"""Fixed native preparation child; never downloads packages or reads user media."""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID

from ai_station_runner import fish_environment, runtime_install
from ai_station_runner.memory_scope import require_scope


def main():
    request = Path(sys.argv[1]).resolve(strict=True)
    body = runtime_install.load_json(request)
    identity = str(UUID(body["run_id"]))
    root = Path(body["data_root"]).resolve(strict=True)
    if request != root / "runtime/setup" / identity / "fish-request.json":
        raise ValueError("The native fish preparation request is outside its owned operation")
    if body["profile"] != fish_environment.PROFILE or body["manifest_sha256"] != fish_environment.fingerprint(
        fish_environment.recipe()
    ):
        raise ValueError("The native fish preparation recipe changed")
    deadline = datetime.fromisoformat(body["deadline_at"])
    if deadline.tzinfo is None:
        raise ValueError("Fish preparation requires an absolute deadline")
    require_scope(identity, 4096)

    def check():
        if time.time() >= deadline.timestamp():
            raise TimeoutError("Fish preparation exceeded its execution deadline")
        current = runtime_install.load_json(request.with_name("fish.json"))
        if not current or current.get("cancellation_requested"):
            raise InterruptedError("Fish preparation was stopped")

    check()
    result = fish_environment.prepare(
        root,
        identity,
        check=check,
        progress=lambda value: print(json.dumps({"fish_preparation": value}), flush=True),
    )
    check()
    print(json.dumps({"fish_environment_prepared": result}), flush=True)


if __name__ == "__main__":
    main()
