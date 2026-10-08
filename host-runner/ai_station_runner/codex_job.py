"""Managed Codex text proposal using the shared checked-write boundary."""

import sys

from ai_station_runner.codex_adapter import prepare_codex, proposal_result
from ai_station_runner.codex_runs import directory, load_request
from ai_station_runner.coding_job import execute_proposal
from ai_station_runner.cursor_job import collect_proposal


def execute(run_id):
    body = load_request(run_id)
    root = directory(run_id)

    def generate(selected):
        argv, env, workspace = prepare_codex(
            root / "provider", prompt=body.prompt, selected=selected, guidance=body.guidance, model=body.model
        )
        return collect_proposal(argv, env, workspace, parse=proposal_result, label="Codex", stderr=False)

    execute_proposal(run_id, body, root, generate, location="external")


if __name__ == "__main__":
    try:
        execute(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
