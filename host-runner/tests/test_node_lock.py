import json
import time
from pathlib import Path

import pytest
from ai_station_runner.gitops import GitError
from ai_station_runner.node_lock import generate_lock, missing_package
from ai_station_runner.node_runtime import NodeRuntime


def missing(url="https://registry.npmjs.org/@scope%2fdemo"):
    return json.dumps(
        {"error": {"code": "ENOTCACHED", "summary": f"request to {url} failed: cache mode is only-if-cached"}}
    )


def test_offline_errors_only_identify_public_registry_package_names():
    assert missing_package(missing()) == "@scope/demo"
    for url in [
        "https://127.0.0.1/private",
        "https://registry.npmjs.org/demo?token=x",
        "https://registry.npmjs.org/demo/-/a.tgz",
        "https://registry.npmjs.org/%2e%2e/private",
    ]:
        with pytest.raises(GitError):
            missing_package(missing(url))
    for output in ["not JSON", "[]", json.dumps({"error": {"code": "ERESOLVE"}})]:
        with pytest.raises(GitError):
            missing_package(output)


@pytest.mark.parametrize("repeat", [False, True])
def test_resolution_and_cache_writer_never_receive_network_and_cannot_loop(tmp_path, monkeypatch, repeat):
    from ai_station_runner import node_lock

    workspace, common, policy = (tmp_path / name for name in ["worktree", "git", "policies"])
    for path in [workspace, common, policy]:
        path.mkdir()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    runtime = NodeRuntime(runtime_root / "node", runtime_root / "npm/bin/npm-cli.js")
    scratch = workspace / "scratch"
    scratch.mkdir()
    (workspace / "package.json").write_text(json.dumps({"name": "fixture", "version": "1.0.0"}))
    monkeypatch.setattr(node_lock, "validation_argv", lambda path, argv: [str(path), *argv])
    fetched = []
    monkeypatch.setattr(
        node_lock,
        "fetch_metadata",
        lambda name, **kwargs: (fetched.append(name) or {"name": name}, {"name": name}),
    )
    calls = []

    def execute(argv, cwd, env, *, deadline, capture):
        assert capture and cwd == workspace and deadline > time.monotonic()
        config = json.loads(Path(argv[0]).read_text())
        assert config["sandbox"]["networkAccess"] is False
        assert config["sandbox"]["additionalReadwritePaths"] == []
        calls.append(argv[1:])
        if "-e" in argv:
            assert fetched == ["@scope/demo"]
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        assert "--offline" in argv and "--package-lock-only" in argv and "--ignore-scripts=true" in argv
        assert "ci" not in argv
        if len(calls) == 1 or repeat:
            return {"exit_code": 1, "stdout": missing(), "stderr": "expected cache miss"}
        staging = scratch / "lock-resolution"
        (staging / "package-lock.json").write_text(
            json.dumps({"lockfileVersion": 3, "packages": {"": {"name": "fixture", "version": "1.0.0"}}})
        )
        return {"exit_code": 0, "stdout": "{}", "stderr": ""}

    kwargs = dict(deadline=time.monotonic() + 5, policy_dir=policy)
    if repeat:
        with pytest.raises(GitError, match="cannot progress"):
            generate_lock(workspace, common, runtime, scratch, {}, execute, **kwargs)
    else:
        result = generate_lock(workspace, common, runtime, scratch, {}, execute, **kwargs)
        assert result["lock_generated"] and result["registry_metadata"] == [{"name": "@scope/demo"}]
    assert len(calls) == 3 and fetched == ["@scope/demo"]


@pytest.mark.parametrize("outcome", ["complete", "incomplete", "concurrent"])
def test_optional_packages_must_be_locked_and_existing_user_files_are_preserved(
    tmp_path, monkeypatch, outcome
):
    import base64

    from ai_station_runner import node_lock

    workspace, common, policies = (tmp_path / name for name in ["worktree", "git", "policies"])
    for path in [workspace, common, policies]:
        path.mkdir()
    scratch = workspace / "scratch"
    scratch.mkdir()
    manifest = {"name": "fixture", "version": "1.0.0", "optionalDependencies": {"native": "1.0.0"}}
    (workspace / "package.json").write_text(json.dumps(manifest))
    runtime = NodeRuntime(tmp_path / "node", tmp_path / "npm/bin/npm-cli.js")
    monkeypatch.setattr(node_lock, "validation_argv", lambda path, argv: [str(path), *argv])
    monkeypatch.setattr(node_lock, "fetch_metadata", lambda name, **kwargs: ({"name": name}, {"name": name}))
    attempts = []

    def execute(argv, cwd, env, **kwargs):
        if "-e" in argv:
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        entries = {"": manifest}
        if attempts and outcome != "incomplete":
            entries["node_modules/native"] = {
                "version": "1.0.0",
                "resolved": "https://registry.npmjs.org/native/-/native-1.0.0.tgz",
                "integrity": "sha512-" + base64.b64encode(b"x" * 64).decode(),
                "optional": True,
            }
        if attempts and outcome == "concurrent":
            (workspace / "package-lock.json").write_text("Important concurrently-created lock")
        (scratch / "lock-resolution/package-lock.json").write_text(
            json.dumps({"lockfileVersion": 3, "packages": entries})
        )
        attempts.append(1)
        return {"exit_code": 0, "stdout": "{}", "stderr": ""}

    kwargs = dict(deadline=time.monotonic() + 5, policy_dir=policies)
    if outcome == "incomplete":
        with pytest.raises(GitError, match="Optional npm dependencies"):
            generate_lock(workspace, common, runtime, scratch, {}, execute, **kwargs)
        assert not (workspace / "package-lock.json").exists()
    elif outcome == "concurrent":
        with pytest.raises(FileExistsError):
            generate_lock(workspace, common, runtime, scratch, {}, execute, **kwargs)
        assert (workspace / "package-lock.json").read_text() == "Important concurrently-created lock"
    else:
        result = generate_lock(workspace, common, runtime, scratch, {}, execute, **kwargs)
        assert result["registry_metadata"] == [{"name": "native"}]
        assert "node_modules/native" in json.loads((workspace / "package-lock.json").read_text())["packages"]
    assert len(attempts) == 2
