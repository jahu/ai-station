"""Dependency-light identity shared by the runner and isolated codec runtime."""

import hashlib
import json
from pathlib import Path

FILES = (
    "timeline_contract.py",
    "timeline_job.py",
    "timeline_runtime.py",
    "timeline_observation.py",
    "memory_scope.py",
    "media_compose_job.py",
    "security.py",
    "media_inputs.py",
)


def observation():
    return hashlib.sha256(
        json.dumps(
            {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in FILES},
            sort_keys=True,
        ).encode()
    ).hexdigest()
