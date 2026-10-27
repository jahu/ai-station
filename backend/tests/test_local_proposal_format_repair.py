"""Real owned worktrees and fake SSE inference exercise format correction."""

# Imported disposable repository/runner fixtures retain their parameter names.
# ruff: noqa: F811
import pytest
from app.api import app
from app.db import session_factory
from app.engine import tick
from app.models import Run, RunEvent, Worktree
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_projects import (  # noqa: F401
    local_coding_bridge,
    owned_runner,
    prepare_local_coding,
    register,
    repository,
    validation_sandbox,
)


@pytest.mark.parametrize("bad", ["summary", "duplicate", "unselected", "twice"])
def test_local_format_correction_writes_only_a_valid_proposal_and_retains_audit(
    repository, owned_runner, local_coding_bridge, bad
):
    good = {
        "summary": "Update the selected source",
        "files": [{"path": "README.md", "content": "Reviewed local correction\n"}],
    }
    invalid = {
        "summary": {"not": "a string"} if bad in {"summary", "twice"} else "Invalid proposal",
        "files": [
            {"path": "unselected.py" if bad == "unselected" else "README.md", "content": "NEVER APPLY\n"}
        ]
        * (2 if bad == "duplicate" else 1),
    }
    local_coding_bridge["proposal_sequence"] = [invalid, invalid if bad == "twice" else good]
    with TestClient(app) as client:
        project = register(client, repository)
        rid = prepare_local_coding(client, project)
        with session_factory()() as session:
            assert tick(session, "format-correction") == rid
            run = session.get(Run, rid)
            assert run.status == ("failed" if bad == "twice" else "succeeded"), run.error_message
            tree = session.get(Worktree, run.parameters["worktree_id"])
            work = owned_runner.data_dir / tree.relative_path
            assert (work / "README.md").read_text() == (
                "Original repository\n" if bad == "twice" else "Reviewed local correction\n"
            )
            assert not (work / "unselected.py").exists()
            assert not (work / "new.py").exists()
            assert "external_ai" not in run.effective_permissions
            events = list(session.scalars(select(RunEvent).where(RunEvent.run_id == rid)))
            assert any("coding.proposal.rejected" in str(e.payload) for e in events)
        assert len(local_coding_bridge["requests"]) == 2
        first, second = [request[1] for request in local_coding_bridge["requests"]]
        assert first["model"] == second["model"] == "fixture-local"
        assert "tools" not in second
        assert second["messages"][0]["content"].startswith(
            first["messages"][0]["content"].split("\nReturn only the requested JSON")[0]
        )
        process = owned_runner.inspect(rid)
        assert not process["alive"]
    assert (repository / "README.md").read_text() == "Original repository\n"
    assert not (repository / "unselected.py").exists()


def test_ambiguous_heading_correction_changes_only_owned_selected_file(
    repository, owned_runner, local_coding_bridge
):
    import subprocess

    original = "# QA Example Garden\nDescription QA Example Garden\nFooter QA Example Garden\n"
    expected = original.replace("# QA Example Garden", "# QA Example Garden — Updated")
    (repository / "README.md").write_text(original)
    subprocess.run(["git", "-C", str(repository), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "Owned repeated-title fixture"],
        check=True,
        capture_output=True,
    )
    local_coding_bridge["proposal_sequence"] = [
        {
            "summary": "Change heading",
            "files": [
                {
                    "path": "README.md",
                    "replacements": [{"old": "QA Example Garden", "new": "QA Example Garden — Updated"}],
                }
            ],
        },
        {"summary": "Change only heading", "files": [{"path": "README.md", "content": expected}]},
    ]
    with TestClient(app) as client:
        project = register(client, repository)
        rid = prepare_local_coding(client, project)
        with session_factory()() as session:
            assert tick(session, "unique-heading-correction") == rid
            run = session.get(Run, rid)
            assert run.status == "succeeded", run.error_message
            tree = session.get(Worktree, run.parameters["worktree_id"])
            work = owned_runner.data_dir / tree.relative_path
            assert (work / "README.md").read_text() == expected
            assert not (work / "new.py").exists()
        assert len(local_coding_bridge["requests"]) == 2
        assert "found 3 matches" in local_coding_bridge["requests"][1][1]["messages"][0]["content"]
        assert "complete content field" in local_coding_bridge["requests"][1][1]["messages"][0]["content"]
        assert not owned_runner.inspect(rid)["alive"]
    assert (repository / "README.md").read_text() == original
