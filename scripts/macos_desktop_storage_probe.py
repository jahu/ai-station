"""Native long-path desktop/control experiment; no Docker, workload or user data."""

import json
import os
import platform
import sys
import tempfile
from pathlib import Path


def main():
    if platform.system() != "Darwin" or not sys.flags.isolated or not sys.dont_write_bytecode:
        raise RuntimeError("Use isolated/no-bytecode native Mac application Python")
    source = Path(__file__).resolve().parent
    sys.path.insert(0, str(source))  # Reviewed desktop scripts, never Host Runner source.
    import desktop
    from desktop_control import CONTROL_FILE, DesktopControl, request
    from dotenv import dotenv_values

    native = None
    with tempfile.TemporaryDirectory(prefix="ais-desktop-", dir="/private/tmp") as temporary:
        root = (
            Path(temporary).resolve()
            / ("Long użytkownik home " + "u" * 80)
            / "Library/Application Support/AI Station"
        )
        root.mkdir(mode=0o700, parents=True)
        try:
            native = desktop.control_directory(root)
            config = desktop.configuration(root)
            values = dotenv_values(config)
            runner = Path(values["AI_STATION_RUNNER_SOCKET"])
            if len(os.fsencode(root)) <= 104 or len(os.fsencode(native / CONTROL_FILE)) >= 104:
                raise ValueError("The native control namespace did not shorten its data path")
            if (native / CONTROL_FILE).is_relative_to(runner.parent):
                raise ValueError("Desktop lifecycle authority entered the Runner mount")
            keep = root / "data/keep.txt"
            keep.write_text("neutral native storage fixture")
            before = config.read_bytes()
            with DesktopControl(native) as control:
                status = request(native)
                if status["instance_id"] != control.instance_id:
                    raise ValueError("Native desktop instance identity changed")
                try:
                    request(native, "stop", instance_id="0" * 32)
                except ValueError:
                    pass
                else:
                    raise ValueError("A stale native instance was allowed to Stop")
                if control.stop_requested.is_set():
                    raise ValueError("A stale native instance changed control state")
                request(native, "stop", instance_id=control.instance_id)
                if not control.stop_requested.is_set():
                    raise ValueError("The matching native Stop request was not accepted")
            if (
                (native / CONTROL_FILE).exists()
                or config.read_bytes() != before
                or keep.read_text() != "neutral native storage fixture"
            ):
                raise ValueError("Native control cleanup changed data or left a socket")
        finally:
            if native is not None:
                runner_dir = native / "runner"
                if runner_dir.exists():
                    runner_dir.rmdir()  # Never recursively remove unexpected contents.
                (native / "desktop-owner.json").unlink()
                native.rmdir()
    value = {
        "platform": "Darwin",
        "architecture": platform.machine(),
        "os_version": platform.mac_ver()[0],
        "native_desktop_storage_passed": True,
        "long_data_path": True,
        "private_stop_channel": True,
        "runner_mount_separate": True,
        "stale_instance_refused": True,
        "matching_stop_accepted": True,
        "data_preserved": True,
        "socket_cleanup_confirmed": True,
        "macos_installer_qualified": False,
        "model_inference_tested": False,
    }
    print(json.dumps(value, sort_keys=True))
    return value


if __name__ == "__main__":
    main()
