"""Freeze an ordinary image Run for the fixed, locally prepared Qwen runtime."""

import io
import secrets

from PIL import Image

from app.image_prompt_presets import (
    IDENTITY_PREFIX,
    PHOTO_SUFFIX,
    RECOMPOSE_PREFIX_MULTI,
    RECOMPOSE_PREFIX_SINGLE,
)
from app.models import Artifact
from app.python_execution import read_owned_file
from app.vision_inputs import snapshot, verify


def freeze(session, run, capabilities):
    report = capabilities.get("managed_image") or {}
    if capabilities.get("available") is not True or not report.get("manifest_sha256"):
        raise ValueError("Prepare a qualified local image runtime in Models before generating")
    parameters = run.parameters
    saved = parameters.get("managed_image_runtime")
    if parameters.get("backend") != "qwen" or parameters.get("mode") == "upscale":
        raise ValueError("This managed image profile supports Qwen Generate, Edit and Recompose")
    selected = (parameters.get("image_model") or {}).get("model_file")
    if selected and (selected.get("sha256"), selected.get("size")) != (
        report.get("diffusion_sha256"),
        report.get("diffusion_size_bytes"),
    ):
        raise ValueError("The selected checkpoint is different from the prepared image profile")
    references = []
    dimensions = None
    for identity in parameters.get("parent_artifact_ids", []):
        artifact = session.get(Artifact, identity)
        if artifact is None:
            raise ValueError("A selected image reference is unavailable")
        item = snapshot(artifact)
        verify(session, [item], read_bytes=True)
        if dimensions is None:
            data = read_owned_file(
                artifact.relative_path, artifact.size_bytes, artifact.sha256, limit=20 * 1024**2, binary=True
            )
            with Image.open(io.BytesIO(data)) as image:
                dimensions = image.size
        references.append({key: item[key] for key in ("relative_path", "size_bytes", "sha256")})
    if [item["relative_path"] for item in references] != parameters.get("inputs", []):
        raise ValueError("Selected image references differ from their saved artifact identities")
    mode = parameters["mode"]
    if (
        mode == "t2i"
        and references
        or mode == "img2img"
        and len(references) != 1
        or mode == "recompose"
        and not references
    ):
        raise ValueError("Image references do not match the requested operation")
    prompt = parameters["edit_prompt"] if mode == "img2img" else parameters["prompt"]
    if parameters.get("prompt_style", "pipeline") == "pipeline":
        if mode == "t2i":
            prompt = f"{prompt.strip()}, {PHOTO_SUFFIX}"
        elif mode == "img2img":
            prompt = f"{IDENTITY_PREFIX} {prompt.strip()}"
        else:
            prefix = RECOMPOSE_PREFIX_SINGLE if len(references) == 1 else RECOMPOSE_PREFIX_MULTI
            prompt = f"{prefix} {prompt.strip()}, {PHOTO_SUFFIX}"
    width, height = parameters.get("width"), parameters.get("height")
    if mode == "img2img":
        scale = min(1, (parameters.get("max_side") or 1216) / max(dimensions))
        width, height = (max(32, round(value * scale / 32) * 32) for value in dimensions)
    if not width or not height or not (256 <= width <= 2048 and 256 <= height <= 2048):
        raise ValueError("Managed image output dimensions must be between 256 and 2048 pixels per side")
    if len(prompt) > 10000:
        raise ValueError("The effective image prompt exceeds the runtime's 10,000 character limit")
    command = {
        "mode": mode,
        "prompt": prompt,
        "reference_count": len(references),
        "width": width,
        "height": height,
        "steps": parameters["steps"],
        "cfg": float(parameters.get("cfg") if parameters.get("cfg") is not None else 6),
        "seed": parameters.get("seed")
        if parameters.get("seed") is not None
        else saved["command"]["seed"]
        if saved
        else secrets.randbits(32),
    }
    runtime = {
        **report,
        "command": command,
        "references": references,
    }
    if saved is not None and saved != runtime:
        raise ValueError("The saved managed image runtime or its effective inputs changed")
    return {**parameters, "managed_image_runtime": runtime}


def verify_references(session, run):
    frozen = run.parameters["managed_image_runtime"]["references"]
    identities = run.parameters.get("parent_artifact_ids", [])
    if len(identities) != len(frozen):
        raise ValueError("Managed image reference identities changed")
    for identity, expected in zip(identities, frozen, strict=True):
        artifact = session.get(Artifact, identity)
        if artifact is None:
            raise ValueError("Managed image reference is unavailable")
        item = snapshot(artifact)
        if any(item[key] != expected[key] for key in ("relative_path", "size_bytes", "sha256")):
            raise ValueError("Managed image reference changed after admission")
        verify(session, [item], read_bytes=True)
