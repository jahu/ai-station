"""Read-only model metadata from installed coding clients, never credentials."""

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

_cache = {}


def coding_models(provider):
    if provider not in {"cursor", "codex"}:
        raise ValueError("Unknown coding provider")
    if provider in _cache and time.monotonic() - _cache[provider][0] < 120:
        return _cache[provider][1]
    rows, notice = [], ""
    try:
        if provider == "codex":
            path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "models_cache.json"
            if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("Codex catalog is unavailable; Auto uses the CLI default")
            data = json.loads(path.read_text())
            rows = [
                {"id": item["slug"], "name": item.get("display_name") or item["slug"]}
                for item in data.get("models", [])
                if item.get("visibility") == "list"
                and re.fullmatch(r"[A-Za-z0-9._:/ -]{1,100}", item.get("slug", ""))
            ]
        else:
            binary = shutil.which("cursor-agent") or shutil.which("agent")
            if not binary:
                raise ValueError("Cursor is not installed")
            result = subprocess.run(
                [binary, "--list-models", "--disable-auto-update"],
                cwd="/tmp",
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
                env={
                    k: v
                    for k, v in os.environ.items()
                    if k in {"PATH", "HOME", "XDG_CONFIG_HOME", "CURSOR_API_KEY"}
                },
            )
            for line in result.stdout[:200000].splitlines():
                match = re.fullmatch(r"([A-Za-z0-9._:/ -]{1,100}) - (.{1,200})", line.strip())
                if match:
                    rows.append({"id": match[1].strip(), "name": match[2]})
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        notice = "Model list is currently unavailable. Auto uses the selected provider's default."
    result = {
        "models": rows[:250],
        "notice": notice,
        "source": "installed_cli" if provider == "cursor" else "cli_catalog_cache",
    }
    _cache[provider] = (time.monotonic(), result)
    return result
