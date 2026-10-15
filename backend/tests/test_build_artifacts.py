# Imported disposable repository/runner fixtures retain their parameter names.
# ruff: noqa: F811
import hashlib
import io
import zipfile
from uuid import uuid4

import pytest
from app.api import app
from app.build_artifacts import register_build
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.models import Artifact, Project, Run
from app.runner_client import RunnerClient
from app.runs import create_run, create_task, request_cancel
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_projects import (  # noqa: F401
    enqueue_validation,
    owned_runner,
    prepared_validation,
    repository,
    validation_sandbox,
)


def fake_export(session, member="index.html", *, symlink=False):
    task = create_task(session, title="Build", prompt="Build", capability="coding.validate")
    run = create_run(
        session,
        task,
        run_type="validation",
        capability="coding.validate",
        executor_type="project_validation",
        parameters={"worktree_run_id": str(uuid4())},
    )
    session.flush()
    path = get_settings().data_dir / f"runtime/validation/{run.id}.build.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        if symlink:
            info = zipfile.ZipInfo(member)
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "outside")
        else:
            archive.writestr(member, "<h1>Built</h1>")
    with zipfile.ZipFile(path) as archive:
        total = sum(m.file_size for m in archive.infolist())
    report = {
        "commands": [{"kind": "build", "exit_code": 0}],
        "build_export": {
            "status": "ready",
            "relative_path": f"runtime/validation/{run.id}.build.zip",
            "file_count": 1,
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "uncompressed_bytes": total,
        },
    }
    return run, report, path


def test_build_registration_is_hashed_portable_idempotent_and_audited(session):
    run, report, path = fake_export(session)
    register_build(session, run, report)
    register_build(session, run, report)
    artifacts = list(session.scalars(select(Artifact).where(Artifact.run_id == run.id)))
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.artifact_type == "archive" and artifact.mime_type == "application/zip"
    assert not artifact.relative_path.startswith("/") and artifact.sha256 == report["build_export"]["sha256"]
    assert (
        artifact.metadata_json["validation_run_id"] == run.id
        and artifact.metadata_json["role"] == "coding_build"
    )
    assert run.metadata_json["build_artifact_id"] == artifact.id
    assert (get_settings().data_dir / artifact.relative_path).read_bytes() == path.read_bytes()


@pytest.mark.parametrize(
    "change", ["path", "hash", "size", "count", "total", "failed", "no_build", "redirect", "hardlink"]
)
def test_build_registration_rejects_mismatches_and_redirects(session, tmp_path, change):
    run, report, path = fake_export(session)
    if change == "path":
        report["build_export"]["relative_path"] = "db/ai-station.sqlite"
    elif change == "hash":
        report["build_export"]["sha256"] = "a" * 64
    elif change == "size":
        report["build_export"]["size_bytes"] += 1
    elif change == "count":
        report["build_export"]["file_count"] = 2
    elif change == "total":
        report["build_export"]["uncompressed_bytes"] += 1
    elif change == "failed":
        report["commands"][0]["exit_code"] = 1
    elif change == "no_build":
        report["commands"][0]["kind"] = "test"
    elif change == "redirect":
        outside = tmp_path / "other.zip"
        path.rename(outside)
        path.symlink_to(outside)
    else:
        (tmp_path / "hard.zip").hardlink_to(path)
    with pytest.raises(ValueError):
        register_build(session, run, report)
    assert not list(session.scalars(select(Artifact).where(Artifact.run_id == run.id)))


@pytest.mark.parametrize(
    "member",
    [
        "../outside",
        "/outside",
        ".env",
        "assets/credentials.json",
        "assets\\outside",
        "a/../outside",
        "a//file",
        "a/./file",
    ],
)
def test_build_archive_members_are_safe_to_download(session, member):
    run, report, _ = fake_export(session, member)
    with pytest.raises(ValueError):
        register_build(session, run, report)


def test_zip_symbolic_members_cannot_be_registered(session):
    run, report, _ = fake_export(session, "link", symlink=True)
    with pytest.raises(ValueError):
        register_build(session, run, report)


def test_old_reports_and_missing_output_never_fabricate_artifacts(session):
    run, _, _ = fake_export(session)
    register_build(session, run, {"commands": [{"kind": "test", "exit_code": 0}]})
    register_build(
        session,
        run,
        {
            "build_export": {
                "status": "unavailable",
                "reason": "No dist directory was produced by this build.",
            }
        },
    )
    assert "build_artifact_id" not in run.metadata_json
    assert run.metadata_json["build_export"]["status"] == "unavailable"


@pytest.mark.parametrize("exit_code", [0, 1])
def test_native_build_becomes_downloadable_artifact_only_after_all_checks_pass(
    repository, owned_runner, validation_sandbox, exit_code
):
    before = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project, tree = prepared_validation(
            client, repository, [["/usr/bin/python3", "-c", f"raise SystemExit({exit_code})"]]
        )
        with session_factory()() as session:
            row = session.get(Project, project["id"])
            row.build_commands = [
                [
                    "/usr/bin/python3",
                    "-c",
                    "from pathlib import Path; p=Path('dist/assets'); p.mkdir(parents=True); Path('dist/index.html').write_text('<h1>Built</h1>'); (p/'app.js').write_text('42;')",
                ]
            ]
            session.commit()
        project = client.get("/api/projects/" + project["id"]).json()
        response = enqueue_validation(client, project, tree)
        assert response.status_code == 202, response.text
        rid = response.json()["id"]
        with session_factory()() as session:
            tick(session, "build-test")
        run = client.get("/api/runs/" + rid).json()
        assert run["status"] == ("succeeded" if exit_code == 0 else "failed"), run
        artifacts = client.get("/api/artifacts", params={"run_id": rid}).json()
        builds = [a for a in artifacts if a["type"] == "archive"]
        assert len(builds) == (1 if exit_code == 0 else 0)
        if builds:
            artifact = builds[0]
            assert run["metadata"]["build_artifact_id"] == artifact["id"]
            file = client.get("/api/artifacts/" + artifact["id"] + "/file")
            assert file.status_code == 200 and file.headers["x-content-type-options"] == "nosniff"
            assert file.headers["content-disposition"].startswith("attachment;")
            assert file.headers["content-type"] == "application/zip"
            with zipfile.ZipFile(io.BytesIO(file.content)) as archive:
                assert sorted(archive.namelist()) == ["assets/app.js", "index.html"]
            assert (
                client.get("/api/artifacts/" + artifact["id"]).json()["metadata"]["project_id"]
                == project["id"]
            )
    assert (repository / ".git/index").read_bytes() == before and not (repository / "dist").exists()


def test_stop_after_native_report_prevents_build_publication(
    repository, owned_runner, validation_sandbox, monkeypatch
):
    with TestClient(app) as client:
        project, tree = prepared_validation(client, repository, [["/usr/bin/true"]])
        with session_factory()() as session:
            session.get(Project, project["id"]).build_commands = [
                [
                    "/usr/bin/python3",
                    "-c",
                    "from pathlib import Path; Path('dist').mkdir(); Path('dist/index.html').write_text('Built')",
                ]
            ]
            session.commit()
        project = client.get("/api/projects/" + project["id"]).json()
        response = enqueue_validation(client, project, tree)
        assert response.status_code == 202
        rid = response.json()["id"]
        original = RunnerClient.validation_report

        def stopped(self, run_id):
            report = original(self, run_id)
            assert report["build_export"]["status"] == "ready"
            with session_factory()() as session:
                request_cancel(session, session.get(Run, run_id))
                session.commit()
            return report

        monkeypatch.setattr(RunnerClient, "validation_report", stopped)
        with session_factory()() as session:
            tick(session, "stop-build-test")
        assert client.get("/api/runs/" + rid).json()["status"] == "canceled"
        assert not client.get("/api/artifacts", params={"run_id": rid}).json()


def test_background_build_writer_is_drained_before_archive_capture(
    repository, owned_runner, validation_sandbox
):
    child = (
        "from pathlib import Path; import signal,time,sys; "
        "signal.signal(signal.SIGTERM,lambda *args:(Path('dist/child-state.txt').write_text('stopped'),sys.exit(0))); "
        "Path('dist/child-state.txt').write_text('running'); time.sleep(30)"
    )
    command = (
        "from pathlib import Path; import subprocess,sys,time; Path('dist').mkdir(); "
        "subprocess.Popen([sys.executable,'-c',"
        + repr(child)
        + "],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        "exec(\"while not Path('dist/child-state.txt').exists(): time.sleep(.02)\")"
    )
    with TestClient(app) as client:
        project, tree = prepared_validation(client, repository, [["/usr/bin/true"]])
        with session_factory()() as session:
            session.get(Project, project["id"]).build_commands = [["/usr/bin/python3", "-c", command]]
            session.commit()
        project = client.get("/api/projects/" + project["id"]).json()
        response = enqueue_validation(client, project, tree)
        assert response.status_code == 202, response.text
        rid = response.json()["id"]
        with session_factory()() as session:
            tick(session, "background-build-test")
        run = client.get("/api/runs/" + rid).json()
        assert run["status"] == "succeeded", run
        archive = client.get("/api/artifacts/" + run["metadata"]["build_artifact_id"] + "/file")
        with zipfile.ZipFile(io.BytesIO(archive.content)) as output:
            assert output.read("child-state.txt") == b"stopped"
