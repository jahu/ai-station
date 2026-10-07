# Reviewed GitHub publication

After validating and committing a coding proposal, open the **commit Run** and choose **Publish reviewed changes**. Enable task-branch push and integration PRs in Project → Git workflow policy first. The form shows the GitHub repository, exact commit, task branch and integration target; enter a PR title/description and explicitly approve publication. This creates a normal host Run and a durable approval record, then pushes the task ref and opens a **draft PR**. The result links to GitHub and includes a JSON artifact. Nothing is merged or deployed.

The native Host Runner uses the existing `gh` login. Supported origins are `https://github.com/owner/repo[.git]` and `git@github.com:owner/repo[.git]`, normalized to HTTPS for publication. Embedded credentials, other hosts, local remotes and production/protected bases are rejected. The source must be a successful AI Station reviewed commit, still at its owned worktree HEAD. Its parent must match the current remote integration head; refresh the task if it does not. Only the reviewed commit is published, including its Git tree; unrelated uncommitted workspace files are excluded.

Network Git uses an isolated bare directory and fixed credential helper; it does not execute repository hooks, custom helpers or URL rewrites. No credentials are copied to application storage. Host commands share a managed process group and a five-minute network deadline with a 1 MiB output limit per command. Cancellation signals only that group.

A stopped/failed Run can follow a successful push or even a successful PR request whose reply was lost. Inspect the persisted last stage and GitHub before further action. Duplicate publication requests for the same commit are blocked, and recovery never blindly repeats network effects. This slice does not reconcile ambiguous remote outcomes automatically or update existing PRs.

Validation uses fake Git/GitHub network commands with real disposable Git objects/worktrees. It covers exact approval, project/protected-branch policy, origin restrictions, config isolation, private error output, partial push/PR failures, idempotent dispatch, cancellation and stale-worker recovery. A real GitHub acceptance test also passed on 2026-10-07: fake local inference created one documentation file in a disposable clone, the actual Host Runner published its reviewed commit, and GitHub confirmed a draft PR to develop with that exact one-file diff. The test then closed the draft and deleted only its verified task branch. No model inference or merge was performed.


To repeat against a repository you own, explicitly opt in and provide the local source checkout, matching GitHub owner/repository and evidence path. Its local develop must match the remote develop head. The test creates and closes a disposable draft PR and deletes its exact task ref after verification; failures preserve evidence/resources for inspection.

```bash
AI_STATION_REAL_GITHUB_TESTS=1 \
AI_STATION_GITHUB_SMOKE_SOURCE=/absolute/path/to/checkout \
AI_STATION_GITHUB_SMOKE_REPOSITORY=owner/repository \
AI_STATION_GITHUB_SMOKE_EVIDENCE=/absolute/path/to/report.json \
.venv/bin/python -m pytest -q backend/tests/test_projects.py::test_real_github_publication
```
