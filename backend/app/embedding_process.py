"""Cancellable, bounded CPU model process. No shell or host process access."""

import asyncio
import json
import os
import signal
import sys

from app.db import utcnow
from app.embedding_models import DIMENSION, MAX_CHARACTERS, installation
from app.events import append_event
from app.paths import safe_join


class EmbeddingStopped(Exception):
    pass


def check_running(session, run):
    session.refresh(run)
    active = run.status in {"claimed", "preparing", "running"}
    session.commit()
    if not active:
        raise EmbeddingStopped("The embedding Run is no longer active")


async def wait_running(session, run, awaitable, seconds=60):
    pending = asyncio.create_task(awaitable)
    try:
        async with asyncio.timeout(seconds):
            while True:
                check_running(session, run)
                ready, _ = await asyncio.wait([pending], timeout=0.2)
                if ready:
                    check_running(session, run)
                    return pending.result()
    finally:
        if not pending.done():
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass


class CpuEmbeddingProcess:
    def __init__(self, session, run, root):
        self.session, self.run, self.root = session, run, root
        self.process = None

    async def wait(self, awaitable, seconds=60):
        return await wait_running(self.session, self.run, awaitable, seconds)

    async def read(self):
        line = await self.wait(self.process.stdout.readline())
        if not line or len(line) > 100000:
            raise ValueError("The CPU embedding process stopped or returned an oversized result")
        try:
            return json.loads(line)
        except ValueError as exc:
            raise ValueError("The CPU embedding process returned invalid JSON") from exc

    async def open(self):
        if not installation(self.root)["installed"]:
            raise ValueError("Prepare the local embedding model first")
        check_running(self.session, self.run)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "PYTHONPATH", "LANG", "LC_ALL", "TZ", "LD_LIBRARY_PATH"}
        }
        environment.update(
            OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="2",
            MKL_NUM_THREADS="2",
            TOKENIZERS_PARALLELISM="false",
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
        )
        relative = f"runs/{self.run.id}/embedding.stderr.log"
        path = safe_join(self.root, relative)
        path.parent.mkdir(exist_ok=True, parents=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as log:
            self.process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.embedding_cpu",
                str(self.root),
                str(os.getpid()),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=log,
                start_new_session=True,
                env=environment,
                limit=100001,
            )
        self.run.stderr_log = relative
        self.run.pid = self.run.process_group_id = self.process.pid
        self.run.metadata_json = {
            **self.run.metadata_json,
            "cpu_process": {
                "pid": self.process.pid,
                "parent_pid": os.getpid(),
                "worker_id": self.run.worker_id,
                "started_at": utcnow().isoformat(),
                "device": "CPU",
                "threads": 2,
                "maximum_address_space_bytes": 2 * 1024**3,
                "parent_death_signal": "SIGKILL",
            },
        }
        append_event(
            self.session, self.run.id, "embedding.cpu.started", self.run.metadata_json["cpu_process"]
        )
        self.session.commit()
        value = await self.read()
        if value != {"ready": True, "device": "CPU", "dimension": DIMENSION}:
            raise ValueError("CPU embedding model readiness was not verified")
        return self

    async def encode(self, text, kind):
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > MAX_CHARACTERS
            or kind not in {"query", "passage"}
        ):
            raise ValueError("Invalid bounded embedding request")
        check_running(self.session, self.run)
        self.process.stdin.write(
            (json.dumps({"text": text, "kind": kind}, ensure_ascii=False) + "\n").encode()
        )
        await self.wait(self.process.stdin.drain())
        value = await self.read()
        from app.embeddings import validate_vector

        if not isinstance(value, dict) or set(value) != {"vector", "chunks"}:
            raise ValueError("CPU embedding response is invalid")
        vector = validate_vector(value["vector"])
        if len(vector) != DIMENSION or type(value["chunks"]) is not int or not 1 <= value["chunks"] <= 256:
            raise ValueError("CPU embedding response is outside its profile")
        check_running(self.session, self.run)
        return vector

    async def close(self):
        process = self.process
        if process is None:
            return
        try:
            if not self.session.is_active:
                self.session.rollback()
            else:
                self.session.commit()
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=2)
                except TimeoutError:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await process.wait()
        # Never hold a SQLite reservation while waiting for model shutdown.
        if not self.session.is_active:
            self.session.rollback()
        self.session.refresh(self.run)
        self.run.metadata_json = {**self.run.metadata_json, "cpu_process_confirmed_gone": True}
        append_event(self.session, self.run.id, "embedding.cpu.stopped", {"exit_code": process.returncode})
        self.session.commit()
