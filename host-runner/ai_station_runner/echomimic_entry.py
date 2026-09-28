"""Executed by the configured EchoMimic Python, not the Runner environment.

Reuse its inference entry point with a pipeline subclass implementing the CPU
offload mode that infer_flash.py declares but does not apply. No external files
are patched; both upstream .to(device) calls become idempotent offload setup.
"""

import argparse
import importlib
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--output-path", required=True)
    options, arguments = parser.parse_known_args()
    sys.path.insert(0, options.runtime_dir)
    inference = importlib.import_module("infer_flash")
    base = inference.WanFunInpaintAudioPipeline

    class OffloadedPipeline(base):
        def to(self, *args, **kwargs):
            if not getattr(self, "_station_offloaded", False):
                self._station_offloaded = True
                self.enable_sequential_cpu_offload(gpu_id=0)
            return self

    inference.WanFunInpaintAudioPipeline = OffloadedPipeline
    sys.argv = [sys.argv[0], *arguments]
    inference.main()
    output = Path(options.output_path)
    image = Path(arguments[arguments.index("--image_path") + 1])
    directory = Path(arguments[arguments.index("--save_path") + 1])
    generated = directory / f"{image.name.split('.')[0]}_output.mp4"
    # Decode the actual container before publishing a successful artifact.
    from moviepy import VideoFileClip

    with VideoFileClip(str(generated)) as clip:
        if clip.duration <= 0 or clip.audio is None:
            raise ValueError("Expected a playable video with an audio track")
        clip.get_frame(0)
    if output.exists():
        raise FileExistsError(output)
    os.rename(generated, output)


if __name__ == "__main__":
    main()
