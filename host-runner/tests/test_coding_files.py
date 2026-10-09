import json

import pytest
from ai_station_runner.coding_files import apply_proposal, parse_proposal, proposal_prompt, read_selected


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


def test_unique_snippet_replacements_apply_and_reject_ambiguous_matches(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("print(1)\nprint(1)\nhelper()\n")
    selected = read_selected(tmp_path, ["app.py", "new.py"])
    with pytest.raises(ValueError, match="exactly one unique snippet"):
        parse_proposal(
            json.dumps(
                {
                    "summary": "Ambiguous",
                    "files": [
                        {"path": "app.py", "replacements": [{"old": "print(1)\n", "new": "print(2)\n"}]}
                    ],
                }
            ),
            selected,
        )
    with pytest.raises(ValueError, match="existing selected file"):
        parse_proposal(
            json.dumps(
                {
                    "summary": "Create",
                    "files": [{"path": "new.py", "replacements": [{"old": "missing", "new": "no"}]}],
                }
            ),
            selected,
        )
    proposal = parse_proposal(
        json.dumps(
            {
                "summary": "Unique edits",
                "files": [
                    {
                        "path": "app.py",
                        "replacements": [
                            {"old": "print(1)\nprint(1)\n", "new": "print(2)\nprint(2)\n"},
                            {"old": "helper()", "new": "helper(1)"},
                        ],
                    },
                    {"path": "new.py", "content": "created\n"},
                ],
            }
        ),
        selected,
    )
    assert proposal["files"][0]["content"] == "print(2)\nprint(2)\nhelper(1)\n"
    report = apply_proposal(tmp_path, selected, proposal)
    assert source.read_text() == "print(2)\nprint(2)\nhelper(1)\n"
    assert (tmp_path / "new.py").read_text() == "created\n"
    assert {item["path"] for item in report["files"]} == {"app.py", "new.py"}
    assert "replacements" not in proposal["files"][0]


@pytest.mark.parametrize(
    "payload",
    [
        {"path": "app.py", "content": "x\n", "replacements": [{"old": "print(1)\n", "new": "x\n"}]},
        {"path": "app.py", "replacements": [{"old": "", "new": "x"}]},
        {"path": "app.py", "replacements": [{"old": "missing", "new": "x"}]},
        {"path": "app.py", "replacements": [{"old": "print(1)\n", "new": "x"}] * 21},
        {"path": "app.py", "delete": True},
    ],
)
def test_invalid_snippet_replacements_fail_closed(tmp_path, payload):
    (tmp_path / "app.py").write_text("print(1)\n")
    selected = read_selected(tmp_path, ["app.py"])
    with pytest.raises(ValueError):
        parse_proposal(json.dumps({"summary": "No", "files": [payload]}), selected)
    assert (tmp_path / "app.py").read_text() == "print(1)\n"


def test_snippet_expansion_respects_file_size_limit(tmp_path):
    (tmp_path / "app.py").write_text("token\n")
    selected = read_selected(tmp_path, ["app.py"])
    with pytest.raises(ValueError, match="bounded UTF-8"):
        parse_proposal(
            json.dumps(
                {
                    "summary": "Huge",
                    "files": [{"path": "app.py", "replacements": [{"old": "token", "new": "x" * 32001}]}],
                }
            ),
            selected,
        )


def test_proposal_prompt_includes_fetched_page_facts():
    selected = [{"path": "index.html", "content": "<h1>Invented</h1>"}]
    message = proposal_prompt(
        prompt="Build https://www.koratimber.com/",
        selected=selected,
        guidance="",
        references=[
            {
                "url": "https://www.koratimber.com/",
                "text": "ul. Przybyszewskiego 193, 93-120 Łódź | info@koratimber.com",
                "untrusted": True,
            }
        ],
    )
    assert "web_observations" in message
    assert "Przybyszewskiego" in message
    assert "untrusted public GET" in message
    assert "replacements" in message
    assert "exactly once" in message
    without = proposal_prompt(prompt="Build", selected=selected, guidance="")
    assert "web_observations" not in without
    assert "file deletion" in without
