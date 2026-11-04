"""Native presentation for the existing desktop supervisor; never a workload API."""

import json
import os
import platform
import re
import subprocess
import time
import webbrowser
from pathlib import Path


def binary(root):
    if platform.system() != "Darwin":
        raise RuntimeError("Native Mac presentation requires macOS")
    root = Path(root).resolve(strict=True)
    metadata = root / "desktop-manifest.json"
    if metadata.is_symlink() or not metadata.is_file() or metadata.stat().st_size > 8 * 1024**2:
        raise ValueError("The native interface requires its packaged manifest")
    value = json.loads(metadata.read_text())
    files = value.get("files") if isinstance(value, dict) else None
    expected = files.get("bin/ai-station-native") if isinstance(files, dict) else None
    path = root / "bin/ai-station-native"
    if (
        not isinstance(expected, str)
        or not re.fullmatch(r"[a-f0-9]{64}", expected)
        or not path.resolve().is_relative_to(root)
        or not path.is_file()
        or not os.access(path, os.X_OK)
    ):
        raise ValueError("The native desktop interface is missing or redirected")
    import hashlib

    with path.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual != expected:
        raise ValueError("The native desktop interface changed")
    return path


def environment():
    # Presentation receives no application/provider, GitHub or SSH credentials.
    return {
        "PATH": os.defpath,
        **{
            key: os.environ[key]
            for key in ("HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "__CF_USER_TEXT_ENCODING")
            if key in os.environ
        },
    }


def payload(value):
    data = json.dumps(value, ensure_ascii=False).encode() + b"\n"
    if len(data) > 16384:
        raise ValueError("Native desktop message exceeds its bounded frame")
    return data


def dialog(root, *args):
    def option(name, fallback):
        return next((arg[len(name) + 1 :] for arg in args if arg.startswith(name + "=")), fallback)

    request = {
        "kind": "question" if "--question" in args else "error" if "--error" in args else "info",
        "text": option("--text", ""),
        "ok": option("--ok-label", "Continue" if "--question" in args else "Close"),
    }
    if "--question" in args:
        request["cancel"] = option("--cancel-label", "Cancel")
    result = subprocess.run(
        [str(binary(root)), "--native-dialog"],
        input=payload(request),
        env=environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError("The native desktop dialog could not complete")
    return result.returncode


def stop_window(process):
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()  # Only this immediate, unreaped presentation child.
        process.wait(timeout=5)


class Preparation:
    def __init__(self, root, *, heading=None, cancelable=False):
        self.cancelable = cancelable
        self.cancel_requested = False
        self.response = b""
        self.process = subprocess.Popen(
            [str(binary(root)), "--native-progress"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE if cancelable else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment(),
        )
        if cancelable:
            os.set_blocking(self.process.stdout.fileno(), False)
            self.process.stdin.write(payload({"cancelable": True}))
            self.process.stdin.flush()
        if heading is not None:
            self.process.stdin.write(payload({"heading": heading}))
            self.process.stdin.flush()

    def stage(self, text):
        if self.process.poll() is None:
            try:
                self.process.stdin.write(payload({"stage": text}))
                self.process.stdin.flush()
            except BrokenPipeError:
                pass  # Closing presentation does not cancel the owned supervisor.

    def update(self, text, *, done=None, total=None, cancelable=True):
        self.stage(text)
        if self.process.poll() is None:
            try:
                self.process.stdin.write(payload({"cancelable": cancelable, "done": done, "total": total}))
                self.process.stdin.flush()
            except BrokenPipeError:
                pass

    def canceled(self):
        if not self.cancelable or self.cancel_requested or self.process.stdout.closed:
            return self.cancel_requested
        try:
            chunk = os.read(self.process.stdout.fileno(), 257)
        except BlockingIOError:
            return False
        self.response += chunk
        if len(self.response) > 256:
            raise ValueError("The native cancellation reply exceeds its bounded frame")
        if b"\n" in self.response:
            if json.loads(self.response) != {"action": "cancel"}:
                raise ValueError("The native progress window returned an unknown action")
            self.cancel_requested = True
        return self.cancel_requested

    def close(self):
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            stop_window(self.process)
        if self.cancelable and self.process.stdout is not None:
            self.process.stdout.close()


def backup_selection(root, *, pending=None, can_abort=True, restore_only=False):
    request = {"pending": pending, "can_abort": can_abort}
    if restore_only:
        request["restore_only"] = True
    return backup_reply(root, "--native-backups", request)


def backup_folder(root):
    return backup_reply(root, "--native-backup-folder", {})


def restore_review(root):
    return backup_reply(root, "--native-restore-review", {})


def administrator_recovery(root):
    from desktop_restore_authority import validate

    value = backup_reply(root, "--native-admin-recovery", {})
    return None if value == {"action": "cancel"} else validate(value)


def backup_reply(root, mode, request):
    result = subprocess.run(
        [str(binary(root)), mode],
        input=payload(request),
        env=environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) > 16384:
        raise RuntimeError("The native backup dialog could not complete")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("The native backup dialog returned an invalid selection")
    return value


def running_window(root, url, *, active):
    while active():
        process = subprocess.Popen(
            [str(binary(root)), "--native-running"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment(),
        )
        try:
            process.stdin.write(
                payload(
                    {
                        "text": "AI Station is running locally.\n\nYour agents and generations keep working in the background. Stop AI Station shuts down this installation and keeps its saved data."
                    }
                )
            )
            process.stdin.close()
            process.stdin = None
            while process.poll() is None and active():
                time.sleep(0.2)
            if process.poll() is None:
                stop_window(process)
                return "ended"
            reply, _ = process.communicate(timeout=5)
            if process.returncode != 0 or len(reply) > 256:
                raise RuntimeError("The native status window returned an invalid response")
            value = json.loads(reply)
            if value == {"action": "stop"}:
                return "stop"
            if value == {"action": "background"}:
                return "background"
            if value != {"action": "open"}:
                raise ValueError("The native status window returned an unknown action")
            webbrowser.open(url)  # Validated private readiness URL never enters native UI frames.
        finally:
            stop_window(process)
    return "ended"
