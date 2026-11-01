"""Simulated native ABI/probe boundaries; actual Mac observation is opt-in."""

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from ai_station_runner import darwin_metal as metal
from ai_station_runner import telemetry


def device(**changes):
    return (
        dict(
            registry_id="0000000000000123",
            name="Apple test GPU",
            unified_memory=True,
            recommended_working_set_bytes=12 * 1024**3,
        )
        | changes
    )


@pytest.fixture
def bridge(monkeypatch):
    state = {
        "calls": [],
        "libraries": [],
        "signatures": [],
        "devices": [device()],
        "missing": set(),
        "array": 20,
        "pool": 101,
        "count": None,
        "fail": None,
    }
    selectors = {}
    names = {}
    buffers = []

    def select(name):
        name = name.decode("ascii")
        value = len(selectors) + 1
        selectors[name] = value
        names[value] = name
        return value

    def dispatch(result_type, target, selector, *args):
        name = names[selector]
        state["calls"].append((target, name, args))
        if state["fail"] == name:
            raise OSError("Simulated native observation failure")
        if name == "new":
            assert target == 100 and result_type is ctypes.c_void_p
            return state["pool"]
        if name in {"release", "drain"}:
            assert result_type is None
            return None
        if name == "count":
            assert target == 20 and result_type is ctypes.c_size_t
            return len(state["devices"]) if state["count"] is None else state["count"]
        if name == "objectAtIndex:":
            assert target == 20 and len(args) == 1
            return 1000 + args[0]
        if name == "respondsToSelector:":
            return 0 if names[args[0]] in state["missing"] else 1
        if target >= 3000:
            raw = state.get("name_bytes", state["devices"][target - 3000]["name"].encode())
            if name == "lengthOfBytesUsingEncoding:":
                assert args == (4,)
                return len(raw)
            assert name == "UTF8String"
            value = ctypes.create_string_buffer(raw)
            buffers.append(value)
            return ctypes.addressof(value)
        item = state["devices"][target - 1000]
        return {
            "registryID": int(item["registry_id"], 16),
            "name": target + 2000,
            "hasUnifiedMemory": int(item["unified_memory"]),
            "recommendedMaxWorkingSetSize": item["recommended_working_set_bytes"],
        }[name]

    def function_types(result, *arguments):
        state["signatures"].append((result, arguments))

        def bind(address):
            assert address == 0x1234
            return lambda target, selector, *args: dispatch(result, target, selector, *args)

        return bind

    def copy():
        state["calls"].append((0, "MTLCopyAllDevices", ()))
        return state["array"]

    native_metal = SimpleNamespace(MTLCopyAllDevices=copy)
    objc = SimpleNamespace(
        objc_getClass=lambda name: 100 if name == b"NSAutoreleasePool" else None,
        sel_registerName=select,
        objc_msgSend=object(),
    )

    def load(path):
        state["libraries"].append(path)
        return native_metal if path.endswith("/Metal") else objc if path.endswith(".dylib") else object()

    def cast(value, kind):
        assert value is objc.objc_msgSend and kind is ctypes.c_void_p
        return SimpleNamespace(value=0x1234)

    monkeypatch.setattr(metal, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(
        metal,
        "ctypes",
        SimpleNamespace(
            **(
                vars(ctypes)
                | {
                    "CDLL": load,
                    "CFUNCTYPE": function_types,
                    "cast": cast,
                }
            )
        ),
    )
    return state, native_metal, objc


def test_fixed_framework_symbols_and_correct_64_bit_scalar_dispatch(bridge):
    state, library, objc = bridge
    native = metal._Native()
    assert state["libraries"] == [
        "/System/Library/Frameworks/Foundation.framework/Foundation",
        "/System/Library/Frameworks/Metal.framework/Metal",
        "/usr/lib/libobjc.A.dylib",
    ]
    assert library.MTLCopyAllDevices.argtypes == []
    assert library.MTLCopyAllDevices.restype is ctypes.c_void_p
    assert objc.sel_registerName.argtypes == [ctypes.c_char_p]
    assert (ctypes.c_uint64, (ctypes.c_void_p, ctypes.c_void_p)) in state["signatures"]
    assert (ctypes.c_void_p, (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t)) in state["signatures"]
    assert metal._report(native.devices()) == {
        "source": "metal",
        "status": "available",
        "complete": True,
        "devices": [device()],
    }
    assert state["calls"][-2:] == [(20, "release", ()), (101, "drain", ())]
    assert all(
        name not in {"currentAllocatedSize", "newBufferWithLength:options:"} for _, name, _ in state["calls"]
    )


def test_multiple_discrete_and_unified_devices_are_not_added_to_system_ram(bridge):
    state, _, _ = bridge
    second = device()
    second.update(registry_id="0000000000000456", name="AMD test GPU", unified_memory=False)
    state["devices"].append(second)
    report = metal._report(metal._Native().devices())
    assert report["devices"] == state["devices"]
    assert all(
        set(item) == {"registry_id", "name", "unified_memory", "recommended_working_set_bytes"}
        for item in report["devices"]
    )


@pytest.mark.parametrize(
    "name,field",
    [
        ("name", "name"),
        ("hasUnifiedMemory", "unified_memory"),
        ("recommendedMaxWorkingSetSize", "recommended_working_set_bytes"),
    ],
)
def test_optional_unsupported_properties_are_unknown_not_invented(bridge, name, field):
    state, _, _ = bridge
    state["missing"].add(name)
    report = metal._report(metal._Native().devices())
    assert report["status"] == "partial" and report["complete"] is True
    assert report["devices"][0][field] is None


@pytest.mark.parametrize("raw", [b"", b"x" * 513, b"\xff"])
def test_name_byte_copy_is_bounded_and_invalid_encoding_stays_unknown(bridge, raw):
    state, _, _ = bridge
    state["name_bytes"] = raw
    assert metal._report(metal._Native().devices())["devices"][0]["name"] is None
    if len(raw) > 512 or not raw:
        assert not any(name == "UTF8String" for _, name, _ in state["calls"])


def test_zero_recommended_size_is_not_free_memory_or_a_cap(bridge):
    state, _, _ = bridge
    state["devices"][0]["recommended_working_set_bytes"] = 0
    report = metal._report(metal._Native().devices())
    assert report["status"] == "partial"
    assert report["devices"][0]["recommended_working_set_bytes"] is None


@pytest.mark.parametrize(
    "problem", ["missing_id", "nil_array", "too_many", "dispatch_error", "release_error"]
)
def test_failed_native_enumeration_always_releases_retained_objects(bridge, problem):
    state, _, _ = bridge
    if problem == "missing_id":
        state["missing"].add("registryID")
    if problem == "nil_array":
        state["array"] = None
    if problem == "too_many":
        state["count"] = metal.MAX_DEVICES + 1
    if problem == "dispatch_error":
        state["fail"] = "objectAtIndex:"
    if problem == "release_error":
        state["fail"] = "release"
    with pytest.raises(OSError):
        metal._Native().devices()
    assert state["calls"][-1] == (101, "drain", ())
    assert any(name == "release" for _, name, _ in state["calls"]) == (problem != "nil_array")


def test_a_successful_empty_array_is_distinct_from_failed_inspection(bridge):
    state, _, _ = bridge
    state["devices"] = []
    assert metal._report(metal._Native().devices()) == {
        "source": "metal",
        "status": "available",
        "complete": True,
        "devices": [],
    }
    assert metal.unavailable()["complete"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("registry_id", "0000000000000000"),
        ("registry_id", "ABC"),
        ("name", "\nprivate"),
        ("name", "x" * 257),
        ("name", 12),
        ("unified_memory", 1),
        ("unified_memory", "true"),
        ("recommended_working_set_bytes", True),
        ("recommended_working_set_bytes", 0),
        ("recommended_working_set_bytes", -1),
        ("recommended_working_set_bytes", 1.5),
        ("recommended_working_set_bytes", 2**60 + 1),
    ],
)
def test_bad_inventory_values_cannot_become_a_hardware_budget(field, value):
    item = device()
    item[field] = value
    with pytest.raises(ValueError):
        metal._report([item])


def test_duplicate_identity_and_incomplete_schema_are_not_successful_enumeration():
    for items in [[device(), device()], [dict(registry_id="0000000000000123")]]:
        with pytest.raises(ValueError):
            metal._report(items)


@pytest.mark.parametrize(
    "failure", [None, "exit", "timeout", "os_error", "oversize", "garbage", "header", "nonbool_header"]
)
def test_probe_is_fixed_isolated_bounded_and_does_not_reflect_errors(monkeypatch, failure):
    monkeypatch.setattr(metal, "sys", SimpleNamespace(platform="darwin", executable=sys.executable))
    report = metal._report([device()])

    def run(argv, **kwargs):
        assert argv == [sys.executable, "-I", "-S", str(Path(metal.__file__).resolve())]
        assert kwargs["stdin"] == kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C.UTF-8"}
        assert kwargs["timeout"] == 5 and kwargs["check"] is False
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 5, stderr=b"PRIVATE-TOKEN")
        if failure == "os_error":
            raise OSError("PRIVATE-TOKEN")
        if failure == "header":
            report["complete"] = False
        if failure == "nonbool_header":
            report["complete"] = 1
        data = json.dumps(report).encode()
        if failure == "oversize":
            data = b"x" * 65537
        if failure == "garbage":
            data = b"PRIVATE-TOKEN"
        kwargs["stdout"].write(data)
        return SimpleNamespace(returncode=1 if failure == "exit" else 0)

    monkeypatch.setattr(metal, "subprocess", SimpleNamespace(**(vars(subprocess) | {"run": run})))
    result = metal.observe()
    assert result == (report if failure is None else metal.unavailable())
    assert "PRIVATE-TOKEN" not in json.dumps(result)


def test_linux_never_loads_or_launches_a_metal_probe(monkeypatch):
    monkeypatch.setattr(metal, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(metal, "ctypes", SimpleNamespace(CDLL=lambda _: pytest.fail("No native library")))
    monkeypatch.setattr(
        metal,
        "subprocess",
        SimpleNamespace(**(vars(subprocess) | {"run": lambda *a, **k: pytest.fail("No subprocess")})),
    )
    assert metal.observe() == metal.unavailable()
    with pytest.raises(OSError):
        metal._Native()


def test_actual_isolated_cli_on_linux_reports_unavailable_not_mac_success():
    if sys.platform != "linux":
        pytest.skip("Linux negative control")
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(Path(metal.__file__).resolve())],
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1 and result.stderr == b""
    assert json.loads(result.stdout) == metal.unavailable()


def test_collect_keeps_metal_separate_from_cuda_gpu_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(telemetry, "cpu", lambda: {})
    monkeypatch.setattr(telemetry, "memory", lambda: {})
    monkeypatch.setattr(telemetry, "disk", lambda _: {})
    monkeypatch.setattr(telemetry, "load", lambda: {})
    report = metal._report([device()])
    monkeypatch.setattr(metal, "observe", lambda: report)
    assert telemetry.collect(tmp_path) == {
        "gpus": [],
        "metal": report,
        "cpu": {},
        "memory": {},
        "disk": {},
        "load": {},
    }


@pytest.mark.skipif(
    sys.platform != "darwin" or os.getenv("AI_STATION_REAL_MAC_METAL_TESTS") != "1",
    reason="Opt-in real Mac Metal observation; Linux ABI simulations do not qualify Mac",
)
def test_actual_native_mac_metal_observation():
    result = metal.observe()
    assert result["complete"] and result["status"] in {"available", "partial"}
    assert metal._report(result["devices"]) == result
