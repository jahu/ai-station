import pytest
from ai_station_runner.app import app
from ai_station_runner.security import PathBoundaryError, ensure_within, resolve_child
from fastapi.testclient import TestClient


def test_canonical_boundaries(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside)
    for value in ["../outside/file", "/etc/passwd", "escape/file", "\x00"]:
        with pytest.raises(PathBoundaryError):
            resolve_child(root, value)
    with pytest.raises(PathBoundaryError):
        ensure_within(outside, [root])
    assert resolve_child(root, "good/file") == root / "good/file"


def test_unfinished_mutations_are_not_exposed():
    with TestClient(app) as client:
        for path in [
            "/shell",
            "/v1/project/command",
            "/v1/git/worktree/remove",
            "/v1/git/pr",
            "/v1/fs/write",
            "/v1/runs/coding",
        ]:
            assert client.post(path, json={}).status_code == 404
        assert client.post("/v1/process/cancel", json={"run_id": "../escape"}).status_code == 422
        assert client.get("/health").status_code == 200
