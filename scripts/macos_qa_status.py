"""Bounded stage evidence survives loss of a disposable hosted Mac's job log."""

import json
import os
import re
import subprocess


class Status:
    def __init__(self, head):
        run = os.environ.get("GITHUB_RUN_ID", "")
        if (
            os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != "jahu/ai-station"
            or os.environ.get("GITHUB_ACTOR") != "jahu"
            or not os.environ.get("GH_TOKEN")
            or not re.fullmatch(r"[a-f0-9]{40}", head)
            or not re.fullmatch(r"[0-9]{1,24}", run)
        ):
            raise ValueError("Stage publication requires the explicit owner-dispatched QA job")
        self.head = head
        self.context = "qa/macos-consumer/" + run
        self.url = "https://github.com/jahu/ai-station/actions/runs/" + run
        self.environment = {key: os.environ[key] for key in ("HOME", "PATH", "GH_TOKEN") if key in os.environ}

    def post(self, state, description):
        if state not in {"pending", "success", "failure", "error"}:
            raise ValueError("Unknown stage status")
        payload = {
            "state": state,
            "context": self.context,
            "target_url": self.url,
            "description": description[:140],
        }
        result = subprocess.run(
            ["gh", "api", "--method", "POST", "repos/jahu/ai-station/statuses/" + self.head, "--input", "-"],
            input=json.dumps(payload).encode(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=self.environment,
            timeout=15,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Could not publish bounded Mac QA stage evidence")
