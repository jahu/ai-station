"""Fixed portrait conditioning recipes; no executable or caller-selected hooks."""

import hashlib
import json
import re
from pathlib import Path

PROFILE = "portrait_anchor_v1"


def checked_recipe(value):
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or set(value) != {"id", "observation"}
        or value["id"] != PROFILE
        or not isinstance(value["observation"], str)
        or re.fullmatch("[0-9a-f]{64}", value["observation"]) is None
    ):
        raise ValueError("Invalid fixed avatar appearance recipe")
    return dict(value)


def current_recipe(runtime, models):
    from ai_station_runner.echo_motion import profile_key

    # Legacy model/checkpoint identities remain unchanged. Only the new recipe
    # binds implementation and upstream conditioning source as well as weights.
    paths = [
        Path(__file__),
        Path(__file__).with_name("echomimic_entry.py"),
        Path(runtime) / "infer_flash.py",
        Path(runtime) / "src/utils.py",
        Path(runtime) / "src/pipeline_wan_fun_inpaint_audio_2512.py",
    ]
    observed = {
        "version": 1,
        "id": PROFILE,
        "model_observation": profile_key(runtime, models),
        "source_hashes": [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths],
    }
    return {
        "id": PROFILE,
        "observation": hashlib.sha256(json.dumps(observed, sort_keys=True).encode()).hexdigest(),
    }


def motion_profile(runtime, models, recipe=None):
    from ai_station_runner.echo_motion import profile_key

    if recipe is None:
        return profile_key(runtime, models)
    recipe = checked_recipe(recipe)
    if recipe != current_recipe(runtime, models):
        raise ValueError("Avatar appearance implementation or model observation changed; start a new job")
    return recipe["observation"]


def anchored_conditioning(original, start, end, *args, **kwargs):
    if start is None or end is not None:
        raise ValueError("Portrait anchoring requires the original portrait and no supplied end image")
    return original(start, start, *args, **kwargs)
