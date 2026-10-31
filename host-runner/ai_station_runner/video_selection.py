"""Explicit/partial video configuration takes precedence over managed fallback."""

from pathlib import Path

from ai_station_runner import video_environment

FIELDS = ("video_python", "comfy_dir", "wan_model", "wan_text_encoder", "wan_vae")


def selection(settings, observation=None):
    if any(getattr(settings, key) for key in FIELDS):
        return {
            **{
                key: Path(getattr(settings, key)).expanduser() if getattr(settings, key) else None
                for key in FIELDS
            },
            "managed": False,
        }
    from ai_station_runner.video_prepare import QUALIFIED

    if not QUALIFIED:
        return None
    try:
        root = settings.host_data_dir().resolve()
        if observation is not None:
            return video_environment.resolve_public(root, observation)
        observed = video_environment.read_json(root / "runtime/video-environments/active.json")
        return video_environment.resolve(root, observed)
    except (OSError, ValueError, KeyError, TypeError):
        return None
