"""Explicit Sonic settings take priority over one qualified managed fallback."""

from pathlib import Path

from ai_station_runner import avatar_environment

FIELDS = ("sonic_python", "sonic_dir", "sonic_models")


def selection(settings, identity=None):
    if settings.sonic_whole_enabled or any(getattr(settings, k) for k in FIELDS):
        return {
            **{k: Path(getattr(settings, k)).expanduser() if getattr(settings, k) else None for k in FIELDS},
            "managed": False,
        }
    from ai_station_runner.avatar_prepare import QUALIFIED

    if not QUALIFIED:
        return None
    try:
        root = settings.host_data_dir().resolve()
        if identity is not None:
            return avatar_environment.resolve_id(root, identity)
        observed = avatar_environment.read_json(root / "runtime/avatar-environments/active.json")
        return avatar_environment.resolve(root, observed)
    except (OSError, ValueError, KeyError, TypeError):
        return None
