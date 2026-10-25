"""Fixed prompt/instruction-only profiles around the trusted, unchanged photo pipeline."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def main():
    model = None
    profile = None
    if len(sys.argv) > 1 and sys.argv[1] == "--station-model-json":
        if len(sys.argv) < 7 or sys.argv[3] != "--station-profile":
            raise ValueError("Invalid selected photo checkpoint arguments")
        model = verified_model(json.loads(sys.argv[2]))
        profile = sys.argv[4]
        if profile not in {"pipeline", "prompt", "instruction"}:
            raise ValueError("Unknown selected photo checkpoint profile")
        sys.argv = [sys.argv[0], *sys.argv[5:]]
    if len(sys.argv) < 3 or sys.argv[2] not in {"t2i", "img2img", "recompose"}:
        raise ValueError("Unsupported photo prompt profile mode")
    mode = sys.argv[2]
    if profile == "prompt" and mode != "t2i" or profile == "instruction" and mode == "t2i":
        raise ValueError("Selected photo checkpoint profile does not match the operation")
    pipeline = Path(sys.argv[1])
    spec = importlib.util.spec_from_file_location("ai_station_photo_pipeline", pipeline)
    if spec is None or spec.loader is None:
        raise ValueError("The configured photo pipeline cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.argv = [str(pipeline), *sys.argv[2:]]
    sys.path.insert(0, str(pipeline.parent))
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    names = (
        ()
        if profile == "pipeline"
        else {
            "t2i": ("PHOTO_SUFFIX", "T2I_NEGATIVE"),
            "img2img": ("IDENTITY_PREFIX",),
            "recompose": ("PHOTO_SUFFIX", "RECOMPOSE_PREFIX_SINGLE", "RECOMPOSE_PREFIX_MULTI"),
        }[mode]
    )
    if not callable(getattr(module, "main", None)) or not all(
        isinstance(getattr(module, name, None), str) for name in names
    ):
        raise ValueError("The configured pipeline does not support the requested prompt profile")
    # Only this owned import changes. The external script and its legacy profile stay intact.
    for name in names:
        setattr(module, name, "")
    if model:
        if not isinstance(getattr(module, "QWEN_DIFFUSION_CANDIDATES", None), list):
            raise ValueError("Configured pipeline cannot select a Qwen diffusion checkpoint")
        module.QWEN_DIFFUSION_CANDIDATES = [model]
        print("photo.model: selected verified checkpoint", flush=True)
    print(
        "photo.profile: " + (profile or ("prompt-only" if mode == "t2i" else "instruction-only")), flush=True
    )
    module.main()


def verified_model(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != {"path", "size", "sha256"}:
        raise ValueError("Invalid selected checkpoint snapshot")
    path = Path(snapshot["path"])
    if (
        path.resolve() != path
        or path.suffix != ".gguf"
        or not path.is_file()
        or path.stat().st_size != snapshot["size"]
    ):
        raise ValueError("Selected Qwen checkpoint is missing or changed")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != snapshot["sha256"]:
        raise ValueError("Selected Qwen checkpoint failed SHA-256 verification")
    return path


if __name__ == "__main__":
    main()
