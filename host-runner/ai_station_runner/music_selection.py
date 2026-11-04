"""Explicit music settings retain priority over an adopted owned environment."""

from pathlib import Path

from ai_station_runner import music_environment


def selection(settings):
    values = [settings.music_python, settings.music_source_dir, settings.music_model_dir]
    if any(values):
        return dict(
            python=Path(values[0]).expanduser() if values[0] else None,
            source=Path(values[1]).expanduser() if values[1] else None,
            models=Path(values[2]).expanduser() if values[2] else None,
            managed=False,
        )
    from ai_station_runner.music_prepare import QUALIFIED

    if not QUALIFIED:
        return None
    try:
        root = settings.host_data_dir().resolve()
        active = music_environment.read_json(root / "runtime/music-environments/active.json")
        return music_environment.resolve(root, active)
    except (OSError, ValueError, KeyError, TypeError):
        return None
