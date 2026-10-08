# Codex coding proposals

The Codex adapter follows the existing fresh worktree → selected-file proposal → checked replacements → saved validation → diff review → approved commit/publication workflow. It uses the host CLI's existing authentication, without reading or copying credentials. External-AI consent is explicit and resets when the user switches coding providers.

Codex runs in a separate empty workspace with a restricted read-only permission profile and no command, browser, app, plugin, hook, child-agent or image tools. Host skill discovery and implicit project guidance are disabled; only the task, saved project guidance and selected snapshots form the task data. A completed text proposal is parsed through the same file-size, path, symlink and source-hash checks as Cursor. Any reported tool action invalidates the result. Only the Runner applies accepted replacements to its owned task worktree. Structured usage/thread metadata, general artifacts, cancellation and conservative recovery follow existing contracts. Raw provider stderr is not persisted.

The integration requires CLI support for isolated configuration (`--ignore-user-config`, `--ignore-rules`), strict configuration, ephemeral execution and named filesystem permission profiles. The installed 0.160.1 CLI was probed against a local fake Responses endpoint with an empty auth directory; no external inference occurred. Missing/incompatible CLI behavior fails before proposal application. See the official [non-interactive CLI contract](https://learn.chatgpt.com/docs/non-interactive-mode) and [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

Real external acceptance passed with the installed CLI: two synthetic selected files were proposed, checked and applied in a disposable worktree; actual native sandbox validation passed and the reviewed commit succeeded. The original checkout and index were unchanged. No private repository files, push or PR were involved. Ordinary tests cover failure, rejected tool actions, explicit provider-bound consent and owned-group cancellation without cloud calls.

Open **Coding → Codex**, or choose **Coding with Codex** in the central Assistant. Select the project and files and approve sending that scope. The coding workspace also permits a model override; an empty value uses the CLI default. Validation still requires the existing native sandbox helper described in [coding boundaries](coding-boundary.md).

Repeat the synthetic external acceptance only with explicit opt-in:

```bash
AI_STATION_REAL_CODEX_TESTS=1 AI_STATION_REAL_SANDBOX_TESTS=1 \
AI_STATION_CODEX_SMOKE_EVIDENCE=/absolute/path/to/report.json \
.venv/bin/python -m pytest -q backend/tests/test_projects.py::test_real_codex_selected_file_proposal
```

