"""One offline speech Run may replace only its fixed T3 checkpoint coordinate."""

import signal
import sys
import time
from pathlib import Path
from uuid import UUID

from ai_station_runner import speech_environment
from ai_station_runner.environment_files import read_json
from ai_station_runner.speech_checkpoints import FILENAME, selected_environment
from ai_station_runner.speech_runtime_schema import SpeechCheckpointJob


def deadline_at(value):
    remaining = value - time.time()
    if remaining <= 0:
        raise TimeoutError("The selected speech execution deadline expired")

    def expired(signum, frame):
        raise TimeoutError("The selected speech execution deadline expired")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, remaining)


def selected_models(config_path, run_id, environment):
    path = Path(config_path)
    identity = str(UUID(str(run_id)))
    if len(path.parents) < 4 or path.resolve(strict=True) != path:
        raise ValueError("Selected speech requires its exact owned Run configuration")
    root = path.parents[3]
    if path != root / "runs" / identity / "speech/checkpoint.json":
        raise ValueError("Selected speech configuration belongs to another Run")
    job = SpeechCheckpointJob.model_validate(read_json(path))
    if str(job.run_id) != identity:
        raise ValueError("Selected speech configuration changed its Run identity")
    deadline_at(job.deadline_at)
    selected = selected_environment(
        root, job.checkpoint, job.managed_runtime.model_dump(mode="json"), verify_weights=True
    )
    if (
        Path(environment).resolve(strict=True) != selected["environment"]
        or Path(sys.base_prefix).resolve() != selected["environment"] / "python"
    ):
        raise ValueError("The speech child requires its original prepared Python environment")
    models = path.parent / "models"
    if models.exists() or models.is_symlink():
        raise ValueError("Inspect the existing selected speech model view instead of restarting it")
    models.mkdir(mode=0o700)
    for item in speech_environment.recipe()["inputs"]:
        if item["kind"] == "model":
            target = (
                selected["checkpoint_path"]
                if item["filename"] == FILENAME
                else (selected["models"] / item["filename"]).resolve(strict=True)
            )
            (models / item["filename"]).symlink_to(target)
    return models
