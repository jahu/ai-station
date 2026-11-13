"""Pure motion identity shared with the offline child; never imports API modules."""

import hashlib
import re
from pathlib import Path

from ai_station_runner import svi_environment
from ai_station_runner.speech_environment import fingerprint


def profile_identity(runtime, image_sha256):
    frozen = svi_environment.recipe()
    if (
        not isinstance(runtime, dict)
        or set(runtime) != {"profile", "manifest_sha256", "environment_id"}
        or runtime["profile"] != svi_environment.PROFILE
        or runtime["manifest_sha256"] != fingerprint(frozen)
        or not isinstance(runtime["environment_id"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", runtime["environment_id"])
        or not isinstance(image_sha256, str)
        or not re.fullmatch(r"[a-f0-9]{64}", image_sha256)
    ):
        raise ValueError("SVI motion requires its exact engine and original anchor identity")
    package = Path(__file__).parent
    implementation = {
        name: hashlib.sha256((package / name).read_bytes()).hexdigest()
        for name in (
            "svi_identity.py",
            "svi_environment.py",
            "video_environment.py",
            "wan_svi_context.py",
            "wan_svi_adapter.py",
            "svi_video_job.py",
        )
    }
    return fingerprint(
        {
            "engine": runtime,
            "implementation": implementation,
            "original_image_sha256": image_sha256,
            "recipe": "svi-pro-q4-832x480-81f-15fps-20-euler-shift5-cfg5-v1",
        }
    )
