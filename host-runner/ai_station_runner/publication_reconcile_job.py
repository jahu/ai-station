"""Read GitHub after uncertain publication. Create a missing draft PR; never push."""

import json
import os
import re
import shlex
import shutil
import signal
import sys
import time

from ai_station_runner.gitops import GitError
from ai_station_runner.publication import directory as publication_directory
from ai_station_runner.publication import load_request
from ai_station_runner.publication_job import command
from ai_station_runner.publication_reconcile import directory, load_reconcile


def execute(run_id: str) -> None:
    if os.getpid() != os.getpgrp():
        raise ValueError("Publication reconcile requires an owned process group")
    body = load_reconcile(run_id)
    publication, committed = load_request(str(body.publication_run_id))
    if str(publication.project_id) != str(body.project_id):
        raise GitError("Publication ownership changed")
    branch = committed["branch"]
    local_report = publication_directory(str(body.publication_run_id)) / "report.json"
    if local_report.is_file() and local_report.stat().st_size <= 32000:
        existing = json.loads(local_report.read_text())
        pr_url = str(existing.get("pr_url", ""))
        if existing.get("stage") == "succeeded" and re.fullmatch(
            r"https://github\.com/" + re.escape(publication.repository) + r"/pull/[1-9][0-9]*",
            pr_url,
        ):
            report = {
                "run_id": run_id,
                "publication_run_id": str(body.publication_run_id),
                "project_id": str(publication.project_id),
                "repository": publication.repository,
                "branch": branch,
                "commit": publication.commit,
                "base": publication.base,
                "pushed": True,
                "pr_url": pr_url,
                "outcome": "recorded_local_report",
            }
            path = directory(run_id) / "report.json"
            with path.open("x") as handle:
                os.chmod(path, 0o600)
                json.dump(report, handle)
            print("Publication reconcile: recorded_local_report", flush=True)
            return
    root = directory(run_id)
    git, gh = shutil.which("git"), shutil.which("gh")
    if not git or not gh:
        raise ValueError("Git and GitHub CLI must be installed")
    env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "XDG_CONFIG_HOME", "GH_CONFIG_DIR", "GH_TOKEN", "GITHUB_TOKEN")
        if key in os.environ
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_TERMINAL_PROMPT="0",
        GIT_ALLOW_PROTOCOL="https",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GH_HOST="github.com",
        GH_PROMPT_DISABLED="1",
        GH_PAGER="cat",
        GH_EDITOR="/bin/false",
        CI="1",
    )
    deadline = time.monotonic() + 300
    export = root / "export.git"
    command(
        [
            git,
            "init",
            "--bare",
            "--template=",
            "--initial-branch=ai/export",
            str(export),
        ],
        env=env,
        cwd=root,
        deadline=deadline,
    )
    env.update(GIT_DIR=str(export))
    options = [
        git,
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "gc.auto=0",
        "-c",
        "credential.helper=",
        "-c",
        f"credential.helper=!{shlex.quote(gh)} auth git-credential",
        "-c",
        "credential.useHttpPath=true",
    ]
    url = f"https://github.com/{publication.repository}.git"
    ref = f"refs/heads/{branch}"
    remote, code = command(
        [*options, "ls-remote", "--exit-code", url, ref],
        env=env,
        cwd=root,
        deadline=deadline,
        allowed=(0, 2),
    )
    report = {
        "run_id": run_id,
        "publication_run_id": str(body.publication_run_id),
        "project_id": str(publication.project_id),
        "repository": publication.repository,
        "branch": branch,
        "commit": publication.commit,
        "base": publication.base,
        "pushed": False,
        "pr_url": None,
        "outcome": "not_on_github",
    }
    if code == 0 and remote.strip():
        if remote.strip().split() != [publication.commit, ref]:
            raise ValueError("Remote task branch has a different commit; inspect GitHub")
        report["pushed"] = True
        listed, _ = command(
            [
                gh,
                "pr",
                "list",
                "--repo",
                publication.repository,
                "--head",
                branch,
                "--base",
                publication.base,
                "--state",
                "all",
                "--json",
                "url,number,isDraft,headRefName,baseRefName,state",
            ],
            env=env,
            cwd=root,
            deadline=deadline,
        )
        matches = [
            item
            for item in json.loads(listed or "[]")
            if item.get("headRefName") == branch and item.get("baseRefName") == publication.base
        ]
        if len(matches) > 1:
            raise ValueError("Multiple pull requests exist for this task branch; inspect GitHub")
        if matches:
            pr_url = str(matches[0].get("url", ""))
            report["outcome"] = "recorded_existing_pr"
        else:
            description = root / "pr-body.md"
            description.write_text(publication.body)
            description.chmod(0o600)
            created, _ = command(
                [
                    gh,
                    "pr",
                    "create",
                    "--repo",
                    publication.repository,
                    "--base",
                    publication.base,
                    "--head",
                    branch,
                    "--title",
                    publication.title,
                    "--body-file",
                    str(description),
                    "--draft",
                    "--no-maintainer-edit",
                ],
                env=env,
                cwd=root,
                deadline=deadline,
            )
            pr_url = created.strip()
            report["outcome"] = "created_draft_pr"
        if not re.fullmatch(
            r"https://github\.com/" + re.escape(publication.repository) + r"/pull/[1-9][0-9]*",
            pr_url,
        ):
            raise ValueError("GitHub returned an unexpected PR URL; inspect the repository")
        report["pr_url"] = pr_url
    path = root / "report.json"
    with path.open("x") as handle:
        os.chmod(path, 0o600)
        json.dump(report, handle)
    print(f"Publication reconcile: {report['outcome']}", flush=True)


if __name__ == "__main__":
    try:
        execute(sys.argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        if os.getpgrp() == os.getpid():
            os.killpg(os.getpid(), signal.SIGTERM)
        raise SystemExit(1) from error
