import json

import pytest
from ai_station_runner.coding_sandbox import validation_policy
from ai_station_runner.config import Settings
from ai_station_runner.diagnostics import _node
from ai_station_runner.gitops import GitError
from ai_station_runner.node_runtime import node_runtime, runtime_policy


def runtime(tmp_path):
    root = tmp_path / "runtime"
    (root / "bin").mkdir(parents=True)
    npm = root / "lib/node_modules/npm"
    (npm / "bin").mkdir(parents=True)
    (npm / "bin/npm-cli.js").write_text("// fixture")
    (npm / "package.json").write_text(json.dumps({"name": "npm", "version": "10.9.8"}))
    (root / "bin/node").write_text("#!/bin/sh\necho v22.0.0\n")
    (root / "bin/node").chmod(0o700)
    return root


def test_runtime_is_read_only_and_install_argv_never_inherits_user_config(tmp_path):
    prefix = runtime(tmp_path)
    worktree = tmp_path / "workspace"
    worktree.mkdir()
    common = tmp_path / "git"
    common.mkdir()
    node = node_runtime(worktree, prefix=str(prefix))
    policy = runtime_policy(validation_policy(worktree, common), node)
    assert not policy["sandbox"]["networkAccess"]
    assert policy["sandbox"]["additionalReadwritePaths"] == []
    assert str(node.node) in policy["sandbox"]["hardcodedReadPaths"]
    assert str(tmp_path) not in policy["sandbox"]["hardcodedReadPaths"]
    assert node.environment({"PATH": "/usr/bin"})["RES_OPTIONS"] == "use-vc"
    scratch = worktree / "scratch"
    scratch.mkdir()
    argv = node.argv("ci", worktree, scratch)
    assert argv[:3] == [str(node.node), str(node.npm), "ci"]
    assert "--ignore-scripts=true" in argv and "--registry=https://registry.npmjs.org" in argv
    assert "--userconfig=" + str(scratch / "user.npmrc") in argv
    with pytest.raises(GitError):
        node.argv("install", worktree, scratch)


def test_runtime_cannot_be_replaced_from_the_writable_worktree(tmp_path):
    prefix = runtime(tmp_path)
    with pytest.raises(GitError):
        node_runtime(tmp_path, prefix=str(prefix))


def test_runtime_diagnostics_distinguish_missing_misconfigured_and_available(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert _node(Settings(data_dir=tmp_path, node_prefix=""))["status"] == "unavailable"
    assert (
        _node(Settings(data_dir=tmp_path, node_prefix=str(tmp_path / "absent")))["status"] == "misconfigured"
    )
    prefix = runtime(tmp_path)
    result = _node(Settings(data_dir=tmp_path / "data", node_prefix=str(prefix)))
    assert result["status"] == "available" and "v22.0.0" in result["detail"]
