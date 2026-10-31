"""Explicit MMAudio settings take priority over one qualified managed fallback."""

from pathlib import Path

from ai_station_runner import effects_environment

FIELDS = ("mmaudio_python", "mmaudio_dir", "mmaudio_models")


def selection(settings, identity=None):
    if settings.mmaudio_enabled or any(getattr(settings, k, "") for k in FIELDS):
        return {
            **{
                k: Path(getattr(settings, k)).expanduser() if getattr(settings, k, "") else None
                for k in FIELDS
            },
            "managed": False,
        }
    from ai_station_runner.effects_prepare import QUALIFIED

    if not QUALIFIED:
        return None
    try:
        root = settings.host_data_dir().resolve()
        if identity is not None:
            return effects_environment.resolve_id(root, identity)
        observed = effects_environment.read_json(root / "runtime/effects-environments/active.json")
        return effects_environment.resolve(root, observed)
    except (OSError, ValueError, KeyError, TypeError):
        return None
