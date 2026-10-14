"""Opt-in prompt-only profile around the trusted, unchanged photo pipeline."""

import importlib.util
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 3 or sys.argv[2] != "t2i":
        raise ValueError("Prompt-only styling supports text-to-image only")
    pipeline = Path(sys.argv[1])
    spec = importlib.util.spec_from_file_location("ai_station_photo_pipeline", pipeline)
    if spec is None or spec.loader is None:
        raise ValueError("The configured photo pipeline cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.argv = [str(pipeline), *sys.argv[2:]]
    sys.path.insert(0, str(pipeline.parent))
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "main", None)) or not all(
        isinstance(getattr(module, name, None), str) for name in ("PHOTO_SUFFIX", "T2I_NEGATIVE")
    ):
        raise ValueError("The configured pipeline does not support the prompt-only profile")
    # Change this owned process's imported module only, never the source file.
    module.PHOTO_SUFFIX = ""
    module.T2I_NEGATIVE = ""
    print("photo.profile: prompt-only", flush=True)
    module.main()


if __name__ == "__main__":
    main()
