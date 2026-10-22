"""Environment-driven settings. No machine-specific paths are hard-coded."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_runner_socket() -> str:
    uid = os.getuid()
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    return str(Path(runtime) / "ai-station" / "runner.sock")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_STATION_",
        env_file=".env",
        extra="ignore",
    )

    data_dir: Path = Field(default=Path("./data"))
    data_host_path: Path | None = None
    database_url: str = ""
    runner_socket: str = Field(default_factory=default_runner_socket)
    bind_host: str = "127.0.0.1"
    lan_host: str = ""
    access_origins: str = ""
    port: int = 8765
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_transport: Literal["direct", "runner"] = "direct"
    llm_host_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    web_search_url: str = ""
    browser_enabled: bool = False
    site_preview_enabled: bool = False
    photo_python: str = ""
    photo_script: str = ""
    sd_cli: str = ""
    model_roots: str = ""
    allowed_roots: str = ""
    lease_seconds: int = 45
    heartbeat_seconds: int = 5
    worker_slots: int = Field(default=3, ge=1, le=8)
    cancel_grace_seconds: float = 3.0
    frontend_dist: str = ""
    skills_dir: str = ""
    log_level: str = "INFO"
    enable_test_executor: bool = False

    def sqlite_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'db' / 'ai-station.sqlite'}"

    def split_paths(self, raw: str) -> list[Path]:
        parts = [part.strip() for part in raw.split(":") if part.strip()]
        return [Path(part).expanduser() for part in parts]

    def model_root_paths(self) -> list[Path]:
        return self.split_paths(self.model_roots)

    def allowed_root_paths(self) -> list[Path]:
        roots = self.split_paths(self.allowed_roots)
        roots.append(self.data_dir)
        if self.data_host_path:
            roots.append(self.data_host_path)
        return roots


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
