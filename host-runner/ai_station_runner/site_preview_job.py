"""Owned offline Chromium session; immutable build broker and typed action mailbox."""

import asyncio
import base64
import hashlib
import io
import json
import os
import time
from contextlib import suppress
from uuid import UUID

from ai_station_runner.python_job import read_stderr
from ai_station_runner.site_preview_protocol import (
    MAX_ACTIONS,
    MAX_FRAME,
    MAX_LINE,
    action_request,
    asset_path,
)
from ai_station_runner.site_preview_runs import (
    PreviewAction,
    PreviewRequest,
    action_result,
    container_identity,
    docker,
    frame_metadata,
    inspect_container,
    load_request,
    locked,
    path,
    read,
    save,
    stop_container,
)
from ai_station_runner.site_preview_source import BuildSource


def ensure_registered(run_id, executor):
    from ai_station_runner.config import get_settings
    from ai_station_runner.processes import ProcessManager, ProcessNotOwned

    manager = ProcessManager(get_settings().host_data_dir())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            record = manager.inspect(run_id)
            if record["executor"] != executor or record["pid"] != os.getpid() or not record["alive"]:
                raise ValueError("Preview wrapper does not own its registered process")
            return
        except ProcessNotOwned:
            time.sleep(0.02)
    raise ValueError("Preview dispatch has no persisted process owner")


def create_container(run_id, saved):
    with locked(path(run_id, "container.lock")):
        if path(run_id, "cancel.json").exists():
            raise InterruptedError("Preview canceled before container creation")
        filename = path(run_id, "container.json")
        if filename.exists():
            raise ValueError("Preview container dispatch is never replayed")
        name, labels = container_identity(saved)
        save(filename, {"state": "creating", "id": None})
        args = ["create", "--pull", "never", "--name", name]
        for key, value in labels.items():
            args += ["--label", f"{key}={value}"]
        args += [
            "--interactive",
            "--init",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "256",
            "--memory",
            "1g",
            "--memory-swap",
            "1g",
            "--cpus",
            "1",
            "--ulimit",
            "nofile=256:256",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=256m",
            saved["image"],
        ]
        cid = docker(args)
        item = inspect_container(saved, cid)
        if item is None:
            raise ValueError("Preview container creation identity could not be confirmed")
        save(filename, {"state": "created", "id": item["Id"]})
        return item["Id"]


def capture(run_id, saved, payload, current_action, revision, remaining):
    expected = {
        "event",
        "action_id",
        "revision",
        "width",
        "height",
        "path",
        "title",
        "blocked_requests",
        "png",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or payload["event"] != "frame"
        or payload["revision"] != revision
        or type(payload["revision"]) is not int
        or payload["action_id"] != current_action
        or not isinstance(payload["png"], str)
        or len(payload["png"]) > (MAX_FRAME + 2) // 3 * 4
    ):
        raise ValueError("Unexpected preview frame or action identity")
    data = base64.b64decode(payload["png"], validate=True)
    if len(data) > remaining:
        raise ValueError("Preview frame budget exceeded")
    frame = {key: value for key, value in payload.items() if key not in {"event", "png"}}
    frame.update(
        relative_path=f"runtime/site-previews/{run_id}/frames/{revision}.png",
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )
    frame_metadata(run_id, frame)
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        if (
            image.format != "PNG"
            or image.size != (frame["width"], frame["height"])
            or getattr(image, "is_animated", False)
        ):
            raise ValueError("Invalid preview PNG frame")
        image.verify()
    filename = path(run_id, f"frames/{revision}.png")
    filename.parent.mkdir(mode=0o700, exist_ok=True)
    with filename.open("xb") as handle:
        os.chmod(handle.fileno(), 0o600)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(filename.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    if current_action:
        action = load_request(current_action, action=True)
        with locked(path(current_action, "action.lock", action=True)):
            if action_result(current_action)["state"] != "sent":
                raise ValueError("Preview interaction was canceled before frame publication")
            save(
                path(current_action, "receipt.json", action=True),
                {"state": "frame", "digest": action["digest"], "frame": frame},
            )
    save(path(run_id, "state.json"), {"request_digest": saved["digest"], "frame": frame})
    print(
        json.dumps({"event": "preview.frame.created", "revision": revision, "action_id": current_action}),
        flush=True,
    )
    return frame


def next_action(run_id, saved, revision):
    queue = path(run_id, "queue")
    if not queue.exists():
        return None
    entries = [item for item in queue.iterdir() if not item.name.startswith(".preview-")]
    if len(entries) > MAX_ACTIONS:
        raise ValueError("Preview interaction budget exceeded")
    for filename in sorted(entries):
        action_id = str(UUID(filename.stem))
        if filename.name != action_id + ".json":
            raise ValueError("Invalid preview mailbox identity")
        with locked(path(action_id, "action.lock", action=True)):
            if read(path(run_id, "queue/" + filename.name)) != {"run_id": action_id}:
                raise ValueError("Invalid preview mailbox record")
            action = load_request(action_id, action=True)
            body = PreviewAction.model_validate(action["request"])
            if str(body.preview_run_id) != run_id or action["preview_digest"] != saved["digest"]:
                raise ValueError("Interaction belongs to another preview")
            receipt = action_result(action_id)
            if receipt["state"] in {"frame", "rejected", "canceled"}:
                path(run_id, "queue/" + filename.name).unlink()
                continue
            if receipt["state"] != "pending":
                raise ValueError("Uncertain preview interaction is never replayed")
            if body.expected_revision != revision or revision >= MAX_ACTIONS:
                save(
                    path(action_id, "receipt.json", action=True),
                    {"state": "rejected", "digest": action["digest"], "reason": "stale_revision"},
                )
                continue
            parent = PreviewRequest.model_validate(saved["request"])
            request = action_request(body.protocol(), parent.width, parent.height)
            save(path(action_id, "receipt.json", action=True), {"state": "sent", "digest": action["digest"]})
            return request
    return None


async def execute(run_id):
    ensure_registered(run_id, "site_preview")
    saved = load_request(run_id)
    body = PreviewRequest.model_validate(saved["request"])
    expires = saved["created_at"] + body.maximum_runtime
    source = BuildSource(path(run_id, "source.zip"), body.archive.sha256, body.archive.size_bytes, body.entry)
    process = reader = stderr = None
    frame = None
    action = None
    revision = 0
    requests = transferred = frame_bytes = 0
    reason = "expired"
    try:
        if expires <= time.time():
            raise ValueError("Preview expired before execution")
        cid = create_container(run_id, saved)
        process = await asyncio.create_subprocess_exec(
            "docker",
            "start",
            "--attach",
            "--interactive",
            cid,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=MAX_LINE + 1,
        )
        stderr = asyncio.create_task(read_stderr(process.stderr))

        async def send(value):
            process.stdin.write((json.dumps(value) + "\n").encode())
            await process.stdin.drain()

        await send(
            {
                "kind": "open",
                "entry": body.entry,
                "width": body.width,
                "height": body.height,
                "max_seconds": max(1, int(expires - time.time())),
            }
        )
        reader = asyncio.create_task(process.stdout.readline())
        while True:
            if path(run_id, "cancel.json").exists():
                reason = "closed"
                break
            if time.time() >= expires - 1:
                break
            done, _ = await asyncio.wait({reader}, timeout=0.05)
            if reader in done:
                line = reader.result()
                if not line:
                    raise ValueError("Preview renderer ended before the session closed")
                if len(line) > MAX_LINE:
                    raise ValueError("Preview renderer exceeded its protocol limit")
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("Invalid preview renderer message")
                if payload.get("event") == "fetch":
                    requests += 1
                    if (
                        set(payload) != {"event", "id", "path", "document"}
                        or type(payload["id"]) is not int
                        or payload["id"] != requests
                        or requests > 2048
                        or type(payload["document"]) is not bool
                    ):
                        raise ValueError("Invalid preview build resource request")
                    asset_path(payload["path"])
                    status, mime, data = source.resource(payload["path"], document=payload["document"])
                    transferred += len(data)
                    if transferred > 128 * 1024 * 1024:
                        raise ValueError("Preview resource budget exceeded")
                    await send(
                        {
                            "kind": "resource",
                            "id": requests,
                            "status": status,
                            "content_type": mime,
                            "body": base64.b64encode(data).decode(),
                        }
                    )
                elif payload.get("event") == "frame":
                    frame = capture(
                        run_id,
                        saved,
                        payload,
                        action["id"] if action else None,
                        revision,
                        min(MAX_FRAME, 128 * 1024 * 1024 - frame_bytes),
                    )
                    frame_bytes += frame["size_bytes"]
                    if frame_bytes > 128 * 1024 * 1024:
                        raise ValueError("Preview frame budget exceeded")
                    action = None
                elif payload.get("event") == "rejected" and action:
                    if (
                        set(payload) != {"event", "action_id", "revision", "reason"}
                        or payload["action_id"] != action["id"]
                        or payload["revision"] != revision - 1
                        or payload["reason"]
                        not in {"stale_revision", "receipt_conflict", "navigation_blocked"}
                    ):
                        raise ValueError("Invalid preview interaction rejection")
                    saved_action = load_request(action["id"], action=True)
                    with locked(path(action["id"], "action.lock", action=True)):
                        save(
                            path(action["id"], "receipt.json", action=True),
                            {
                                "state": "rejected",
                                "digest": saved_action["digest"],
                                "reason": payload["reason"],
                            },
                        )
                    revision -= 1
                    action = None
                else:
                    raise ValueError("Unexpected preview renderer event")
                reader = asyncio.create_task(process.stdout.readline())
            if frame is not None and action is None:
                action = next_action(run_id, saved, revision)
                if action:
                    revision += 1
                    await send(action)
        with suppress(BrokenPipeError, ConnectionResetError):
            await send({"kind": "close"})
            process.stdin.close()
        if reader:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
            reader = None

        async def drain():
            discarded = 0
            while chunk := await process.stdout.read(65536):
                discarded += len(chunk)
                if discarded > MAX_LINE * 2:
                    raise ValueError("Preview exceeded its closing output budget")

        await asyncio.wait_for(asyncio.gather(process.wait(), drain()), timeout=10)
        if process.returncode != 0 and reason != "closed":
            raise ValueError("Preview renderer did not confirm clean completion")
        save(
            path(run_id, "report.json"),
            {
                "request_digest": saved["digest"],
                "reason": reason,
                "last_revision": frame["revision"] if frame else None,
            },
        )
    finally:
        if reader:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        cleanup = await asyncio.to_thread(stop_container, run_id)
        if process and process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()
                await process.wait()
        if stderr:
            await stderr
        if not cleanup:
            raise ValueError("Preview container cleanup requires inspection")


if __name__ == "__main__":
    import sys

    try:
        asyncio.run(execute(str(UUID(sys.argv[1]))))
    except Exception as exc:
        print(
            "Preview stopped: " + type(exc).__name__ + (": " + str(exc) if type(exc) is ValueError else ""),
            file=sys.stderr,
        )
        raise SystemExit(1) from None
