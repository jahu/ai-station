"""Finite renderer recipe and read-only inspection; no caller-selected images."""

import hashlib
import json
import re
import shutil
from pathlib import Path

from ai_station_runner.motion_docker import connection, docker

RESOURCE = Path(__file__).parent / "recipes/hyperframes"
FILES = (
    "motion_assets.py",
    "motion_codec.py",
    "motion_container.py",
    "motion_contract.py",
    "motion_document.py",
    "motion_qc.mjs",
    "media_inputs.py",
)
RECIPES = ("Dockerfile", "package.json", "package-lock.json")
ENTRYPOINT = ["python", "-m", "ai_station_runner.motion_container"]
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")


def recipe():
    values = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in FILES}
    values.update({name: hashlib.sha256((RESOURCE / name).read_bytes()).hexdigest() for name in RECIPES})
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_context(destination):
    destination.mkdir(mode=0o700)
    (destination / "code").mkdir(mode=0o700)
    for name in RECIPES:
        shutil.copyfile(RESOURCE / name, destination / name)
    for name in FILES:
        shutil.copyfile(Path(__file__).with_name(name), destination / "code" / name)
    return recipe()


def image(settings):
    configured = getattr(settings, "motion_image", "")
    if not configured:
        path = settings.host_data_dir().resolve() / "runtime/motion/selection.json"
        if path.resolve() != path or not path.is_file() or path.stat().st_size > 64000:
            raise ValueError("Prepare the isolated Hyperframes renderer in Studio")
        selected = json.loads(path.read_text())
        if (
            not isinstance(selected, dict)
            or selected.get("protocol") != 1
            or selected.get("recipe_sha256") != recipe()
        ):
            raise ValueError("The prepared motion renderer changed")
        configured = selected.get("image_id", "")
    if not isinstance(configured, str) or not (
        re.fullmatch(r"ai-station-motion:[A-Za-z0-9_.-]+", configured) or IMAGE_ID.fullmatch(configured)
    ):
        raise ValueError("Configure the fixed AI Station motion renderer")
    bound = connection()
    raw = docker(["image", "inspect", configured, "--format", "{{json .}}"], bound=bound, missing_ok=True)
    value = json.loads(raw) if raw else {}
    if not isinstance(value, dict):
        raise ValueError("The motion image record is invalid")
    config = value.get("Config") or {}
    labels = config.get("Labels") or {}
    if (
        not IMAGE_ID.fullmatch(value.get("Id", ""))
        or config.get("Entrypoint") != ENTRYPOINT
        or config.get("Cmd") not in (None, [])
        or config.get("User") != "1000:1000"
        or labels.get("ai-station.motion.protocol") != "1"
        or labels.get("ai-station.motion.recipe") != recipe()
    ):
        raise ValueError("Prepare the pinned isolated Hyperframes renderer in Studio")
    return {
        "image_id": value["Id"],
        "recipe_sha256": labels["ai-station.motion.recipe"],
        "protocol": 1,
        "connection": bound,
    }
