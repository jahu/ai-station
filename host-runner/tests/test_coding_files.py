import json

import pytest
from ai_station_runner.coding_files import apply_proposal, parse_proposal, read_selected


def test_checked_replacements_preserve_unchanged_files_and_executable_mode(tmp_path):
    old = tmp_path / "app.py"
    old.write_text("print(1)\n")
    old.chmod(0o755)
    selected = read_selected(tmp_path, ["app.py", "new.py"])
    proposal = parse_proposal(
        json.dumps(
            {
                "summary": "Fix",
                "files": [{"path": "app.py", "content": "print(2)\n"}, {"path": "new.py", "content": "new"}],
            }
        ),
        selected,
    )
    report = apply_proposal(tmp_path, selected, proposal)
    assert old.read_text() == "print(2)\n"
    assert old.stat().st_mode & 0o777 == 0o755
    assert len(report["files"]) == 2 and report["review_status"] == "needs_review"
    assert "No newline at end of file" in report["files"][1]["diff"]
    assert report["files"][0]["insertions"] == report["files"][0]["deletions"] == 1


@pytest.mark.parametrize(
    "path",
    ["../outside", "/etc/passwd", ".git/config", "src/../app.py", "src/.env", "credentials.json", "ssh.key"],
)
def test_rejects_unselected_paths_and_sensitive_locations(tmp_path, path):
    with pytest.raises(ValueError):
        read_selected(tmp_path, [path])
    selected = read_selected(tmp_path, ["safe.py"])
    with pytest.raises(ValueError):
        parse_proposal(json.dumps({"summary": "No", "files": [{"path": path, "content": "bad"}]}), selected)


def test_symlinks_hardlinks_binary_oversize_and_stale_content_fail_before_writes(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("outside")
    (workspace / "link").symlink_to(outside)
    with pytest.raises(ValueError):
        read_selected(workspace, ["link"])
    (workspace / "hard").hardlink_to(outside)
    with pytest.raises(ValueError):
        read_selected(workspace, ["hard"])
    (workspace / "binary").write_bytes(b"\0")
    with pytest.raises(ValueError):
        read_selected(workspace, ["binary"])
    (workspace / "huge").write_bytes(b"x" * 32001)
    with pytest.raises(ValueError):
        read_selected(workspace, ["huge"])
    selected = read_selected(workspace, ["new.py", "other.py"])
    proposal = parse_proposal(
        json.dumps(
            {
                "summary": "change",
                "files": [{"path": "new.py", "content": "new"}, {"path": "other.py", "content": "replace"}],
            }
        ),
        selected,
    )
    (workspace / "other.py").write_text("human edit")
    with pytest.raises(ValueError, match="changed"):
        apply_proposal(workspace, selected, proposal)
    assert not (workspace / "new.py").exists()
    assert (workspace / "other.py").read_text() == "human edit"
    assert outside.read_text() == "outside"


def test_review_patch_can_be_applied_by_git_including_new_empty_files(tmp_path):
    import subprocess

    workspace, target = tmp_path / "workspace", tmp_path / "target"
    workspace.mkdir()
    target.mkdir()
    for root in (workspace, target):
        (root / "file with spaces.py").write_text("old\n")
    selected = read_selected(workspace, ["file with spaces.py", "empty.py", "new.py"])
    proposal = parse_proposal(
        json.dumps(
            {
                "summary": "Replace",
                "files": [
                    {"path": "file with spaces.py", "content": "new\n"},
                    {"path": "empty.py", "content": ""},
                    {"path": "new.py", "content": "no newline"},
                ],
            }
        ),
        selected,
    )
    report = apply_proposal(workspace, selected, proposal)
    patch = "".join(item["diff"] for item in report["files"])
    subprocess.run(["git", "init", str(target)], check=True, capture_output=True)
    result = subprocess.run(
        ["git", "-C", str(target), "apply", "--"], input=patch, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    for item in proposal["files"]:
        assert (target / item["path"]).read_text() == item["content"]
