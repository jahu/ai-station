"""Managed Codex text proposal using the shared checked-write boundary."""

import sys

from ai_station_runner.codex_adapter import prepare_codex, proposal_result
from ai_station_runner.codex_runs import directory, load_request
from ai_station_runner.coding_job import execute_proposal
from ai_station_runner.cursor_job import collect_proposal


def execute(run_id):
    body = load_request(run_id)
    root = directory(run_id)

    counter = 0

    def complete(message=None, selected=None):
        nonlocal counter
        counter += 1
        argv, env, workspace = prepare_codex(
            root / f"provider-{counter}",
            prompt=body.prompt,
            selected=selected or [],
            guidance=body.guidance,
            model=body.model,
        )
        if message is not None:
            argv[-1] = message
        return collect_proposal(argv, env, workspace, parse=proposal_result, label="Codex", stderr=False)

    discover = None
    if body.explore:
        from ai_station_runner.coding_exploration import explore

        def discover(workspace):
            return explore(workspace, body.prompt, body.guidance, lambda message: complete(message)[0])

    execute_proposal(
        run_id,
        body,
        root,
        lambda selected: complete(selected=selected),
        location="external",
        discover=discover,
    )


if __name__ == "__main__":
    try:
        execute(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error
