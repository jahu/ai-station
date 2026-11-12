"""Fixed prompt/instruction-only profiles around the trusted, unchanged photo pipeline."""

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


def main():
    model = None
    profile = None
    options = {}
    while len(sys.argv) > 1 and sys.argv[1].startswith("--station-"):
        key = sys.argv[1]
        if (
            key not in {"--station-model-json", "--station-profile", "--station-sd-cli", "--station-seed"}
            or key in options
            or len(sys.argv) < 3
        ):
            raise ValueError("Invalid selected photo configuration arguments")
        options[key] = sys.argv[2]
        sys.argv = [sys.argv[0], *sys.argv[3:]]
    seed = None
    if "--station-seed" in options:
        raw = options["--station-seed"]
        try:
            seed = int(raw)
        except ValueError:
            raise ValueError("Invalid Qwen seed") from None
        if str(seed) != raw or not 0 <= seed <= 4294967295:
            raise ValueError("Invalid Qwen seed")
    if "--station-model-json" in options:
        model = verified_model(json.loads(options["--station-model-json"]))
        if "--station-profile" not in options:
            raise ValueError("Selected checkpoint needs a prompt profile")
    if "--station-profile" in options:
        profile = options["--station-profile"]
        if profile not in {"pipeline", "prompt", "instruction"}:
            raise ValueError("Unknown selected photo checkpoint profile")
    runtime = None
    if "--station-sd-cli" in options:
        value = options["--station-sd-cli"]
        if not value or value.startswith("-") or "\x00" in value:
            raise ValueError("Configured sd-cli must be executable")
        runtime = Path(value).expanduser().resolve(strict=True)
        if not runtime.is_file() or not os.access(runtime, os.X_OK):
            raise ValueError("Configured sd-cli must be executable")
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
    if runtime:
        if not isinstance(getattr(module, "SDCLI", None), Path):
            raise ValueError("Configured photo pipeline cannot select its sd-cli")
        module.SDCLI = runtime
        print("photo.runtime: configured sd-cli", flush=True)
    if seed is not None:
        import subprocess

        def seeded_run(command, *args, **kwargs):
            # Only this imported pipeline gets the fixed seed. Never patch the
            # global subprocess module or accept a caller-selected executable.
            if (
                not isinstance(command, list)
                or not command
                or not isinstance(getattr(module, "SDCLI", None), Path)
                or command[0] != str(module.SDCLI)
                or kwargs.get("shell")
            ):
                raise ValueError("Qwen seed requires the configured sd-cli argv")
            print(f"photo.seed: {seed}", flush=True)
            return subprocess.run([*command, "--seed", str(seed)], *args, **kwargs)

        module.subprocess = SimpleNamespace(run=seeded_run)
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
