"""Typed native desktop update bridge. It grants no host installation commands."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ai_station_runner.config import get_settings
from ai_station_runner.desktop_update_channel import command, request

router = APIRouter(prefix="/v1/station/updates")
# Native Linux passed frozen-package preserving apply, restart, cold recovery
# and subsequent stock-launch qualification. Windows/macOS remain unavailable.
QUALIFIED_PLATFORMS = frozenset({"linux-amd64"})


def qualified(value):
    platform = value.get("platform")
    return value.get("installed") is True and isinstance(platform, str) and platform in QUALIFIED_PLATFORMS


class UpdateOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["prepare", "inspect", "apply", "cancel"]
    run_id: UUID
    request: dict | None = None
    permissions: list[str] = Field(max_length=4)


def native(value):
    path = get_settings().desktop_control_socket
    if not path:
        raise HTTPException(503, "Automatic updates require the installed desktop app")
    try:
        return request(path, value)
    except OSError:
        raise HTTPException(503, "The native desktop updater is not available") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/capabilities")
def capabilities():
    if not get_settings().desktop_control_socket:
        return {"installed": False, "apply_available": False}
    value = native({"action": "updates.capabilities"})
    return {**value, "apply_available": qualified(value)}


@router.post("")
def operate(body: UpdateOperation):
    if body.permissions != ["manage_station", "network_read"]:
        raise HTTPException(403, "Desktop updates require explicit station-management permission")
    value = {"action": "updates." + body.action, "run_id": str(body.run_id)}
    if body.request is not None:
        value["request"] = body.request
    try:
        value = command(value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not qualified(native({"action": "updates.capabilities"})):
        raise HTTPException(503, "Automatic updates are not qualified for this native installation")
    return native(value)
