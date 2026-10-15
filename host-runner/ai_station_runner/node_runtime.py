"""Configured Node distribution, granted only as read-only runtime files."""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ai_station_runner.config import get_settings
from ai_station_runner.gitops import GitError


@dataclass(frozen=True)
class NodeRuntime:
    node: Path
    npm: Path

    @property
    def read_paths(self):
        crypto_config = [Path("/etc/ssl/openssl.cnf"), Path("/etc/pki/tls/openssl.cnf")]
        return [str(self.node), str(self.npm.parent.parent)] + [
            str(path.resolve()) for path in crypto_config if path.is_file()
        ]

    def environment(self, env):
        # The native sandbox blocks UDP sockets. Keep the host's configured DNS
        # resolver, using TCP inside this owned process instead of changing it.
        return {**env, "PATH": str(self.node.parent) + os.pathsep + env["PATH"], "RES_OPTIONS": "use-vc"}

    def argv(self, operation, workspace, scratch):
        if operation != "ci":
            raise GitError("Unsupported managed npm operation")
        return [
            str(self.node),
            str(self.npm),
            "ci",
            "--ignore-scripts=true",
            "--no-audit",
            "--no-fund",
            "--update-notifier=false",
            "--registry=https://registry.npmjs.org",
            "--include=dev",
            "--include=optional",
            "--prefix=" + str(workspace),
            "--cache=" + str(scratch / "npm-cache"),
            "--userconfig=" + str(scratch / "user.npmrc"),
            "--globalconfig=" + str(scratch / "global.npmrc"),
        ]

    def describe(self, env):
        result = subprocess.run(
            [str(self.node), "--version"],
            cwd=env["HOME"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        version = result.stdout.strip()
        if not re.fullmatch(r"v\d+\.\d+\.\d+", version) or int(version.split(".")[0][1:]) < 22:
            raise GitError("Managed Node projects require an installed Node 22 or newer runtime")
        path = self.npm.parent.parent / "package.json"
        if path.stat().st_size > 64000:
            raise GitError("Invalid npm runtime metadata")
        metadata = json.loads(path.read_text())
        npm_version = metadata.get("version")
        if (
            metadata.get("name") != "npm"
            or not isinstance(npm_version, str)
            or not re.fullmatch(r"\d+\.\d+\.\d+", npm_version)
        ):
            raise GitError("Configured npm runtime metadata is invalid")
        return {"node_version": version, "npm_version": npm_version}


def node_runtime(workspace: Path, *, prefix=None):
    prefix = get_settings().node_prefix if prefix is None else prefix
    if prefix:
        root = Path(prefix).expanduser().resolve(strict=True)
        node, npm = root / "bin/node", root / "lib/node_modules/npm/bin/npm-cli.js"
    else:
        binary, cli = shutil.which("node"), shutil.which("npm")
        if not binary or not cli:
            raise GitError(
                "Node/npm is unavailable. Configure AI_STATION_NODE_PREFIX with an installed Node distribution."
            )
        node, npm = Path(binary), Path(cli)
    try:
        node, npm = node.resolve(strict=True), npm.resolve(strict=True)
    except OSError as exc:
        raise GitError("Configured Node/npm runtime is unavailable") from exc
    if (
        not node.is_file()
        or not os.access(node, os.X_OK)
        or not npm.is_file()
        or npm.name != "npm-cli.js"
        or node.is_relative_to(workspace.resolve())
        or npm.is_relative_to(workspace.resolve())
    ):
        raise GitError("Node/npm must use an existing runtime outside the writable worktree")
    return NodeRuntime(node=node, npm=npm)


def runtime_policy(policy, runtime):
    paths = policy["sandbox"]["hardcodedReadPaths"]
    policy["sandbox"]["hardcodedReadPaths"] = list(dict.fromkeys([*paths, *runtime.read_paths]))
    return policy
