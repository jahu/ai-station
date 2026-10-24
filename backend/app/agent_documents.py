"""Operator-selected stored documents, read only through a bounded CPU helper."""

import asyncio
import json
import os
import re
import signal
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.artifacts import register_file
from app.db import session_scope, utcnow
from app.document_schema import (
    MAX_CAPTURE_JSON,
    MAX_EXCERPT_BYTES,
    MAX_PDF_BYTES,
    MAX_TEXT_BYTES,
    MIMES,
    DocumentSnapshot,
)
from app.events import append_event
from app.models import Artifact
from app.paths import artifact_relative
from app.permissions import require
from app.python_execution import read_owned_file
from app.serialize import artifact_dict

router = APIRouter(prefix="/api/documents", tags=["documents"])
DB = Annotated[Session, Depends(session_scope)]


def _snapshot(row):
    if row is None or row.trashed_at is not None or row.mime_type not in MIMES:
        raise ValueError("Choose an available PDF, UTF-8 text or Markdown document")
    suffix = Path(row.relative_path).suffix
    limit = MAX_PDF_BYTES if row.mime_type == "application/pdf" else MAX_TEXT_BYTES
    if row.relative_path != artifact_relative(row.id, suffix) or not 1 <= row.size_bytes <= limit:
        raise ValueError("The selected document is redirected or exceeds its size limit")
    return DocumentSnapshot(
        artifact_id=row.id,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        mime_type=row.mime_type,
        name=row.original_filename or f"Document {row.id}",
    )


def reviewed_scope(session, scope, *, freeze=False):
    if scope is None:
        raise ValueError("Choose documents before enabling this tool")
    current = [
        _snapshot(session.get(Artifact, str(aid), populate_existing=True)) for aid in scope.artifact_ids
    ]
    if not scope.snapshots and freeze:
        scope.snapshots = current
    if not scope.snapshots or current != scope.snapshots:
        raise ValueError("A selected document changed; review and select the files again")
    return scope


def original_bytes(session, snapshot):
    row = session.get(Artifact, str(snapshot.artifact_id), populate_existing=True)
    if _snapshot(row) != snapshot:
        raise ValueError("A selected document changed or is unavailable")
    return read_owned_file(
        row.relative_path,
        snapshot.size_bytes,
        snapshot.sha256,
        limit=MAX_PDF_BYTES if snapshot.mime_type == "application/pdf" else MAX_TEXT_BYTES,
        binary=True,
    )


@router.post("/uploads", status_code=201)
def upload(session: DB, file: Annotated[UploadFile, File()]):
    name = Path((file.filename or "").replace("\\", "/")).name[:200]
    suffix = Path(name).suffix.lower()
    mime = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown"}.get(suffix)
    if not mime:
        raise HTTPException(422, "Upload a PDF, UTF-8 text or Markdown document")
    limit = MAX_PDF_BYTES if suffix == ".pdf" else MAX_TEXT_BYTES
    data = file.file.read(limit + 1)
    if not data or len(data) > limit:
        raise HTTPException(413, "Use PDF up to 8 MiB or UTF-8 text/Markdown up to 256 KiB")
    if suffix == ".pdf":
        if not data.startswith(b"%PDF"):
            raise HTTPException(422, "Invalid PDF header")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(422, "Choose a UTF-8 text document") from None
        if "\0" in text:
            raise HTTPException(422, "Text documents cannot contain null bytes")
    with tempfile.NamedTemporaryFile(suffix=suffix) as source:
        source.write(data)
        source.flush()
        row = register_file(
            session,
            source=Path(source.name),
            artifact_type="pdf" if suffix == ".pdf" else "text",
            mime_type=mime,
            original_filename=name,
            run_id=None,
            metadata={"source": "upload", "document_input": True},
        )
    session.commit()
    return artifact_dict(row)


async def read_document(session, run, data, mime, deadline):
    """Fixed helper, no inherited secret environment, owned Stop/reap and hard limits."""
    end = min(deadline, time.monotonic() + 10)
    session.refresh(run)
    if run.status == "cancel_requested":
        return None
    if time.monotonic() >= end:
        raise ValueError("Document reading runtime limit exceeded")
    session.commit()
    reader = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.document_reader",
        "pdf" if mime == "application/pdf" else "text",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "LANG": "C.UTF-8",
            "PYTHONNOUSERSITE": "1",
        },
    )
    pending = None
    try:
        pending = asyncio.create_task(reader.communicate(data))
        append_event(session, run.id, "document.reader.started", {"pid": reader.pid})
        session.commit()
        while True:
            session.refresh(run)
            canceled = run.status == "cancel_requested"
            session.commit()
            if canceled:
                return None
            if time.monotonic() >= end:
                raise ValueError("Document reading runtime limit exceeded")
            ready, _ = await asyncio.wait([pending], timeout=0.1)
            if ready:
                output, _ = pending.result()
                if len(output) > 2 * 1024**2:
                    raise ValueError("Document reader exceeded its output bound")
                try:
                    result = json.loads(output)
                except (ValueError, UnicodeDecodeError):
                    raise ValueError("Document reader failed or exceeded its resource limit") from None
                if reader.returncode != 0:
                    raise ValueError(result.get("error", "Document reader failed"))
                session.refresh(run)
                if run.status == "cancel_requested":
                    return None
                if time.monotonic() >= end:
                    raise ValueError("Document reading runtime limit exceeded")
                return result
    finally:
        if reader.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(reader.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(reader.wait(), timeout=1)
            except asyncio.TimeoutError:
                with suppress(ProcessLookupError):
                    os.killpg(reader.pid, signal.SIGKILL)
                await reader.wait()
        if pending is not None:
            with suppress(Exception, asyncio.CancelledError):
                await pending
        append_event(
            session, run.id, "document.reader.reaped", {"pid": reader.pid, "returncode": reader.returncode}
        )


def validate_arguments(scope, arguments):
    if not isinstance(arguments, dict) or set(arguments) - {"artifact_id", "query", "offset"}:
        raise ValueError("Refusing unexpected document arguments")
    aid, query, offset = arguments.get("artifact_id"), arguments.get("query", ""), arguments.get("offset", 0)
    if scope is None or aid is not None and aid not in [str(i) for i in scope.artifact_ids]:
        raise ValueError("The model cannot choose an unreviewed document")
    if (
        not isinstance(query, str)
        or len(query) > 200
        or type(offset) is not int
        or not 0 <= offset <= MAX_TEXT_BYTES
    ):
        raise ValueError("Use a bounded document query or text offset")
    if query and offset:
        raise ValueError("Choose a search query or a text offset")
    return {"artifact_id": aid, "query": query, "offset": offset}


def compact_observation(data, artifact_id):
    budget = MAX_EXCERPT_BYTES
    docs = []
    for item in data["documents"]:
        text, start = item["text"], data.get("offset", 0)
        query = data.get("query", "")
        match = re.search(re.escape(query), text, re.IGNORECASE) if query else None
        if query:
            start = max(0, match.start() - 300) if match else 0
        remaining_docs = len(data["documents"]) - len(docs)
        allowance = budget // remaining_docs
        excerpt = text[start:].encode("utf-8")[:allowance].decode("utf-8", errors="ignore")
        docs.append(
            {
                **item,
                "text": excerpt,
                "offset": start,
                "query_found": not query or match is not None,
                "excerpted": bool(start or len(excerpt) < len(text) or item.get("truncated")),
            }
        )
        budget -= len(excerpt.encode("utf-8"))
    return {**data, "documents": docs, "artifact_id": artifact_id}


async def execute_documents(session, run, definition, deadline, arguments=None):
    require(run.effective_permissions, "filesystem_read")
    scope = reviewed_scope(session, definition.documents)
    args = validate_arguments(scope, arguments or {})
    chosen = [s for s in scope.snapshots if args["artifact_id"] in {None, str(s.artifact_id)}]
    append_event(
        session,
        run.id,
        "tool.started",
        {"tool": "read_documents", "artifact_ids": [str(s.artifact_id) for s in chosen]},
    )
    session.commit()
    documents, parents = [], []
    for snapshot in chosen:
        raw = original_bytes(session, snapshot)
        result = await read_document(session, run, raw, snapshot.mime_type, deadline)
        if result is None:
            return None
        original_bytes(session, snapshot)
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt") as text:
            text.write(result["text"])
            text.flush()
            extracted = register_file(
                session,
                source=Path(text.name),
                artifact_type="text",
                mime_type="text/plain",
                original_filename=snapshot.name[:196] + ".txt",
                run_id=run.id,
                parent_artifact_ids=[str(snapshot.artifact_id)],
                metadata={"document_extract": True},
            )
        documents.append(
            {
                **result,
                "source_artifact_id": str(snapshot.artifact_id),
                "text_artifact_id": extracted.id,
                "source_sha256": snapshot.sha256,
                "name": snapshot.name,
                "mime_type": snapshot.mime_type,
                "untrusted": True,
            }
        )
        parents.extend([str(snapshot.artifact_id), extracted.id])
    reviewed_scope(session, scope)
    data = {
        "documents": documents,
        "query": args["query"],
        "offset": args["offset"],
        "captured_at": utcnow().isoformat(),
        "untrusted": True,
    }
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
        serialized = json.dumps(data, ensure_ascii=False)
        if len(serialized.encode("utf-8")) > MAX_CAPTURE_JSON:
            raise ValueError("Document capture exceeds its bounded JSON input; choose fewer files")
        handle.write(serialized)
        handle.flush()
        artifact = register_file(
            session,
            source=Path(handle.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename="document-capture.json",
            run_id=run.id,
            parent_artifact_ids=parents,
            metadata={"tool": "read_documents"},
        )
    append_event(session, run.id, "tool.completed", {"tool": "read_documents", "artifact_id": artifact.id})
    session.commit()
    return compact_observation(data, artifact.id)


def verified_documents(session, source, definition, *, complete=False, for_execution=True):
    scope = definition.documents
    if scope is None or not scope.snapshots:
        raise ValueError("Document capture lost its reviewed selection")
    if for_execution:
        reviewed_scope(session, scope)
        for snapshot in scope.snapshots:
            original_bytes(session, snapshot)
    require(source.effective_permissions, "filesystem_read")
    observed = source.metadata_json.get("observation")
    artifact = session.get(Artifact, observed.get("artifact_id", "")) if isinstance(observed, dict) else None
    if (
        artifact is None
        or artifact.run_id != source.id
        or artifact.trashed_at is not None
        or artifact.metadata_json.get("tool") != "read_documents"
        or artifact.mime_type != "application/json"
    ):
        raise ValueError("Document capture lost its original JSON artifact")
    data = json.loads(
        read_owned_file(
            artifact.relative_path, artifact.size_bytes, artifact.sha256, limit=MAX_CAPTURE_JSON, binary=True
        )
    )
    if compact_observation(data, artifact.id) != observed or data.get("query") or data.get("offset") != 0:
        raise ValueError("Document observation changed after capture")
    if [d.get("source_artifact_id") for d in data["documents"]] != [str(i) for i in scope.artifact_ids]:
        raise ValueError("Document capture changed its reviewed selection")
    parents = []
    for document, snapshot in zip(data["documents"], scope.snapshots, strict=True):
        text = session.get(Artifact, document.get("text_artifact_id"))
        if (
            document.get("source_sha256") != snapshot.sha256
            or text is None
            or text.run_id != source.id
            or text.trashed_at is not None
            or text.mime_type != "text/plain"
            or not text.metadata_json.get("document_extract")
            or text.parent_artifact_ids != [str(snapshot.artifact_id)]
            or read_owned_file(
                text.relative_path, text.size_bytes, text.sha256, limit=MAX_TEXT_BYTES, binary=True
            ).decode("utf-8")
            != document.get("text")
        ):
            raise ValueError("Document extraction lost its immutable source binding")
        parents.extend([str(snapshot.artifact_id), text.id])
    if artifact.parent_artifact_ids != parents:
        raise ValueError("Document capture changed its source lineage")
    return artifact, data if complete else observed, []
