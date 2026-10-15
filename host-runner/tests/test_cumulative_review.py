import json
import subprocess

import pytest
from ai_station_runner.coding_files import read_review_files, read_selected
from ai_station_runner.coding_review import checked_report_bytes, projected_review
from ai_station_runner.gitinspect import BASE_CONFIG, git_environment
from ai_station_runner.source_inventory import source_file_args


def git(root, *args):
    return subprocess.check_output(
        ["git", *BASE_CONFIG, "-C", str(root), *args], env=git_environment(), text=True
    )


def test_source_inventory_ignores_only_untracked_reserved_execution_directories(tmp_path):
    git(tmp_path, "init", "-b", "develop")
    for name in [
        "app.py",
        ".ai-station-validation-old/.npm/log.txt",
        ".ai-station-dependencies-old/cache/item.json",
        "nested/.ai-station-validation-user/notes.py",
    ]:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("source or retained metadata")
    (tmp_path / ".ai-station-validation-file").write_text("not a directory")
    (tmp_path / ".ai-station-validation-link").symlink_to(tmp_path / "nested", target_is_directory=True)
    paths = set(filter(None, git(tmp_path, *source_file_args()).split("\0")))
    assert "app.py" in paths and "nested/.ai-station-validation-user/notes.py" in paths
    assert ".ai-station-validation-file" in paths and ".ai-station-validation-link" in paths
    assert (
        ".ai-station-validation-old/.npm/log.txt" not in paths
        and ".ai-station-dependencies-old/cache/item.json" not in paths
    )
    # A tracked reserved name is never silently hidden from a source inventory.
    git(tmp_path, "add", "-f", "--", ".ai-station-validation-old/.npm/log.txt")
    assert ".ai-station-validation-old/.npm/log.txt" in git(tmp_path, *source_file_args(cached=True)).split(
        "\0"
    )
    assert (tmp_path / ".ai-station-validation-old/.npm/log.txt").read_text() == "source or retained metadata"


def test_review_can_hash_locks_and_many_files_without_expanding_model_context(tmp_path):
    names = []
    for index in range(12):
        name = f"part{index}.py"
        (tmp_path / name).write_text("x=1\n")
        names.append(name)
    (tmp_path / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "padding": "x" * 33000}))
    names.append("package-lock.json")
    reviewed = read_review_files(tmp_path, names)
    assert len(reviewed) == 13 and all(item["sha256"] for item in reviewed)
    with pytest.raises(ValueError):
        read_selected(tmp_path, names)
    with pytest.raises(ValueError):
        read_selected(tmp_path, ["package-lock.json"])


@pytest.mark.parametrize(
    "name",
    [".env", "src/../out.py", "/etc/passwd", ".ai-station-validation-old/private.py", "credentials.json"],
)
def test_review_does_not_relax_path_or_credentials_policy(tmp_path, name):
    with pytest.raises(ValueError):
        read_review_files(tmp_path, [name])


def test_review_still_rejects_links_binary_duplicates_and_resource_excess(tmp_path):
    (tmp_path / "original").write_text("private")
    (tmp_path / "link").symlink_to(tmp_path / "original")
    (tmp_path / "hard").hardlink_to(tmp_path / "original")
    (tmp_path / "binary").write_bytes(b"\0")
    (tmp_path / "large").write_bytes(b"x" * 256001)
    for name in ["link", "hard", "binary", "large"]:
        with pytest.raises(ValueError):
            read_review_files(tmp_path, [name])
    with pytest.raises(ValueError):
        read_review_files(tmp_path, ["missing"] * 2)
    with pytest.raises(ValueError):
        read_review_files(tmp_path, [f"file{i}" for i in range(201)])
    for index in range(9):
        (tmp_path / f"full{index}").write_bytes(b"x" * 250000)
    with pytest.raises(ValueError):
        read_review_files(tmp_path, [f"full{i}" for i in range(9)])


def test_projected_review_uses_base_without_applying_or_sharing_prior_files(tmp_path):
    class Result:
        def __init__(self, stdout="", code=0):
            self.stdout = stdout
            self.returncode = code

    class Repo:
        def read(self, args, check=True):
            if args[0] == "diff":
                return Result("before.py\0")
            if args[0] == "ls-files":
                return Result("package-lock.json\0")
            if args[0] == "show":
                return Result("old\n") if args[1] == "HEAD:before.py" else Result(code=128)
            if args[0] == "ls-tree":
                return Result("100644 blob value\tbefore.py\n") if args[-1] == "before.py" else Result()
            raise AssertionError(args)

    (tmp_path / "before.py").write_text("earlier turn\n")
    (tmp_path / "package-lock.json").write_text("x" * 33000)
    selected = read_selected(tmp_path, ["new.py"])
    proposal = {"summary": "Add source", "files": [{"path": "new.py", "content": "new\n"}]}
    changes, snapshots = projected_review(Repo(), tmp_path, selected, proposal, cumulative=True)
    assert {c["path"] for c in changes} == {"before.py", "new.py", "package-lock.json"}
    assert next(c for c in changes if c["path"] == "before.py")["before_sha256"]
    assert len(snapshots) == 3 and selected[0]["content"] is None
    assert not (tmp_path / "new.py").exists()


def test_encoded_review_limit_counts_json_escaping_before_publication():
    with pytest.raises(ValueError, match="1 MiB"):
        checked_report_bytes({"summary": "bounded", "files": [{"diff": "\x01" * 180000}]})
    assert json.loads(checked_report_bytes({"files": []})) == {"files": []}
