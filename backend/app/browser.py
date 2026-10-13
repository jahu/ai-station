"""Reviewed public-page runs and artifact adoption through the native boundary."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.artifacts import register_file
from app.config import get_settings
from app.db import session_factory, utcnow
from app.events import append_event
from app.http_fetch import reviewed_urls
from app.native_job_executor import NativeJobExecutor
from app.paths import safe_join
from app.runner_client import RunnerClient, RunnerError, RunnerUnavailable
from app.runs import create_run, create_task, run_dict, transition
from app.state import RunStatus

router = APIRouter(prefix="/api/browser", tags=["browser"])


def available():
    if not get_settings().browser_enabled:
        return {"available": False, "reason": "Enable the optional browser executor after building its image"}
    try:
        return RunnerClient(timeout=2).request("GET", "/v1/browser/capabilities")
    except (RunnerError, RunnerUnavailable):
        return {"available": False, "reason": "Host Runner browser executor is unavailable"}


class PageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    urls: list[str] = Field(min_length=1, max_length=3)

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, values):
        return reviewed_urls(values)


@router.get("/capabilities")
def capabilities():
    return available()


@router.post("/runs", status_code=202)
def enqueue(body: PageRequest):
    if not available()["available"]:
        raise HTTPException(503, "Browser executor is unavailable; inspect its setup in Diagnostics")
    with session_factory()() as session:
        task = create_task(
            session, title="Inspect public pages", prompt="\n".join(body.urls), capability="browser"
        )
        run = create_run(
            session,
            task,
            run_type="browser",
            capability="browser.inspect",
            executor_type="browser",
            execution_target="host",
            parameters={"urls": body.urls},
            permissions=["browser", "network_read"],
            retry_class="inspect",
            triggered_by="user",
        )
        session.commit()
        return run_dict(run)


class BrowserExecutor(NativeJobExecutor):
    name = "browser"
    permissions = ("browser", "network_read")
    error_type = "BrowserFailed"

    def payload(self, run):
        maximum_runtime = 165
        if run.agent_id:
            from app.agent_schema import AgentSettings

            definition = AgentSettings.model_validate(run.parameters["definition"])
            if "browser" not in definition.tools or run.parameters.get("tool") != "browser":
                raise ValueError("Browser is not an approved workflow step")
            urls = definition.fetch_urls
            deadline = datetime.fromisoformat(run.parameters["deadline_at"])
            maximum_runtime = min(maximum_runtime, int((deadline - utcnow()).total_seconds()))
            if maximum_runtime < 5:
                raise ValueError("Agent runtime limit exceeded before browsing")
        else:
            urls = run.parameters["urls"]
        return {
            "run_id": run.id,
            "urls": reviewed_urls(urls),
            "permissions": list(run.effective_permissions),
            "maximum_runtime": maximum_runtime,
        }

    def start(self, runner, payload):
        return runner.request("POST", "/v1/runs/browser", payload)

    def report(self, runner, run_id):
        return runner.request("GET", f"/v1/runs/browser/{run_id}/report")

    def finish(self, session, run, report):
        expected = reviewed_urls(
            run.parameters["definition"]["fetch_urls"] if run.agent_id else run.parameters["urls"]
        )
        if (
            report.get("run_id") != run.id
            or report.get("urls") != expected
            or len(report.get("pages", [])) != len(expected)
        ):
            raise ValueError("Browser report does not match the reviewed request")
        pages = []
        for index, raw in enumerate(report["pages"]):
            relative = f"runtime/browser/{run.id}/page-{index}.png"
            if raw.get("screenshot_path") != relative:
                raise ValueError("Unexpected browser screenshot path")
            source = safe_join(get_settings().data_dir, relative)
            artifact = register_file(
                session,
                source=source,
                artifact_type="image",
                mime_type="image/png",
                original_filename=f"page-{index + 1}.png",
                run_id=run.id,
                metadata={
                    "tool": "browser",
                    "url": raw["url"],
                    "title": raw["title"],
                    "operation": "browser.inspect",
                },
            )
            page = {key: value for key, value in raw.items() if key not in {"screenshot_path", "event"}}
            page["screenshot_artifact_id"] = artifact.id
            pages.append(page)
            append_event(
                session,
                run.id,
                "browser.page.completed",
                {"index": index, "url": page["url"], "artifact_id": artifact.id},
            )
        result = {
            "urls": expected,
            "pages": pages,
            "captured_at": report["captured_at"],
            "untrusted": True,
            "bounded": True,
        }
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as handle:
            json.dump(result, handle)
            handle.flush()
            artifact = register_file(
                session,
                source=Path(handle.name),
                artifact_type="json",
                mime_type="application/json",
                original_filename="browser-pages.json",
                run_id=run.id,
                metadata={"tool": "browser"},
            )
        result["artifact_id"] = artifact.id
        # Full network audit stays in JSON; inference receives bounded page text.
        result["pages"] = [
            {
                **{key: value for key, value in page.items() if key not in {"requests", "links"}},
                "links": page.get("links", [])[:3],
                "request_count": len(page.get("requests", [])),
                "blocked_resource_count": page.get("blocked_request_count", 0)
                + sum(1 for request in page.get("requests", []) if request.get("error")),
            }
            for page in pages
        ]
        if run.agent_id and "remember_workflow" in run.parameters["definition"]["tools"]:
            from app.agent_executor import persist_agent_memory

            persist_agent_memory(
                session,
                run,
                json.dumps(result),
                tags=["agent-workflow", "browser"],
                tool="remember_workflow",
                excerpt_notice="\n\n[Excerpt: open the source Run for the full observation.]",
            )
        run.metadata_json = {**run.metadata_json, "observation": result, "browser": result}
        run.summary = f"Inspected {len(pages)} public pages with JavaScript; screenshots are in Library."
        append_event(
            session,
            run.id,
            "tool.completed",
            {"tool": "browser", "page_count": len(pages), "artifact_id": artifact.id},
        )
        transition(session, run, RunStatus.SUCCEEDED, event_type="run.completed", payload={})
        return "done"
