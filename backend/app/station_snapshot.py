"""Read-only workstation observation, executed by the shared worker."""

import json
import math
import re
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.artifacts import register_file
from app.db import utcnow
from app.events import append_event
from app.models import Message, Run, RuntimeInstance
from app.permissions import require
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, transition
from app.state import TERMINAL, RunStatus


def enqueue_snapshot(session, parent):
    return create_run(
        session,
        parent.task,
        run_type="inspection",
        capability="system.inspect",
        executor_type="station_snapshot",
        parent_run_id=parent.id,
        permissions=["filesystem_read"],
        retry_class="safe",
    )


def _number(value):
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def _text(value):
    return " ".join(str(value or "Unknown").split())[:160]


def _metrics(raw, keys):
    return {key: _number(raw.get(key)) for key in keys}


def _hardware(raw):
    return {
        "gpus": [
            {
                "name": _text(gpu.get("name")),
                **_metrics(
                    gpu, ["index", "utilization", "memory_used_mib", "memory_total_mib", "temperature_c"]
                ),
            }
            for gpu in raw.get("gpus", [])[:32]
        ],
        "cpu": _metrics(raw.get("cpu", {}), ["utilization", "temperature_c"]),
        "memory": _metrics(
            raw.get("memory", {}), ["used_mib", "total_mib", "available_mib", "swap_used_mib"]
        ),
        "disk": _metrics(raw.get("disk", {}), ["used_bytes", "total_bytes", "free_bytes"]),
    }


def _display(value, unit=""):
    return "unavailable" if value is None else f"{value:g}{unit}"


def _markdown(text):
    return re.sub(r"([\\`*_{}\[\]()<>#|!])", r"\\\1", _text(text))


def render_snapshot(snapshot):
    hardware = snapshot["hardware"]
    lines = ["**Workstation snapshot**", f"Observed at {snapshot['sampled_at']} (UTC).", "", "**GPUs**"]
    for gpu in hardware["gpus"]:
        lines.append(
            f"- GPU {_display(gpu['index'])} · {_markdown(gpu['name'])}: "
            f"{_display(gpu['utilization'], '%')} utilization, "
            f"{_display(gpu['memory_used_mib'])} / {_display(gpu['memory_total_mib'], ' MiB')} VRAM, "
            f"{_display(gpu['temperature_c'], ' °C')}."
        )
    if not hardware["gpus"]:
        lines.append("GPU telemetry is unavailable or no GPU was detected.")
    cpu, memory, disk = hardware["cpu"], hardware["memory"], hardware["disk"]
    free_gib = disk["free_bytes"] / 1024**3 if disk["free_bytes"] is not None else None
    lines.extend(
        [
            "",
            f"**CPU:** {_display(cpu['utilization'], '%')} · {_display(cpu['temperature_c'], ' °C')}",
            f"**RAM:** {_display(memory['used_mib'])} / {_display(memory['total_mib'], ' MiB')} · "
            f"{_display(memory['available_mib'], ' MiB')} available",
            f"**Application storage:** {_display(free_gib, ' GiB')} free",
            "",
            "**Active AI Station Runs**",
        ]
    )
    lines.extend(
        f"- {_markdown(row['capability'])}: {_markdown(row['status'])} · Run {row['id']}"
        for row in snapshot["runs"]
    )
    if not snapshot["runs"]:
        lines.append("No other active Runs.")
    lines.extend(["", "**Runtime observations**"])
    lines.extend(
        f"- {_markdown(row['name'])}: {_markdown(row['status'])} ({_markdown(row['ownership'])}); last observed {row['observed_at']}."
        for row in snapshot["runtimes"]
    )
    if not snapshot["runtimes"]:
        lines.append("No saved runtime observations.")
    lines.extend(
        [
            "",
            "GPU metrics are live; runtime states are saved observations, not a new health check. This does not identify unrelated host processes.",
        ]
    )
    return "\n\n".join(lines)


class StationSnapshotExecutor:
    name = "station_snapshot"

    @staticmethod
    def canceled(session, run):
        session.refresh(run)
        if run.status == "cancel_requested":
            transition(session, run, RunStatus.CANCELED, event_type="run.canceled")
        return run.status == "canceled"

    def execute(self, session, run):
        if self.canceled(session, run):
            return "done"
        require(run.effective_permissions, "filesystem_read")
        transition(session, run, RunStatus.PREPARING, event_type="executor.preparing")
        transition(session, run, RunStatus.RUNNING, event_type="executor.started")
        append_event(session, run.id, "tool.requested", {"tool": "system_snapshot"})
        session.commit()
        # The endpoint accepts no path, URL, command or process-control input.
        try:
            hardware = _hardware(RunnerClient(timeout=8).hardware())
        except (RunnerError, RunnerUnavailable):
            if self.canceled(session, run):
                return "done"
            append_event(session, run.id, "tool.failed", {"tool": "system_snapshot"})
            session.commit()
            raise
        if self.canceled(session, run):
            return "done"
        runs = list(
            session.scalars(
                select(Run)
                .where(Run.status.not_in(TERMINAL), Run.id != run.id)
                .order_by(Run.created_at.desc(), Run.id)
                .limit(12)
            )
        )
        runtimes = list(
            session.scalars(
                select(RuntimeInstance)
                .order_by(RuntimeInstance.updated_at.desc(), RuntimeInstance.id)
                .limit(12)
            )
        )
        snapshot = {
            "sampled_at": utcnow().isoformat(),
            "hardware": hardware,
            "runs": [{"id": row.id, "capability": row.capability, "status": row.status} for row in runs],
            "runtimes": [
                {
                    "name": _text(row.name),
                    "status": row.status,
                    "ownership": row.ownership,
                    "observed_at": row.updated_at.isoformat(),
                }
                for row in runtimes
            ],
        }
        report = render_snapshot(snapshot)
        for suffix, kind, mime, content in [
            (".json", "json", "application/json", json.dumps(snapshot, ensure_ascii=False)),
            (".md", "markdown", "text/markdown", report),
        ]:
            with tempfile.NamedTemporaryFile(mode="w+", suffix=suffix, encoding="utf-8") as source:
                source.write(content)
                source.flush()
                register_file(
                    session,
                    source=Path(source.name),
                    artifact_type=kind,
                    mime_type=mime,
                    original_filename="workstation-snapshot" + suffix,
                    run_id=run.id,
                    metadata={"system_snapshot": True},
                )
        message = session.scalar(
            select(Message).where(
                Message.run_id == run.parent_run_id,
                Message.conversation_id == run.conversation_id,
                Message.role == "assistant",
            )
        )
        if message and message.metadata_json.get("orchestration"):
            message.content = report
        run.summary = "Current workstation telemetry and saved activity observed."
        append_event(
            session,
            run.id,
            "tool.completed",
            {"tool": "system_snapshot", "sampled_at": snapshot["sampled_at"]},
        )
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed")
        session.commit()
        return "done"
