"""Typed image operations; no caller-defined image, command or filesystem roots."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from ai_station_runner import managed_image_job as jobs

router = APIRouter(tags=["managed images"])


class Cancel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    permissions: list[Literal["filesystem_read", "workspace_write"]] = Field(max_length=2)


@router.post("/v1/runs/managed-image")
def start(body: jobs.Start):
    return jobs.start(body)


@router.get("/v1/images/jobs/{identity}")
def inspect(identity: UUID, stdout_offset: int = Query(0, ge=0), stderr_offset: int = Query(0, ge=0)):
    return jobs.inspect(identity, stdout_offset=stdout_offset, stderr_offset=stderr_offset)


@router.post("/v1/images/jobs/{identity}/cancel")
def cancel(identity: UUID, body: Cancel):
    return jobs.cancel(identity, permissions=body.permissions)
