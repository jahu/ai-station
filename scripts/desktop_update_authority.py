"""Native read-only recheck of the exact standalone administrator update Run."""

import json
import sqlite3
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID

import desktop_versions as versions
from ai_station_runner.station_release_metadata import update_request

GATE = "station_update_dispatch_gate"


def authority(root, run_id, *, expected=None, idle=False):
    if not isinstance(run_id, str) or str(UUID(run_id)) != run_id:
        raise ValueError("Use a canonical desktop update Run identity")
    data, namespace = versions.namespace(root / "desktop.env")
    receipt = versions.load(root)
    if receipt["namespace_sha256"] != namespace or receipt["phase"] != "ready":
        raise ValueError("The running desktop no longer matches its private installation")
    database = data / "db/ai-station.sqlite"
    with sqlite3.connect(f"file:{quote(str(database), safe='/')}?mode=ro", uri=True, timeout=2) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        row = connection.execute(
            "SELECT r.*, u.enabled AS account_enabled, u.is_admin AS account_admin, "
            "u.bootstrap_pending AS account_pending, t.owner_id AS task_owner, "
            "t.agent_id AS task_agent, t.project_id AS task_project, t.conversation_id AS task_conversation "
            "FROM runs r JOIN users u ON u.id=r.owner_id JOIN tasks t ON t.id=r.task_id WHERE r.id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ValueError("The administrator update Run is unavailable")
        parameters = update_request(json.loads(row["parameters"]))
        if (
            not row["account_enabled"]
            or not row["account_admin"]
            or row["account_pending"]
            or row["task_owner"] != row["owner_id"]
            or row["executor_type"] != "station_update"
            or row["run_type"] != "maintenance"
            or row["capability"] != "station.updates.install"
            or row["execution_target"] != "host"
            or json.loads(row["effective_permissions"]) != ["manage_station", "network_read"]
            or any(
                row[key]
                for key in (
                    "agent_id",
                    "project_id",
                    "conversation_id",
                    "parent_run_id",
                    "task_agent",
                    "task_project",
                    "task_conversation",
                )
            )
            or row["status"] not in {"running", "cancel_requested"}
            or parameters["current_version"] != receipt["package"]["version"]
            or expected is not None
            and parameters != expected
        ):
            raise ValueError("The native update no longer has its exact administrator authority")
        if row["lease_expires_at"] is None:
            raise ValueError("The native update has no live worker claim")
        lease = datetime.fromisoformat(row["lease_expires_at"]).replace(tzinfo=UTC)
        if lease <= datetime.now(UTC):
            raise ValueError("The native update worker claim expired")
        if idle:
            if row["status"] != "running":
                raise ValueError("The desktop update was canceled before activation")
            saved = connection.execute("SELECT value FROM settings WHERE key=?", (GATE,)).fetchone()
            if saved is None:
                raise ValueError("The desktop update has not acquired its idle dispatch gate")
            claimed = datetime.fromisoformat(row["claimed_at"]).replace(tzinfo=UTC).isoformat()
            expected_gate = {
                "schema": 1,
                "run_id": run_id,
                "owner_id": row["owner_id"],
                "worker_id": row["worker_id"],
                "claimed_at": claimed,
            }
            if json.loads(saved[0]) != expected_gate:
                raise ValueError("The native update idle gate belongs to another claim")
            busy = connection.execute(
                "SELECT id FROM runs WHERE id<>? AND status IN ('claimed','preparing','running','cancel_requested','waiting_for_tool') LIMIT 1",
                (run_id,),
            ).fetchone()
            if busy:
                raise ValueError("Other work is still active; the desktop was not stopped")
    return {
        "request": parameters,
        "canceled": row["status"] == "cancel_requested",
        "namespace_sha256": namespace,
    }
