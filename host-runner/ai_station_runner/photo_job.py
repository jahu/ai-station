"""Fixed prompt/instruction-only profiles around the trusted, unchanged photo pipeline."""

import importlib.util
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 3 or sys.argv[2] not in {"t2i", "img2img", "recompose"}:
        raise ValueError("Unsupported photo prompt profile mode")
    mode = sys.argv[2]
    pipeline = Path(sys.argv[1])
    spec = importlib.util.spec_from_file_location("ai_station_photo_pipeline", pipeline)
    if spec is None or spec.loader is None:
        raise ValueError("The configured photo pipeline cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.argv = [str(pipeline), *sys.argv[2:]]
    sys.path.insert(0, str(pipeline.parent))
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    names = {
        "t2i": ("PHOTO_SUFFIX", "T2I_NEGATIVE"),
        "img2img": ("IDENTITY_PREFIX",),
        "recompose": ("PHOTO_SUFFIX", "RECOMPOSE_PREFIX_SINGLE", "RECOMPOSE_PREFIX_MULTI"),
    }[mode]
    if not callable(getattr(module, "main", None)) or not all(
        isinstance(getattr(module, name, None), str) for name in names
    ):
        raise ValueError("The configured pipeline does not support the requested prompt profile")
    # Only this owned import changes. The external script and its legacy profile stay intact.
    for name in names:
        setattr(module, name, "")
    print("photo.profile: " + ("prompt-only" if mode == "t2i" else "instruction-only"), flush=True)
    module.main()


if __name__ == "__main__":
    main()
