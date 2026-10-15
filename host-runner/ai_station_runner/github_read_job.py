"""Fixed GitHub GET operations; no caller API paths, queries or gh commands."""

import json
import os
import shutil
import signal
import sys
import time
from datetime import UTC, datetime

from ai_station_runner.github_read import directory, load_request
from ai_station_runner.publication_job import command


def snapshot(repository, *, gh, env, cwd, deadline):
    # Fixed GET projections deliberately omit issue bodies, comments and secrets.
    operations = {
        "project": (
            f"repos/{repository}",
            '{name: .full_name, description: (.description // "")[0:500], url: .html_url, private: .private, default_branch: .default_branch, open_issues: .open_issues_count, updated_at: .updated_at}',
        ),
        "issues": (
            f"repos/{repository}/issues?state=open&per_page=30",
            "[.[] | select(.pull_request == null) | {number, title: .title[0:300], url: .html_url, state, updated_at, author: .user.login}]",
        ),
        "pull_requests": (
            f"repos/{repository}/pulls?state=open&per_page=30",
            "[.[] | {number, title: .title[0:300], url: .html_url, state, updated_at, draft, author: .user.login, base: .base.ref, head: .head.ref}]",
        ),
    }
    result = {}
    for name, (endpoint, projection) in operations.items():
        try:
            raw, _ = command(
                [gh, "api", "--hostname", "github.com", "--method", "GET", "--jq", projection, endpoint],
                env=env,
                cwd=cwd,
                deadline=deadline,
            )
        except RuntimeError as exc:
            raise RuntimeError("GitHub read failed; check the host gh login and repository access") from exc
        result[name] = json.loads(raw)
        print(json.dumps({"event": "github.read.completed", "section": name}), flush=True)
    if result["project"].get("name", "").lower() != repository.lower():
        raise ValueError("GitHub redirected to a different repository; update the connector first")
    return result


def execute(run_id):
    if os.getpid() != os.getpgrp():
        raise ValueError("GitHub reading requires an owned process group")
    body = load_request(run_id)
    gh = shutil.which("gh")
    if not gh:
        raise ValueError("GitHub CLI is unavailable")
    env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "XDG_CONFIG_HOME", "GH_CONFIG_DIR", "GH_TOKEN", "GITHUB_TOKEN")
        if key in os.environ
    }
    env.update(
        GH_HOST="github.com",
        GH_PROMPT_DISABLED="1",
        GH_PAGER="cat",
        GH_EDITOR="/bin/false",
        GH_DEBUG="",
        CI="1",
    )
    result = snapshot(body.repository, gh=gh, env=env, cwd=directory(run_id), deadline=time.monotonic() + 60)
    value = {
        "run_id": run_id,
        "repository": body.repository,
        "captured_at": datetime.now(UTC).isoformat(),
        "bounded": True,
        "untrusted": True,
        **result,
    }
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded.encode()) > 256000:
        raise ValueError("GitHub snapshot exceeds its limit")
    with (directory(run_id) / "report.json").open("x") as handle:
        os.chmod(handle.name, 0o600)
        handle.write(encoded)


if __name__ == "__main__":
    try:
        execute(sys.argv[1])
    except Exception:
        # Upstream stderr, credentials and response bodies never enter Run logs.
        print(
            "GitHub snapshot failed; inspect host gh login and repository access", file=sys.stderr, flush=True
        )
        if os.getpid() == os.getpgrp():
            os.killpg(os.getpid(), signal.SIGTERM)
        raise SystemExit(1)
