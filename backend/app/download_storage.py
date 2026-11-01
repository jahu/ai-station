"""Physical backing-volume admission around existing model download Runs."""

import shutil
import time

HEADROOM = 256 * 1024**2


def capacity(usage, hardware):
    report = (hardware.get("disk") or {}).get("physical_storage")
    if hardware.get("storage_unavailable"):
        raise ValueError("Connect the Host Runner to inspect application storage")
    if report is None:
        return {"free_bytes": usage.free, "total_bytes": usage.total, "headroom_bytes": HEADROOM}
    if (
        not isinstance(report, dict)
        or report.get("status") != "ready"
        or type(report.get("free_bytes")) is not int
        or type(report.get("total_bytes")) is not int
        or not 0 <= report["free_bytes"] <= report["total_bytes"] <= 2**60
        or report["total_bytes"] == 0
    ):
        raise ValueError(
            "Reopen AI Station's Windows controls to refresh physical disk space before downloading"
        )
    return {
        "free_bytes": min(usage.free, report["free_bytes"]),
        "total_bytes": min(usage.total, report["total_bytes"]),
        "headroom_bytes": HEADROOM,
    }


class DownloadStorage:
    def __init__(self, folder, hardware, runner, remaining):
        self.folder = folder
        self.hardware = hardware
        self.runner = runner
        self.remaining = remaining
        self.windows = (hardware.get("disk") or {}).get("physical_storage") is not None
        self.observed = time.monotonic()
        self.local_free = shutil.disk_usage(folder).free

    def check(self):
        if self.windows and time.monotonic() - self.observed >= 5:
            fresh = self.runner.hardware()
            if (fresh.get("disk") or {}).get("physical_storage") is None:
                raise ValueError(
                    "Windows physical disk observation disappeared; saved downloads were preserved"
                )
            self.hardware = fresh
            self.local_free = shutil.disk_usage(self.folder).free
            self.observed = time.monotonic()
        usage = shutil.disk_usage(self.folder)
        hardware = self.hardware
        if self.windows:
            # Account for local writes between native telemetry refreshes too.
            report = dict((hardware.get("disk") or {}).get("physical_storage") or {})
            if type(report.get("free_bytes")) is int:
                report["free_bytes"] = max(0, report["free_bytes"] - max(0, self.local_free - usage.free))
            hardware = {**hardware, "disk": {"physical_storage": report}}
        value = capacity(usage, hardware)
        if value["free_bytes"] < self.remaining() + HEADROOM:
            raise ValueError("Not enough free application storage for model files and download headroom")
