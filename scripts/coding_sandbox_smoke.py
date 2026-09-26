"""Opt-in native isolation probe. No AI inference, credentials or real repository edits."""

import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path

from ai_station_runner.coding_sandbox import validation_argv, write_policy


def main():
    if os.environ.get("AI_STATION_REAL_SANDBOX_TESTS") != "1":
        raise SystemExit("Set AI_STATION_REAL_SANDBOX_TESTS=1 to probe the installed native helper")
    with tempfile.TemporaryDirectory(prefix="ai-station-boundary-") as temporary, socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        root = Path(temporary)
        workspace = root / "workspace"
        common = root / "repository.git"
        workspace.mkdir()
        common.mkdir()
        outside = root / "outside"
        for path in (outside, workspace / ".git", common / "config"):
            path.write_text("fixture")
        policy = write_policy(root / "policy.json", workspace, common)
        code = """
import json, pathlib, socket, sys
workspace = pathlib.Path.cwd()
(workspace / "inside").write_text("ok")
result = {}
for name, path, mode in [
    ("outside_read", sys.argv[1], "r"),
    ("outside_write", sys.argv[1], "w"),
    ("git_file", str(workspace / ".git"), "w"),
    ("git_common", sys.argv[2], "w"),
    ("global_tmp", sys.argv[3], "w"),
]:
    try:
        with open(path, mode):
            pass
        result[name] = "allowed"
    except OSError:
        result[name] = "denied"
try:
    socket.create_connection(("127.0.0.1", int(sys.argv[4])), timeout=1).close()
    result["network"] = "allowed"
except OSError:
    result["network"] = "denied"
print(json.dumps(result))
"""
        result = subprocess.run(
            validation_argv(
                policy,
                [
                    "/usr/bin/python3",
                    "-c",
                    code,
                    str(outside),
                    str(common / "config"),
                    str(root / "tmp-probe"),
                    str(server.getsockname()[1]),
                ],
            ),
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
        checks = json.loads(result.stdout)
        assert len(checks) == 6 and all(value == "denied" for value in checks.values()), checks
        assert (workspace / "inside").read_text() == "ok"
        assert all(path.read_text() == "fixture" for path in (outside, workspace / ".git", common / "config"))
        print("PASS: workspace write; outside read/write, Git metadata writes, global tmp and network denied")


if __name__ == "__main__":
    main()
