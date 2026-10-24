"""Explicit document scope feeds reports without granting arbitrary file access."""

import asyncio
import io
import json
import os
import time
from uuid import uuid4

import pytest
from app.agent_documents import read_document, validate_arguments, verified_documents
from app.agent_schema import AgentSettings
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.local_provider import LocalChatProvider
from app.models import Artifact, Run
from app.runs import request_cancel
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import select
from test_agents import create, drain, run_now, workflow_step


def test_selected_text_document_feeds_report_and_keeps_provenance(monkeypatch):
    requests = []

    async def stream(self, **kwargs):
        requests.append(kwargs["messages"])
        yield "The selected document contains the values 12 and 15."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    uploaded = api.post(
        "/api/documents/uploads",
        files={"file": ("observations.txt", b"Observed values: 12 and 15.", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    artifact = uploaded.json()
    agent = create(
        api,
        tools=["read_documents"],
        documents={"artifact_ids": [artifact["id"]]},
        enabled=True,
    )
    assert agent["documents"]["snapshots"][0]["artifact_id"] == artifact["id"]
    queued = run_now(api, agent)
    with session_factory()() as session:
        drain(session)
    source = workflow_step(api, queued["id"], "read_documents")
    report = workflow_step(api, queued["id"], "report")
    assert source["status"] == report["status"] == "succeeded", report
    assert "Observed values: 12 and 15." in json.dumps(requests)
    assert source["effective_permissions"] == ["filesystem_read"]
    assert source["metadata"]["observation"]["documents"][0]["source_artifact_id"] == artifact["id"]


def upload_document(api, data=b"Observed values: 12 and 15.", name="observations.txt"):
    result = api.post("/api/documents/uploads", files={"file": (name, data)})
    assert result.status_code == 201, result.text
    return result.json()


def capture_only(api, artifact, **settings):
    from app.engine import tick

    agent = create(
        api, tools=["read_documents"], documents={"artifact_ids": [artifact["id"]]}, enabled=True, **settings
    )
    parent = run_now(api, agent)
    with session_factory()() as session:
        assert tick(session, "document-parent") == parent["id"]
        source = workflow_step(api, parent["id"], "read_documents")
        assert tick(session, "document-source") == source["id"]
    return agent, parent, workflow_step(api, parent["id"], "read_documents")


def test_real_pdf_extraction_and_read_only_library_selection(monkeypatch):
    from test_chat import _pdf

    async def stream(self, **kwargs):
        assert "WillowClause" in json.dumps(kwargs["messages"])
        yield "The selected contract contains WillowClause."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    original = _pdf("WillowClause")
    document = upload_document(api, original, "contract.pdf")
    _, parent, source = capture_only(api, document)
    assert source["status"] == "succeeded", source
    observed = source["metadata"]["observation"]["documents"][0]
    assert observed["page_count"] == 1 and not observed["truncated"]
    assert "WillowClause" in observed["text"]
    references = api.get("/api/artifacts?kind=references").json()
    assert document["id"] in [item["id"] for item in references]
    assert document["id"] not in [item["id"] for item in api.get("/api/artifacts?kind=document").json()]
    with session_factory()() as session:
        drain(session)
    assert workflow_step(api, parent["id"], "report")["status"] == "succeeded"
    from app.config import get_settings

    assert (get_settings().data_dir / document["relative_path"]).read_bytes() == original


@pytest.mark.parametrize(
    "name,content,status",
    [
        ("secrets.exe", b"x", 422),
        ("wrong.pdf", b"not a pdf", 422),
        ("binary.txt", b"\xff\xfe", 422),
        ("nul.md", b"abc\0def", 422),
        ("empty.txt", b"", 413),
        ("large.txt", b"x" * (256 * 1024 + 1), 413),
    ],
)
def test_document_upload_validates_without_starting_a_workload(name, content, status):
    api = TestClient(app)
    result = api.post("/api/documents/uploads", files={"file": (name, content)})
    assert result.status_code == status, result.text
    with session_factory()() as session:
        assert not list(session.scalars(select(Run)))
        assert not list(session.scalars(select(Artifact)))


@pytest.mark.parametrize("kind", ["corrupt", "encrypted", "scanned", "too_many_pages"])
def test_unreadable_pdf_fails_before_model_with_clear_diagnostic(kind, monkeypatch):
    requests = []

    async def stream(self, **kwargs):
        requests.append(kwargs)
        yield "Must not be called"

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    content = b"%PDF bad payload secret-marker"
    expected = "document"
    if kind != "corrupt":
        writer = PdfWriter()
        for _ in range(65 if kind == "too_many_pages" else 1):
            writer.add_blank_page(200, 200)
        if kind == "encrypted":
            writer.encrypt("private-password")
        output = io.BytesIO()
        writer.write(output)
        content = output.getvalue()
        expected = {"encrypted": "Encrypted", "scanned": "OCR", "too_many_pages": "64 pages"}[kind]
    api = TestClient(app)
    artifact = upload_document(api, content, "input.pdf")
    _, parent, source = capture_only(api, artifact)
    with session_factory()() as session:
        drain(session)
    assert source["status"] == "failed", source
    assert expected in source["error_message"]
    assert "secret-marker" not in source["error_message"]
    assert workflow_step(api, parent["id"], "report")["status"] != "succeeded"
    assert not requests


@pytest.mark.parametrize("change", ["bytes", "symlink", "path", "trash", "capture", "metadata", "extracted"])
def test_changed_sources_fail_closed_and_never_reach_model(change, monkeypatch, tmp_path):
    requests = []

    async def stream(self, **kwargs):
        requests.append(kwargs)
        yield "Must not be called"

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    artifact = upload_document(api)
    _, parent, source = capture_only(api, artifact)
    assert source["status"] == "succeeded"
    with session_factory()() as s:
        row = s.get(Artifact, artifact["id"])
        path = get_settings().data_dir / row.relative_path
        if change == "bytes":
            path.write_bytes(b"Changed source")
        elif change == "symlink":
            outside = tmp_path / "outside.txt"
            outside.write_bytes(path.read_bytes())
            path.unlink()
            path.symlink_to(outside)
        elif change == "path":
            row.relative_path = "../outside.txt"
        elif change == "trash":
            from app.db import utcnow

            row.trashed_at = utcnow()
        else:
            saved = s.get(Run, source["id"])
            if change == "metadata":
                saved.metadata_json = {**saved.metadata_json, "observation": {"artifact_id": str(uuid4())}}
            else:
                aid = (
                    source["metadata"]["observation"]["artifact_id"]
                    if change == "capture"
                    else source["metadata"]["observation"]["documents"][0]["text_artifact_id"]
                )
                captured = s.get(Artifact, aid)
                (get_settings().data_dir / captured.relative_path).write_text("Changed capture")
        s.commit()
    with session_factory()() as session:
        drain(session)
    report = workflow_step(api, parent["id"], "report")
    assert report["status"] == "failed", report
    assert not requests


def test_legacy_identity_document_scope_arguments_pause_and_historical_capture():
    api = TestClient(app)
    legacy = AgentSettings(name="Legacy", goal="Report", model="fake-local")
    assert "documents" not in legacy.model_dump(mode="json")
    artifact = upload_document(api)
    agent, _, source = capture_only(api, artifact)
    definition = AgentSettings.model_validate(source["parameters"]["definition"])
    from app.agent_tools import calling_tools, parse_tool_call

    schema = calling_tools(definition)[0]["function"]["parameters"]
    assert schema["properties"]["artifact_id"]["enum"] == [artifact["id"]]
    for args in [
        {"path": "/etc/passwd"},
        {"artifact_id": str(uuid4())},
        {"offset": True},
        {"query": "x", "offset": 1},
        {"url": "https://example.com"},
    ]:
        with pytest.raises(ValueError):
            parse_tool_call(definition, {"name": "read_documents", "arguments": json.dumps(args)})
    assert validate_arguments(definition.documents, {"query": "values"})["query"] == "values"
    with session_factory()() as s:
        from app.db import utcnow

        s.get(Artifact, artifact["id"]).trashed_at = utcnow()
        s.commit()
        saved = s.get(Run, source["id"])
        _, historical, _ = verified_documents(s, saved, definition, for_execution=False, complete=True)
        assert historical["documents"][0]["text"] == "Observed values: 12 and 15."
        with pytest.raises(ValueError):
            verified_documents(s, saved, definition)
    paused = api.post(
        f"/api/agents/{agent['id']}/enabled",
        json={"enabled": False, "expected_updated_at": agent["updated_at"]},
    )
    assert paused.status_code == 200, paused.text
    assert not paused.json()["document_readiness"]["ready"]
    refused = api.post(
        f"/api/agents/{agent['id']}/enabled",
        json={"enabled": True, "expected_updated_at": paused.json()["updated_at"]},
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.parametrize("cause", ["stop", "deadline", "audit_error"])
def test_reader_stop_deadline_and_audit_error_reap_only_owned_process(cause, monkeypatch):
    import sys

    from app import agent_documents
    from app.engine import tick

    api = TestClient(app)
    artifact = upload_document(api)
    agent = create(api, tools=["read_documents"], documents={"artifact_ids": [artifact["id"]]}, enabled=True)
    parent = run_now(api, agent)
    with session_factory()() as s:
        tick(s, "document-stop-parent")
    source = workflow_step(api, parent["id"], "read_documents")
    original_spawn = asyncio.create_subprocess_exec
    processes = []

    async def spawn(*args, **kwargs):
        assert args[:3] == (sys.executable, "-m", "app.document_reader")
        assert "PRIVATE_TEST_CREDENTIAL" not in kwargs["env"]
        proc = await original_spawn(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        processes.append(proc)
        if cause == "stop":
            with session_factory()() as cancel:
                request_cancel(cancel, cancel.get(Run, source["id"]))
                cancel.commit()
        return proc

    monkeypatch.setenv("PRIVATE_TEST_CREDENTIAL", "must-not-inherit")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    append = agent_documents.append_event

    def audit(session, rid, name, payload):
        if name == "document.reader.started" and cause == "audit_error":
            raise RuntimeError("Synthetic audit failure")
        return append(session, rid, name, payload)

    monkeypatch.setattr(agent_documents, "append_event", audit)
    with session_factory()() as s:
        run = s.get(Run, source["id"])
        run.status = "running"
        s.commit()
        if cause == "stop":
            assert asyncio.run(read_document(s, run, b"text", "text/plain", time.monotonic() + 5)) is None
        else:
            error = RuntimeError if cause == "audit_error" else ValueError
            with pytest.raises(error, match="audit|runtime limit"):
                asyncio.run(read_document(s, run, b"text", "text/plain", time.monotonic() + 0.3))
    assert len(processes) == 1 and processes[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(processes[0].pid, 0)


@pytest.mark.parametrize("padding", ["a", "ß"])
def test_query_window_is_bounded_and_has_explicit_excerpt(padding):
    from app.agent_documents import compact_observation

    text = "Start " + padding * 18000 + " SPECIAL NEEDLE ending"
    data = {"documents": [{"text": text, "truncated": False}], "query": "special needle", "offset": 0}
    excerpt = compact_observation(data, "capture")["documents"][0]
    assert excerpt["query_found"] and excerpt["excerpted"] and excerpt["offset"] > 10000
    assert "SPECIAL NEEDLE" in excerpt["text"] and len(excerpt["text"].encode()) <= 12000


def test_worker_loss_kills_the_actual_reader_before_its_blocking_input_can_orphan():
    """Disposable Linux subreaper verifies the real helper's parent-death contract."""
    import subprocess
    import sys
    import textwrap
    from pathlib import Path

    parent_code = textwrap.dedent("""
        import subprocess,sys,time
        from pathlib import Path
        reader=subprocess.Popen([sys.executable,"-m","app.document_reader","text"],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        for _ in range(200):
            if "pipe_read" in Path(f"/proc/{reader.pid}/wchan").read_text():
                break
            assert reader.poll() is None
            time.sleep(.01)
        else:
            reader.kill();reader.wait();raise RuntimeError("Reader did not reach its bounded input")
        print(reader.pid,flush=True)
        time.sleep(30)
    """)
    harness = textwrap.dedent("""
        import ctypes,os,signal,subprocess,sys,time
        assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0
        parent=subprocess.Popen([sys.executable,"-c",sys.argv[1]],stdout=subprocess.PIPE,text=True)
        pid=None
        try:
            pid=int(parent.stdout.readline())
            parent.kill();parent.wait(timeout=3)
            until=time.monotonic()+3
            while time.monotonic()<until:
                child,status=os.waitpid(pid,os.WNOHANG)
                if child:
                    assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
                    print("owned reader killed and reaped after worker loss")
                    break
                time.sleep(.01)
            else:
                raise RuntimeError("Reader survived worker loss")
        finally:
            if parent.poll() is None:
                parent.kill();parent.wait()
            if pid:
                try:os.kill(pid,signal.SIGKILL);os.waitpid(pid,0)
                except (ProcessLookupError,ChildProcessError):pass
    """)
    result = subprocess.run(
        [sys.executable, "-c", harness, parent_code],
        env={"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "owned reader killed and reaped" in result.stdout


def test_report_searches_a_selected_document_and_records_the_actual_window(monkeypatch):
    calls = []

    async def stream(self, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            kwargs["on_tool_calls"](
                [
                    {
                        "id": "window",
                        "name": "read_documents",
                        "arguments": json.dumps({"query": "SPECIAL NEEDLE"}),
                    }
                ]
            )
            yield ""
        else:
            last = json.loads(kwargs["messages"][-1]["content"])
            assert last["documents"][0]["query_found"]
            assert "SPECIAL NEEDLE" in last["documents"][0]["text"]
            yield "The selected document contains SPECIAL NEEDLE."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    api = TestClient(app)
    artifact = upload_document(api, b"a" * 18000 + b" SPECIAL NEEDLE conclusion")
    _, parent, _ = capture_only(api, artifact, tool_calling="bounded")
    with session_factory()() as s:
        drain(s)
    report = workflow_step(api, parent["id"], "report")
    assert report["status"] == "succeeded", report
    call = report["metadata"]["tool_calls"][0]
    assert call["result"]["query"] == "SPECIAL NEEDLE"
    assert call["result"]["documents"][0]["offset"] > 12000
    captured = api.get("/api/artifacts/" + call["result"]["artifact_id"]).json()
    assert captured["run_id"] == report["id"]
    assert len(calls) == 2
