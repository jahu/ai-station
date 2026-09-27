"""Opt-in real Cursor task against AI Station, preserving its active checkout.

Uses the running localhost application and leaves its project, worktree and Runs
available for review. This consumes external Cursor inference only with explicit
AI_STATION_REAL_CURSOR_TESTS=1. It never commits, merges or deploys the proposal.
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
TARGET = "docs/self-development-example.md"
CONTENT = (
    "# AI Station self-development example\n\n"
    "Changes are prepared in an owned task worktree.\n"
    "Review the diff and validation results before integration.\n"
    "The running checkout is preserved; deployment is a separate action.\n"
)


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def snapshot():
    index = Path(git("rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip())
    return {
        "head": git("rev-parse", "HEAD").decode().strip(),
        "status": git("status", "--porcelain=v1", "-z").decode(),
        "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if os.environ.get("AI_STATION_REAL_CURSOR_TESTS") != "1":
        parser.error("Set AI_STATION_REAL_CURSOR_TESTS=1 to explicitly enable external Cursor inference")
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        parser.error("Use the trusted localhost AI Station base URL")
    before = snapshot()
    target_before = (ROOT / TARGET).read_bytes() if (ROOT / TARGET).exists() else None
    with httpx.Client(base_url=args.url.rstrip("/") + "/api", trust_env=False, timeout=30) as client:

        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        def completed(run_id):
            deadline = time.monotonic() + 360
            while time.monotonic() < deadline:
                run = request("GET", f"/runs/{run_id}")
                if run["status"] in {"succeeded", "failed", "canceled", "interrupted"}:
                    assert run["status"] == "succeeded", (run_id, run["status"], run["error_message"])
                    return run
                time.sleep(0.5)
            raise RuntimeError(f"Run {run_id} needs inspection; it was not automatically retried")

        existing = [p for p in request("GET", "/projects?limit=500") if p["repo_path"] == str(ROOT)]
        if existing:
            project = existing[0]
            if not project["test_commands"]:
                raise RuntimeError("Configure saved validation on the existing AI Station project first")
        else:
            project = request(
                "POST",
                "/projects",
                json={
                    "name": "AI Station",
                    "repo_path": str(ROOT),
                    "default_branch": "main",
                    "integration_branch": "develop",
                    "preferred_executor": "cursor",
                    "agent_rules": (ROOT / "AGENTS.md").read_text(),
                    "test_commands": [
                        ["/usr/bin/python3", "-m", "compileall", "-q", "backend/app"],
                        ["/usr/bin/python3", "-m", "compileall", "-q", "host-runner/ai_station_runner"],
                    ],
                },
            )
        preparation = request(
            "POST",
            "/coding/cursor",
            json={
                "project_id": project["id"],
                "expected_updated_at": project["updated_at"],
                "prompt": "Create the selected Markdown file by decoding this JSON string as its exact contents, including the final newline; do not change anything else: "
                + json.dumps(CONTENT),
                "files": [TARGET],
                "external_ai": True,
            },
        )
        print("Queued real self-development task:", preparation["id"], flush=True)
        prepared = completed(preparation["id"])
        coded = completed(prepared["metadata"]["coding_run_id"])
        validation = completed(coded["metadata"]["validation_run_id"])
        assert coded["metadata"]["review_status"] == "needs_review"
        assert [f["path"] for f in coded["metadata"]["coding_review"]["files"]] == [TARGET]
        assert (
            coded["metadata"]["coding_review"]["files"][0]["after_sha256"]
            == hashlib.sha256(CONTENT.encode()).hexdigest()
        )
        artifacts = request("GET", f"/artifacts?run_id={coded['id']}")
        assert {a["type"] for a in artifacts} == {"json", "git_diff"}
        assert snapshot() == before, "Active checkout or Git index changed"
        assert ((ROOT / TARGET).read_bytes() if (ROOT / TARGET).exists() else None) == target_before
        print(
            json.dumps(
                {
                    "project_id": project["id"],
                    "preparation_run": prepared["id"],
                    "coding_run": coded["id"],
                    "validation_run": validation["id"],
                    "original_checkout": before,
                },
                indent=2,
            )
        )
        print(
            "PASS: real AI Station worktree edit, review artifacts, document/syntax validation and unchanged active checkout"
        )
        print(
            "Full backend/frontend suites are separate release checks; this task validates a documentation-only proposal."
        )


if __name__ == "__main__":
    main()
