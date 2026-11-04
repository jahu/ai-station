"""Bounded, read-only Metal facts. Working-set guidance is not free/dedicated VRAM."""

import ctypes
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_DEVICES = 32
MAX_NAME_BYTES = 512
MAX_REPORT_BYTES = 65536
PROBE_SECONDS = 5


def unavailable():
    return {"source": "metal", "status": "unavailable", "complete": False, "devices": []}


def _report(devices):
    if not isinstance(devices, list) or len(devices) > MAX_DEVICES:
        raise ValueError("Invalid native Metal device inventory")
    seen = set()
    partial = False
    for item in devices:
        if not isinstance(item, dict) or set(item) != {
            "registry_id",
            "name",
            "unified_memory",
            "recommended_working_set_bytes",
        }:
            raise ValueError("Invalid native Metal fields")
        identity = item["registry_id"]
        if (
            not isinstance(identity, str)
            or not re.fullmatch(r"[a-f0-9]{16}", identity)
            or int(identity, 16) == 0
            or identity in seen
        ):
            raise ValueError("Invalid native Metal identity")
        seen.add(identity)
        name = item["name"]
        if name is not None and (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 256
            or len(name.encode("utf-8")) > MAX_NAME_BYTES
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
        ):
            raise ValueError("Invalid native Metal name")
        unified = item["unified_memory"]
        budget = item["recommended_working_set_bytes"]
        if unified is not None and type(unified) is not bool:
            raise ValueError("Invalid native Metal memory type")
        if budget is not None and (type(budget) is not int or not 0 < budget <= 2**60):
            raise ValueError("Invalid native Metal working-set guidance")
        partial |= name is None or unified is None or budget is None
    return {
        "source": "metal",
        "status": "partial" if partial else "available",
        "complete": True,
        "devices": devices,
    }


class _Native:
    def __init__(self):
        if sys.platform != "darwin" or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise OSError("Native Metal observation requires 64-bit macOS")
        try:
            # Fixed OS frameworks only; no discovery commands, SDK or PyObjC dependency.
            self.foundation = ctypes.CDLL("/System/Library/Frameworks/Foundation.framework/Foundation")
            self.metal = ctypes.CDLL("/System/Library/Frameworks/Metal.framework/Metal")
            self.objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
            self.objc.objc_getClass.argtypes = [ctypes.c_char_p]
            self.objc.objc_getClass.restype = ctypes.c_void_p
            self.objc.sel_registerName.argtypes = [ctypes.c_char_p]
            self.objc.sel_registerName.restype = ctypes.c_void_p
            self.metal.MTLCopyAllDevices.argtypes = []
            self.metal.MTLCopyAllDevices.restype = ctypes.c_void_p
            address = ctypes.cast(self.objc.objc_msgSend, ctypes.c_void_p).value
            if not address:
                raise OSError("Native Objective-C dispatch is unavailable")
            pointer, size = ctypes.c_void_p, ctypes.c_size_t
            signatures = {
                "new": (pointer, ()),
                "drain": (None, ()),
                "release": (None, ()),
                "respondsToSelector:": (ctypes.c_byte, (pointer,)),
                "count": (size, ()),
                "objectAtIndex:": (pointer, (size,)),
                "registryID": (ctypes.c_uint64, ()),
                "name": (pointer, ()),
                "hasUnifiedMemory": (ctypes.c_byte, ()),
                "recommendedMaxWorkingSetSize": (ctypes.c_uint64, ()),
                "lengthOfBytesUsingEncoding:": (size, (size,)),
                "UTF8String": (pointer, ()),
            }
            self.calls = {}
            for name, (result, arguments) in signatures.items():
                selector = self.objc.sel_registerName(name.encode("ascii"))
                if not selector:
                    raise OSError("Native Metal selector is unavailable")
                call = ctypes.CFUNCTYPE(result, pointer, pointer, *arguments)(address)
                self.calls[name] = (selector, call)
            self.pool_class = self.objc.objc_getClass(b"NSAutoreleasePool")
            if not self.pool_class:
                raise OSError("Native autorelease pool is unavailable")
        except (AttributeError, ValueError) as exc:
            raise OSError("Native Metal observation is unavailable") from exc

    def _send(self, target, name, *arguments):
        if not target:
            raise OSError("Native Metal returned an empty object")
        selector, call = self.calls[name]
        return call(target, selector, *arguments)

    def _property(self, target, name):
        selector = self.calls[name][0]
        if not self._send(target, "respondsToSelector:", selector):
            return None
        return self._send(target, name)

    def _name(self, device):
        value = self._property(device, "name")
        if not value:
            return None
        # NSUTF8StringEncoding is 4. Bound before copying any NSString bytes.
        size = self._send(value, "lengthOfBytesUsingEncoding:", 4)
        if not 0 < size <= MAX_NAME_BYTES:
            return None
        pointer = self._send(value, "UTF8String")
        if not pointer:
            return None
        try:
            return ctypes.string_at(pointer, size).decode("utf-8")
        except UnicodeDecodeError:
            return None

    def devices(self):
        pool = self._send(self.pool_class, "new")
        if not pool:
            raise OSError("Native autorelease pool could not be created")
        array = None
        try:
            array = self.metal.MTLCopyAllDevices()
            if not array:
                raise OSError("Native Metal inventory is unavailable")
            count = self._send(array, "count")
            if not 0 <= count <= MAX_DEVICES:
                raise OSError("Native Metal inventory exceeds its bound")
            result = []
            for index in range(count):
                device = self._send(array, "objectAtIndex:", index)
                identity = self._property(device, "registryID")
                if not identity:
                    raise OSError("Native Metal device identity is unavailable")
                unified = self._property(device, "hasUnifiedMemory")
                if unified not in {None, 0, 1}:
                    raise OSError("Invalid native Metal memory type")
                budget = self._property(device, "recommendedMaxWorkingSetSize")
                result.append(
                    {
                        "registry_id": f"{identity:016x}",
                        "name": self._name(device),
                        "unified_memory": None if unified is None else bool(unified),
                        "recommended_working_set_bytes": budget or None,
                    }
                )
            return result
        finally:
            try:
                if array:
                    self._send(array, "release")  # Copy ownership, independent of the pool.
            finally:
                self._send(pool, "drain")


def observe():
    if sys.platform != "darwin":
        return unavailable()
    # Driver/framework loading is isolated from the Runner. A failed/hung probe
    # cannot become a successful no-GPU observation or expose native stderr.
    try:
        with tempfile.TemporaryFile() as output:
            process = subprocess.run(
                [sys.executable, "-I", "-S", "-B", str(Path(__file__).resolve())],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C.UTF-8"},
                timeout=PROBE_SECONDS,
                check=False,
            )
            if process.returncode:
                return unavailable()
            output.seek(0)
            raw = output.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            return unavailable()
        value = json.loads(raw)
        if value == unavailable():
            return unavailable()
        if not isinstance(value, dict) or value.get("complete") is not True:
            return unavailable()
        expected = _report(value["devices"])
        return expected if value == expected else unavailable()
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return unavailable()


if __name__ == "__main__":
    try:
        result = _report(_Native().devices())
    except (OSError, ValueError):
        result = unavailable()
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(1 if result["status"] == "unavailable" else 0)
