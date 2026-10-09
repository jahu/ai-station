"""Explicit run state machine."""

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    PREPARING = "preparing"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"


TERMINAL = {
    RunStatus.SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELED,
    RunStatus.INTERRUPTED,
}

ACTIVE = {
    RunStatus.QUEUED,
    RunStatus.CLAIMED,
    RunStatus.PREPARING,
    RunStatus.RUNNING,
    RunStatus.WAITING_FOR_APPROVAL,
    RunStatus.CANCEL_REQUESTED,
}

# interrupted -> queued is only used by recovery for safe retries.
TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.QUEUED: {RunStatus.CLAIMED, RunStatus.CANCELED, RunStatus.WAITING_FOR_APPROVAL},
    RunStatus.CLAIMED: {
        RunStatus.PREPARING,
        RunStatus.FAILED,
        RunStatus.CANCEL_REQUESTED,
        RunStatus.INTERRUPTED,
    },
    RunStatus.PREPARING: {
        RunStatus.RUNNING,
        RunStatus.FAILED,
        RunStatus.CANCEL_REQUESTED,
        RunStatus.INTERRUPTED,
        RunStatus.WAITING_FOR_APPROVAL,
    },
    RunStatus.RUNNING: {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCEL_REQUESTED,
        RunStatus.WAITING_FOR_APPROVAL,
        RunStatus.INTERRUPTED,
    },
    RunStatus.WAITING_FOR_APPROVAL: {
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.PREPARING,
        RunStatus.CANCELED,
        RunStatus.FAILED,
    },
    RunStatus.CANCEL_REQUESTED: {RunStatus.CANCELED, RunStatus.FAILED, RunStatus.INTERRUPTED},
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELED: set(),
    RunStatus.INTERRUPTED: {RunStatus.QUEUED},
}


class InvalidTransition(Exception):
    def __init__(self, current: str, target: str):
        super().__init__(f"Invalid run transition: {current} -> {target}")
        self.current = current
        self.target = target


def assert_transition(current: str, target: str) -> None:
    try:
        src = RunStatus(current)
        dst = RunStatus(target)
    except ValueError as exc:
        raise InvalidTransition(current, target) from exc
    if dst not in TRANSITIONS[src]:
        raise InvalidTransition(current, target)
