"""Fixed native preparation child; never downloads packages or reads user media."""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID

from ai_station_runner import music_environment, runtime_install
from ai_station_runner.memory_scope import require_scope


def main():
    request = Path(sys.argv[1]).resolve(strict=True)
    body = runtime_install.load_json(request)
    identity = str(UUID(body["run_id"]))
    root = Path(body["data_root"]).resolve(strict=True)
    if request != root / "runtime/setup" / identity / "music-request.json":
        raise ValueError("The native music preparation request is outside its owned operation")
    if body["profile"] != music_environment.PROFILE or body[
        "manifest_sha256"
    ] != music_environment.fingerprint(music_environment.recipe()):
        raise ValueError("The native music preparation recipe changed")
    deadline = datetime.fromisoformat(body["deadline_at"])
    if deadline.tzinfo is None:
        raise ValueError("Music preparation requires an absolute deadline")
    require_scope(identity, 4096)

    def check():
        if time.time() >= deadline.timestamp():
            raise TimeoutError("Music preparation exceeded its execution deadline")
        current = runtime_install.load_json(request.with_name("music.json"))
        if not current or current.get("cancellation_requested"):
            raise InterruptedError("Music preparation was stopped")

    check()
    result = music_environment.prepare(
        root,
        identity,
        check=check,
        progress=lambda value: print(json.dumps({"music_preparation": value}), flush=True),
    )
    check()
    print(json.dumps({"music_environment_prepared": result}), flush=True)


if __name__ == "__main__":
    main()
