"""Run only the configured speech CLI and publish complete compatible PCM parts."""

import json
import os
import subprocess
import sys
import wave
from contextlib import ExitStack
from pathlib import Path


def generate(config_path: Path) -> None:
    config = json.loads(config_path.read_text())
    work = config_path.parent.resolve()
    output = Path(config["output"])
    if output.exists() or output.is_symlink() or output.resolve() != output:
        raise ValueError("Inspect the existing speech output")
    parts = config["chunks"]
    if not 2 <= len(parts) <= 20 or any(not part or len(part) > 220 for part in parts):
        raise ValueError("Invalid bounded speech chunks")
    temporary = work / "complete.wav"
    total = 0
    expected = None
    # All children inherit the manager-owned group and offline environment.
    # A failed/canceled child never produces a partially published artifact.
    with temporary.open("xb") as raw, ExitStack() as opened:
        for index, text in enumerate(parts):
            path = work / f"part-{index:02d}.wav"
            if path.exists() or path.is_symlink():
                raise ValueError("Inspect existing speech parts")
            print(f"speech.chunk.started {index + 1}/{len(parts)}", flush=True)
            subprocess.run(
                [
                    sys.executable,
                    config["script"],
                    "--ref",
                    config["reference"],
                    "--text",
                    text,
                    "--out",
                    str(path),
                ],
                check=True,
            )
            if path.is_symlink() or path.stat().st_size > 20 * 1024**2:
                raise ValueError("Invalid speech part file")
            with wave.open(str(path), "rb") as part:
                channels, width, rate = part.getnchannels(), part.getsampwidth(), part.getframerate()
                frames = part.getnframes()
                if (
                    channels not in (1, 2)
                    or width not in (1, 2, 3, 4)
                    or not 8000 <= rate <= 96000
                    or not 0.1 <= frames / rate < 30
                    or part.getcomptype() != "NONE"
                ):
                    raise ValueError("Invalid or token-limit-length speech part")
                dimensions = (channels, width, rate)
                if expected is None:
                    expected = dimensions
                    complete = opened.enter_context(wave.open(raw, "wb"))
                    complete.setnchannels(channels)
                    complete.setsampwidth(width)
                    complete.setframerate(rate)
                elif dimensions != expected:
                    raise ValueError("Speech parts have incompatible PCM formats")
                samples = part.readframes(frames)
                if len(samples) != frames * channels * width:
                    raise ValueError("Truncated speech part")
                total += frames
                if total / rate > 300 or total * channels * width > 20 * 1024**2:
                    raise ValueError("Combined speech exceeds its output budget")
                complete.writeframes(samples)
            print(f"speech.chunk.completed {index + 1}/{len(parts)}", flush=True)
    # A hard link publishes the complete file without overwriting an existing path.
    os.link(temporary, output)
    temporary.unlink()
    print(f"speech.completed parts={len(parts)} samples={total}", flush=True)


if __name__ == "__main__":
    generate(Path(sys.argv[1]))
