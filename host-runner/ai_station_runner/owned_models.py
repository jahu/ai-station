"""Read-only inspection of a fixed app-owned verified-model namespace."""

import re

from fastapi import HTTPException

from ai_station_runner.config import get_settings

SHA = re.compile(r"[a-f0-9]{64}\Z")


def owned_model(relative, digest):
    return verify_owned_model(get_settings().host_data_dir(), relative, digest)


def owned_safetensors(relative, digest):
    return verify_owned_model(
        get_settings().host_data_dir(), relative, digest, checkpoint_format="safetensors"
    )


def owned_tensor_zip(relative, digest):
    return verify_owned_model(
        get_settings().host_data_dir(), relative, digest, checkpoint_format="pytorch_zip_tensor_data"
    )


def verify_owned_model(root, relative, digest, *, checkpoint_format="gguf"):
    """The same immutable-model boundary for an explicitly owned native data root."""
    from ai_station_runner.owned_model_files import verify_owned_model as inspect_file

    try:
        return inspect_file(root, relative, digest, checkpoint_format=checkpoint_format)
    except (OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


def validate_reference(path, digest, app_owned):
    if app_owned:
        if not isinstance(digest, str) or not SHA.fullmatch(digest) or path != "models/store/" + digest:
            raise ValueError("Choose a verified app-owned model reference")
    elif digest is not None:
        raise ValueError("A model checksum requires an explicit app-owned source")
