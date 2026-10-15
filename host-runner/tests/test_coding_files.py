import json
import subprocess

import pytest
from ai_station_runner.coding_files import apply_proposal, parse_proposal, proposal_prompt, read_selected


@pytest.mark.parametrize("content", ["", "old\n", "no newline"])
@pytest.mark.parametrize("mode", [0o644, 0o755])
def test_selected_deletion_has_reversible_git_patch(tmp_path, content, mode):
    workspace, target = tmp_path / "workspace", tmp_path / "target"
    for root in (workspace, target):
        root.mkdir()
        (root / "old file.py").write_text(content)
        (root / "old file.py").chmod(mode)
        (root / "keep.py").write_text("before\n")
    selected = read_selected(workspace, ["old file.py", "keep.py"])
    proposal = parse_proposal(
        json.dumps(
            {
                "summary": "Remove obsolete source",
                "files": [
                    {"path": "old file.py", "delete": True},
                    {"path": "keep.py", "content": "after\n"},
                ],
            }
        ),
        selected,
    )
    report = apply_proposal(workspace, selected, proposal)
    assert not (workspace / "old file.py").exists()
    assert (workspace / "keep.py").read_text() == "after\n"
    removed = report["files"][0]
    assert removed["operation"] == "delete" and removed["after_sha256"] is None
    assert removed["before_sha256"] == selected[0]["sha256"]
    assert removed["insertions"] == 0 and removed["deletions"] == len(content.splitlines())
    assert f"deleted file mode {0o100000 | mode:o}" in removed["diff"]
    patch = "".join(item["diff"] for item in report["files"])
    subprocess.run(["git", "init", str(target)], capture_output=True, check=True)
    for args in ([], ["--reverse"]):
        result = subprocess.run(
            ["git", "-C", str(target), "apply", *args, "--"], input=patch, text=True, capture_output=True
        )
        assert result.returncode == 0, result.stderr
    assert (target / "old file.py").read_text() == content
    # Git patches preserve the executable bit; permissions also follow umask.
    assert bool((target / "old file.py").stat().st_mode & 0o111) == bool(mode & 0o111)
    assert (target / "keep.py").read_text() == "before\n"


def test_stale_deletion_rejects_all_changes_before_application(tmp_path):
    (tmp_path / "old.py").write_text("original\n")
    (tmp_path / "keep.py").write_text("before\n")
    selected = read_selected(tmp_path, ["old.py", "keep.py"])
    proposal = parse_proposal(
        json.dumps(
            {
                "summary": "change",
                "files": [
                    {"path": "keep.py", "content": "after\n"},
                    {"path": "old.py", "delete": True},
                ],
            }
        ),
        selected,
    )
    (tmp_path / "old.py").write_text("human change\n")
    with pytest.raises(ValueError, match="changed after"):
        apply_proposal(tmp_path, selected, proposal)
    assert (tmp_path / "old.py").read_text() == "human change\n"
    assert (tmp_path / "keep.py").read_text() == "before\n"


def test_deletion_rejects_missing_unselected_and_redirected_paths(tmp_path):
    (tmp_path / "source.py").write_text("original\n")
    selected = read_selected(tmp_path, ["source.py", "missing.py"])
    for path in ("missing.py", "unselected.py"):
        with pytest.raises(ValueError):
            parse_proposal(
                json.dumps({"summary": "remove", "files": [{"path": path, "delete": True}]}), selected
            )
    proposal = parse_proposal(
        json.dumps({"summary": "remove", "files": [{"path": "source.py", "delete": True}]}), selected
    )
    (tmp_path / "source.py").unlink()
    outside = tmp_path.parent / "outside.py"
    outside.write_text("unrelated\n")
    (tmp_path / "source.py").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        apply_proposal(tmp_path, selected, proposal)
    assert outside.read_text() == "unrelated\n"


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
        {"path": "app.py", "delete": False},
        {"path": "app.py", "delete": 1},
        {"path": "app.py", "delete": "true"},
        {"path": "app.py", "delete": True, "content": ""},
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
    assert '"delete": true' in without and "existing selected file" in without


def test_non_json_output_reports_no_application_and_preserves_source(tmp_path):
    (tmp_path / "example.py").write_text("original = True\n")
    selected = read_selected(tmp_path, ["example.py"])
    with pytest.raises(ValueError, match="non-JSON coding proposal; no files were applied"):
        parse_proposal("I need to extend this file with a multiply function.", selected)
    assert (tmp_path / "example.py").read_text() == "original = True\n"


@pytest.mark.parametrize("exists", [False, True])
def test_root_gitignore_uses_checked_proposals_and_reversible_diff(tmp_path, exists):
    path = tmp_path / ".gitignore"
    before = "node_modules/\n" if exists else None
    if exists:
        path.write_text(before)
    selected = read_selected(tmp_path, [".gitignore"])
    assert selected[0]["content"] == before
    proposal = parse_proposal(
        json.dumps(
            {
                "summary": "Ignore build output",
                "files": [{"path": ".gitignore", "content": "node_modules/\ndist/\n"}],
            }
        ),
        selected,
    )
    report = apply_proposal(tmp_path, selected, proposal)
    assert path.read_text() == "node_modules/\ndist/\n"
    assert report["files"][0]["path"] == ".gitignore"
    assert "+dist/" in report["files"][0]["diff"]
    assert report["files"][0]["before_sha256"] == selected[0]["sha256"]
    result = subprocess.run(
        ["git", "apply", "--reverse", "--check", "--"],
        cwd=tmp_path,
        input=report["files"][0]["diff"],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".git/config",
        ".github/workflows/build.yml",
        "src/.gitignore",
        ".gitignore/config",
        "./.gitignore",
        "../.gitignore",
        "/.gitignore",
        ".gitignore/../app.py",
        ".gitignore-secret",
        "secrets/.gitignore",
    ],
)
def test_ignore_exception_does_not_grant_other_hidden_or_credential_paths(tmp_path, name):
    with pytest.raises(ValueError):
        read_selected(tmp_path, [name])


@pytest.mark.parametrize("redirect", ["symlink", "hardlink"])
def test_gitignore_redirect_cannot_read_or_replace_external_data(tmp_path, redirect):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("private\n")
    path = workspace / ".gitignore"
    selected = read_selected(workspace, [".gitignore"])
    proposal = parse_proposal(
        json.dumps({"summary": "Ignore builds", "files": [{"path": ".gitignore", "content": "dist/\n"}]}),
        selected,
    )
    if redirect == "symlink":
        path.symlink_to(outside)
    else:
        path.hardlink_to(outside)
    with pytest.raises(ValueError):
        read_selected(workspace, [".gitignore"])
    with pytest.raises(ValueError):
        apply_proposal(workspace, selected, proposal)
    assert outside.read_text() == "private\n"


def test_concurrently_changed_gitignore_prevents_other_writes(tmp_path):
    (tmp_path / ".gitignore").write_text("dist/\n")
    selected = read_selected(tmp_path, ["new.js", ".gitignore"])
    proposal = parse_proposal(
        json.dumps(
            {
                "summary": "Add app",
                "files": [
                    {"path": "new.js", "content": "export default 1;"},
                    {"path": ".gitignore", "content": "node_modules/\n"},
                ],
            }
        ),
        selected,
    )
    (tmp_path / ".gitignore").write_text("human change\n")
    with pytest.raises(ValueError, match="changed after"):
        apply_proposal(tmp_path, selected, proposal)
    assert not (tmp_path / "new.js").exists()
    assert (tmp_path / ".gitignore").read_text() == "human change\n"
