"""Host-side settings. Prefers the host data path when both are present."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def default_socket() -> str:
    uid = os.getuid()
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    return str(Path(runtime) / "ai-station" / "runner.sock")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AI_STATION_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    data_host_path: Path | None = None
    runner_socket: str = ""
    photo_python: str = ""
    photo_script: str = ""
    krea_runtime_dir: str = ""
    krea_companions_dir: str = ""
    krea_enabled: bool = False
    sd_cli: str = ""
    transcription_python: str = ""
    transcription_model_dir: str = ""
    chatterbox_python: str = ""
    chatterbox_script: str = ""
    chatterbox_cache: str = ""
    fish_speech_enabled: bool = False
    fish_speech_python: str = ""
    fish_speech_dir: str = ""
    fish_speech_models: str = ""
    music_python: str = ""
    music_source_dir: str = ""
    music_model_dir: str = ""
    echomimic_python: str = ""
    echomimic_dir: str = ""
    echomimic_models: str = ""
    echo_bounded_profile: bool = False
    sonic_python: str = ""
    sonic_dir: str = ""
    sonic_models: str = ""
    sonic_whole_enabled: bool = False
    video_python: str = ""
    comfy_dir: str = ""
    wan_model: str = ""
    wan_text_encoder: str = ""
    wan_vae: str = ""
    wan_bounded_profile: bool = False
    browser_image: str = ""
    site_preview_image: str = ""
    python_image: str = ""
    llama_image: str = "ghcr.io/ggml-org/llama.cpp:server-cuda"
    model_roots: str = ""
    allowed_roots: str = ""
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = ""
    web_search_url: str = ""
    cancel_grace_seconds: float = 3.0
    tailnet_binary_dir: str = ""
    tailnet_private_dir: str = ""
    port: int = 8765
    runner_id: str = "local"
    node_prefix: str = ""

    def host_data_dir(self) -> Path:
        return (self.data_host_path or self.data_dir).expanduser()

    def socket_path(self) -> str:
        return self.runner_socket or default_socket()

    def roots(self) -> list[Path]:
        found = _split(self.allowed_roots) + _split(self.model_roots)
        found.append(self.host_data_dir())
        return found


def _split(raw: str) -> list[Path]:
    return [Path(part).expanduser() for part in raw.split(":") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
