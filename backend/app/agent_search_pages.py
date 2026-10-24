"""Read only public URLs bound to this agent workflow's verified search output."""

import hashlib
import json
import tempfile
import time
from pathlib import Path

from sqlalchemy import select

from app.artifacts import register_file
from app.config import get_settings
from app.db import utcnow
from app.events import append_event
from app.http_fetch import execute_fetch, public_url
from app.models import Artifact, Run, RunDependency
from app.paths import safe_join
from app.permissions import require
from app.providers import ProviderError

MAX_SOURCE_BYTES = 128 * 1024
MAX_RESULT_CHARS = 20000


def search_source(session, run, definition, *, for_execution=True):
    if run.agent_id is None:
        from app.conversation_data import reviewed_research_step

        reviewed_research_step(session, run, for_execution=for_execution)
    if set(definition.tools).intersection({"web_search", "search_pages"}) != {"web_search", "search_pages"}:
        raise ValueError("Read search sources requires the reviewed web_search tool")
    parent = session.get(Run, run.parent_run_id) if run.parent_run_id else None
    if (
        not parent
        or parent.executor_type != "agent_workflow"
        or parent.status != "succeeded"
        or parent.task_id != run.task_id
        or parent.agent_id != run.agent_id
        or parent.parameters.get("definition") != run.parameters.get("definition")
    ):
        raise ValueError("Search-page reading is missing its reviewed workflow binding")
    sources = list(
        session.scalars(
            select(Run).where(
                Run.parent_run_id == parent.id,
                Run.task_id == run.task_id,
                Run.agent_id == run.agent_id,
                Run.executor_type == "agent_tool",
                Run.parameters["tool"].as_string() == "web_search",
            )
        )
    )
    if len(sources) != 1:
        raise ValueError("Search-page reading requires one same-workflow search step")
    source = sources[0]
    if (
        source.status != "succeeded"
        or source.parameters.get("definition") != run.parameters.get("definition")
        or session.get(RunDependency, (run.id, source.id)) is None
    ):
        raise ValueError("Search-page reading requires its successful search dependency")
    children = parent.metadata_json.get("child_run_ids") or []
    if run.id not in children or source.id not in children:
        raise ValueError("Search steps do not match the published workflow manifest")
    observation = source.metadata_json.get("observation") or {}
    if not isinstance(observation, dict):
        raise ValueError("Search step has no structured observation")
    artifact = (
        session.get(Artifact, observation.get("artifact_id")) if observation.get("artifact_id") else None
    )
    if (
        not artifact
        or artifact.run_id != source.id
        or artifact.artifact_type != "json"
        or artifact.mime_type != "application/json"
        or artifact.metadata_json.get("tool") != "web_search"
        or artifact.trashed_at is not None
        or not 0 < artifact.size_bytes <= MAX_SOURCE_BYTES
    ):
        raise ValueError("Search-page reading requires its original search artifact")
    path = safe_join(get_settings().data_dir, artifact.relative_path)
    with path.open("rb") as handle:
        raw = handle.read(MAX_SOURCE_BYTES + 1)
    if len(raw) != artifact.size_bytes or hashlib.sha256(raw).hexdigest() != artifact.sha256:
        raise ValueError("Search artifact changed; source-page reading was refused")
    data = json.loads(raw)
    if (
        not isinstance(data, dict)
        or data.get("query") != definition.search_query
        or data != {key: value for key, value in observation.items() if key != "artifact_id"}
        or not isinstance(data.get("sources"), list)
        or len(data["sources"]) > 5
    ):
        raise ValueError("Search observation does not match its reviewed query and artifact")
    urls = []
    for item in data["sources"]:
        url = public_url(item.get("url")) if isinstance(item, dict) else None
        if url and url not in urls:
            urls.append(url)
        if len(urls) == 3:
            break
    return source, artifact, data, urls


async def execute_search_pages(session, run, definition, deadline):
    require(run.effective_permissions, "network_read")
    source, artifact, search, urls = search_source(session, run, definition)
    append_event(
        session,
        run.id,
        "tool.requested",
        {
            "tool": "search_pages",
            "source_run_id": source.id,
            "source_artifact_id": artifact.id,
            "urls": urls,
        },
    )
    session.commit()
    pages, errors, parents = [], [], [artifact.id]
    for url in urls:
        session.refresh(run)
        if run.status in {"cancel_requested", "canceled"}:
            return None
        if time.monotonic() >= deadline:
            raise ProviderError("Agent runtime limit exceeded during search-page reading")
        try:
            result = await execute_fetch(session, run, [url], deadline=deadline)
        except ProviderError as exc:
            session.refresh(run)
            if run.status in {"cancel_requested", "canceled"}:
                return None
            if time.monotonic() >= deadline:
                raise ProviderError("Agent runtime limit exceeded during search-page reading") from exc
            errors.append({"url": url, "error": str(exc)[:400]})
            continue
        if result is None:
            return None
        parents.append(result["artifact_id"])
        for page in result["pages"]:
            text = page.get("text", "")
            pages.append(
                {
                    **{key: value for key, value in page.items() if key != "links"},
                    "requested_url": url,
                    "text": text[:2000],
                    "truncated": page.get("truncated", False) or len(text) > 2000,
                    "source_artifact_id": result["artifact_id"],
                }
            )
    session.refresh(run)
    if run.status in {"cancel_requested", "canceled"}:
        return None
    if time.monotonic() >= deadline:
        raise ProviderError("Agent runtime limit exceeded during search-page reading")
    result = {
        "urls": urls,
        "pages": pages,
        "errors": errors,
        "fetched_at": utcnow().isoformat(),
        "query": definition.search_query,
        "search_run_id": source.id,
        "search_artifact_id": artifact.id,
        "searched_at": search.get("searched_at"),
        "partial": bool(errors) or not pages or any(not page.get("text") for page in pages),
        "untrusted": True,
        "bounded": True,
    }
    # Preserve complete URL authority; trim excerpts rather than silently changing targets.
    if len(json.dumps(result, ensure_ascii=False)) > MAX_RESULT_CHARS - 100:
        for page in pages:
            page["text"] = page["text"][:500]
            page["truncated"] = True
    if len(json.dumps(result, ensure_ascii=False)) > MAX_RESULT_CHARS - 100:
        raise ProviderError("Search-page observation exceeded its context limit")
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
        json.dump(result, handle)
        handle.flush()
        saved = register_file(
            session,
            source=Path(handle.name),
            artifact_type="json",
            mime_type="application/json",
            original_filename="search-pages.json",
            run_id=run.id,
            metadata={"tool": "search_pages"},
            parent_artifact_ids=parents,
        )
    result = {**result, "artifact_id": saved.id}
    run.metadata_json = {**run.metadata_json, "search_pages": result}
    append_event(
        session,
        run.id,
        "tool.completed",
        {
            "tool": "search_pages",
            "artifact_id": saved.id,
            "page_count": len(pages),
            "partial": result["partial"],
            "source_artifact_id": artifact.id,
        },
    )
    session.commit()
    return result
