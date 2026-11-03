"""Native Linux setup consent. No HTTP, Runner or agent entry point."""

import fcntl
import json
import os
import platform
import subprocess
from pathlib import Path

from desktop_docker_access import STATION, trusted
from desktop_versions import directory, read_private
from linux_gpu_probe import command, gpu_uuids, native_linux, nvidia_present, probe, write_private
from windows_gpu_bundle import RECIPE

HELPER = Path("/usr/libexec/ai-station/gpu-access")
POLICY = Path("/usr/share/polkit-1/actions/org.ai-station.gpu-access.policy")


def enabled(value):
    return value.get("linux_gpu_recipe") == RECIPE and native_linux()


def preference(root):
    path = root / "graphics-choice.json"
    if not path.exists() and not path.is_symlink():
        return None
    value = json.loads(read_private(path, 4096))
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "choice"}
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or value["choice"] not in {"cpu", "pending", "restart"}
    ):
        raise ValueError("The private graphics setup choice needs inspection")
    return value["choice"]


def save(root, choice):
    write_private(root / "graphics-choice.json", {"schema": 1, "choice": choice})


def system_engine(engine):
    """Only the observed system socket may enter the fixed privileged setup."""
    result = command(engine, "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}")
    if result.returncode:
        return False
    endpoint = engine.environment.get("DOCKER_HOST") or json.loads(result.stdout)
    if engine.environment.get("DOCKER_CONTEXT"):
        endpoint = json.loads(result.stdout)
    if endpoint not in {"unix:///run/docker.sock", "unix:///var/run/docker.sock"}:
        return False
    result = command(engine, "info", "--format", "{{json .SecurityOptions}}")
    return not result.returncode and not any("rootless" in str(v) for v in json.loads(result.stdout))


def prepare(
    root,
    value,
    engine,
    *,
    before_dialog=lambda: None,
    stop_requested=lambda: False,
    console=False,
    force=False,
):
    if not enabled(value):
        return "not_applicable"
    directory(root)
    descriptor = os.open(root / "graphics-setup.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        read_private(root / "graphics-setup.lock", 0)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Graphics setup is already open. Finish its existing window first") from None
        return _prepare(root, value, engine, before_dialog, stop_requested, console, force)
    finally:
        os.close(descriptor)


def _prepare(root, value, engine, before_dialog, stopped, console, force):
    choice = preference(root)
    uuids = gpu_uuids()
    if not uuids and not nvidia_present():
        return "not_applicable"
    if stopped():
        return "canceled"
    if uuids and probe(root, value["image_id"], engine, uuids):
        (root / "graphics-choice.json").unlink(missing_ok=True)
        return "ready"
    if choice == "cpu" and not force:
        return "cpu"
    if console:
        raise RuntimeError(
            "Open the installed AI Station desktop application to choose graphics setup or CPU"
        )
    before_dialog()

    def ask(text, *, authorize=False, remember=True):
        if stopped():
            return "canceled"
        result = subprocess.run(
            [
                "zenity",
                "--title=AI Station",
                "--width=560",
                "--question",
                "--text=" + text,
                "--ok-label=" + ("Enable GPU features" if authorize else "Use CPU for now"),
                "--cancel-label=Close",
                *(["--extra-button=Use CPU for now"] if authorize else []),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip() == "Use CPU for now" or (not authorize and result.returncode == 0):
            if remember:
                save(root, "cpu")
            return "cpu"
        return "authorize" if authorize and result.returncode == 0 else "canceled"

    if choice == "restart":
        return ask(
            "Graphics tools are prepared, but GPU access is not ready yet.\n\n"
            "Save your work and restart your computer normally, then open AI Station again. "
            "AI Station will check actual GPU access. It will not restart Docker or other apps.\n\n"
            "You can use CPU chat in the meantime. Enable graphics later from the AI Station "
            "desktop controls → Graphics setup. Native media still needs its own compatible hardware.",
            remember=False,
        )
    supported = platform.freedesktop_os_release()
    available = bool(uuids) and supported.get("ID") == "ubuntu" and supported.get("VERSION_ID") == "24.04"
    available = available and system_engine(engine) and all(trusted(p) for p in (HELPER, POLICY, STATION))
    if not available:
        return ask(
            "Your graphics setup needs attention before container-based GPU features can run.\n\n"
            "Automatic setup supports Ubuntu 24.04 with a working NVIDIA driver and the system "
            "Docker Engine. Existing Desktop, rootless or remote engines and OS drivers are preserved. "
            "Ask your administrator to prepare NVIDIA Container Toolkit for your selected engine.\n\n"
            "You can start CPU chat now. To check again later, open the AI Station desktop "
            "controls → Graphics setup."
        )
    answer = ask(
        "Enable GPU features for local chat and images?\n\n"
        "AI Station will install about 9 MB of verified NVIDIA container tools and add their "
        "runtime to system Docker. Your existing settings are preserved. Drivers, CUDA and models "
        "are not installed. No containers or services are stopped.\n\n"
        "Your operating system will ask for administrator authentication; AI Station never "
        "receives that password. Afterward, save your work and restart your computer normally.\n\n"
        "You can also use CPU chat now and enable graphics later from the desktop controls.",
        authorize=True,
    )
    if answer != "authorize" or stopped():
        return "canceled" if stopped() else answer
    save(root, "pending")
    # Never interrupt a package-manager transaction on the native Stop action.
    # The fixed helper bounds its own operations and retains a recovery receipt.
    result = subprocess.run(
        ["/usr/bin/pkexec", "--disable-internal-agent", str(HELPER)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 126:
        if choice is None:
            (root / "graphics-choice.json").unlink()
        else:
            save(root, choice)
        return "canceled"
    if result.returncode:
        raise RuntimeError(
            "Graphics preparation did not finish. Its inspection receipt was preserved. "
            "Reopen Graphics setup or ask your administrator; no AI Station work was started."
        )
    try:
        response = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise RuntimeError(
            "Graphics setup acknowledgement is uncertain. Reopen Graphics setup to inspect it"
        ) from None
    if response != {"status": "prepared", "restart_required": True, "gpu_ready": False}:
        raise RuntimeError("Graphics setup needs inspection before continuing")
    save(root, "restart")
    if stopped():
        return "canceled"
    return ask(
        "Graphics tools are prepared.\n\nSave your work and restart your computer normally, "
        "then open AI Station again. GPU access will be checked after restart. "
        "Your other apps and containers have not been stopped.\n\nYou can use CPU chat in the meantime.",
        remember=False,
    )
