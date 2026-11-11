"""Opaque, immutable renderer identity; no host SDK or implicit installation."""

import hashlib
import json
from pathlib import Path

from ai_station_runner.motion_image import recipe

CODE = (
    "motion_runtime.py",
    "motion_job.py",
    "motion_owner.py",
    "motion_docker.py",
    "motion_image.py",
    "motion_installation.py",
    "memory_scope.py",
    "security.py",
)


def observation(installed):
    files = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in CODE}
    return hashlib.sha256(
        json.dumps(
            {
                "files": files,
                "recipe": recipe(),
                "image": installed["image_id"],
                "connection": installed["connection"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
