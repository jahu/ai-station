"""Owned offline native llama.cpp SDK preparation; no model or package installation."""

import json
import platform
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID

from ai_station_runner import runtime_install
from ai_station_runner.darwin_llama_environment import Environment


def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise RuntimeError("Native SDK preparation requires isolated/no-bytecode Python")
    request = Path(sys.argv[1]).resolve(strict=True)
    body = runtime_install.load_json(request)
    identity = str(UUID(body["run_id"]))
    root = Path(body["data_root"]).resolve(strict=True)
    if request != root / "runtime/setup" / identity / "native_llama-request.json":
        raise ValueError("The native SDK request is outside its owned operation")
    environment = Environment(body["profile"])
    if platform.system() != "Darwin" or platform.machine() != environment.architecture:
        raise RuntimeError("Native SDK preparation requires its matching Mac platform")
    if body["manifest_sha256"] != environment.fingerprint(environment.recipe()):
        raise ValueError("The native SDK recipe changed")
    deadline = datetime.fromisoformat(body["deadline_at"])
    if deadline.tzinfo is None:
        raise ValueError("Native SDK preparation needs an absolute deadline")

    def check():
        if time.time() >= deadline.timestamp():
            raise TimeoutError("Native SDK preparation exceeded its deadline")
        current = runtime_install.load_json(request.with_name("native_llama.json"))
        if not current or current.get("cancellation_requested"):
            raise InterruptedError("Native SDK preparation was stopped")

    check()
    result = environment.prepare(
        root,
        identity,
        check=check,
        progress=lambda value: print(json.dumps({"native_llama_preparation": value}), flush=True),
    )
    check()
    print(json.dumps({"native_llama_environment_prepared": result}), flush=True)


if __name__ == "__main__":
    main()
