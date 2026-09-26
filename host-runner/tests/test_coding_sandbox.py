import json
import os

import pytest
from ai_station_runner.coding_sandbox import (
    SandboxUnavailable,
    validation_argv,
    validation_policy,
    write_policy,
)


def test_validation_policy_keeps_git_readonly_and_denies_network_and_global_tmp(tmp_path):
    workspace = tmp_path / "workspace"
    common = tmp_path / "repository.git"
    workspace.mkdir()
    common.mkdir()
    policy = validation_policy(workspace, common)
    sandbox = policy["sandbox"]
    assert sandbox["cwd"] == str(workspace)
    assert not sandbox["networkAccess"] and sandbox["disableTmpWrite"]
    assert not sandbox["additionalReadwritePaths"]
    assert ".git/**" in sandbox["additionalReadonlyPaths"][str(workspace)]
    assert str(common) in sandbox["hardcodedReadPaths"]
    assert str(tmp_path) not in sandbox["hardcodedReadPaths"]
    target = write_policy(tmp_path / "policies/job.json", workspace, common)
    assert json.loads(target.read_text()) == policy
    assert os.stat(target).st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_policy(target, workspace, common)
    with pytest.raises(SandboxUnavailable):
        write_policy(workspace / "policy.json", workspace, common)


def test_missing_helper_fails_closed_and_arguments_remain_separate(monkeypatch, tmp_path):
    monkeypatch.setattr("ai_station_runner.coding_sandbox.shutil.which", lambda name: None)
    with pytest.raises(SandboxUnavailable):
        validation_argv(tmp_path / "policy.json", ["pytest", "-q"])
    helper = tmp_path / "cursorsandbox"
    monkeypatch.setattr("ai_station_runner.coding_sandbox.cursor_sandbox_binary", lambda: helper)
    argv = validation_argv(tmp_path / "policy.json", ["pytest", "file with spaces.py"])
    assert argv[-3:] == ["--", "pytest", "file with spaces.py"]
    assert "--preflight-only" in validation_argv(tmp_path / "policy.json", ["true"], preflight=True)
    with pytest.raises(ValueError):
        validation_argv(tmp_path / "policy.json", [])


def test_policy_rejects_symlink_redirection(tmp_path):
    workspace = tmp_path / "workspace"
    common = tmp_path / "common"
    target = tmp_path / "target"
    for path in (workspace, common, target):
        path.mkdir()
    (tmp_path / "link").symlink_to(target, target_is_directory=True)
    with pytest.raises(SandboxUnavailable):
        write_policy(tmp_path / "link/policy.json", workspace, common)
    assert not (target / "policy.json").exists()
