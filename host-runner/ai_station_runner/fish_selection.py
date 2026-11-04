"""Preserve explicit Fish/ASR configurations before qualified shared fallback."""

from pathlib import Path

from ai_station_runner import fish_environment

FIELDS = ("fish_speech_python", "fish_speech_dir", "fish_speech_models")
ASR_FIELDS = ("transcription_python", "transcription_model_dir")


def explicit(settings, names):
    return {
        **{k: Path(getattr(settings, k)).expanduser() if getattr(settings, k, "") else None for k in names},
        "managed": False,
    }


def managed(settings, identity):
    from ai_station_runner.fish_prepare import QUALIFIED

    if not QUALIFIED:
        return None
    try:
        root = settings.host_data_dir().resolve()
        if identity is not None:
            return fish_environment.resolve_id(root, identity)
        observed = fish_environment.read_json(root / "runtime/fish-environments/active.json")
        return fish_environment.resolve(root, observed)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def selection(settings, identity=None):
    if getattr(settings, "fish_speech_enabled", False) or any(getattr(settings, k, "") for k in FIELDS):
        return explicit(settings, FIELDS)
    return managed(settings, identity)


def transcription_selection(settings, identity=None):
    if any(getattr(settings, k, "") for k in ASR_FIELDS):
        return explicit(settings, ASR_FIELDS)
    return managed(settings, identity)
