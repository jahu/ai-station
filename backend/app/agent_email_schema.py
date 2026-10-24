"""Pure future result-delivery policy; not an operational agent adapter yet."""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.email_schema import SMTPSettings, mailbox

TEMPLATE = "agent-result-v1"
MAX_BODY_CHARS = 16000
MAX_REPORT_CHARS = 128000


class AgentReportEmailScope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    connector_id: UUID
    connector_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    recipients: list[str] = Field(min_length=1, max_length=5)
    mode: Literal["review", "automatic"] = "review"
    content: Literal["report", "summary"] = "report"
    subject_prefix: str = Field(default="AI Station", min_length=1, max_length=80, pattern=r"^[^\r\n\x00]+$")

    @field_validator("recipients")
    @classmethod
    def reviewed_recipients(cls, values):
        return SMTPSettings.valid_recipients(values)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def definition_fingerprint(definition):
    # Activation changes enabled itself. Every other reviewed field is authority:
    # changing tools, source scope, model, goal or policy needs another grant.
    return digest(definition.model_dump(mode="json", exclude={"enabled"}))


def consent_payload(agent_id, definition, scope: AgentReportEmailScope, sender):
    return {
        "agent_id": str(UUID(str(agent_id))),
        "definition_hash": definition_fingerprint(definition),
        "scope": scope.model_dump(mode="json"),
        "sender": mailbox(sender),
        "recipients": list(scope.recipients),
        "template": TEMPLATE,
        "source": "verified-completed-agent-result",
    }


def render_report(scope: AgentReportEmailScope, name, run_id, artifact_id, text):
    """Render literal saved report bytes; the caller must verify their provenance.

    Recipients/transport are deliberately absent. This function cannot infer a
    completion state or choose a different source. It does not read files/send.
    """
    if scope.content != "report":
        raise ValueError("Use a verified result summary renderer for summary delivery")
    if not isinstance(text, str) or not text.strip() or "\x00" in text or len(text) > MAX_REPORT_CHARS:
        raise ValueError("Choose a bounded, intact completed report")
    name = " ".join(str(name).replace("\x00", " ").split())[:200] or "Agent"
    header = (
        f"AI Station agent result\nAgent: {name}\nRun: {UUID(str(run_id))}\n"
        f"Report artifact: {UUID(str(artifact_id))}\n\n"
    )
    notice = "\n\n[Excerpt. The complete original report is retained in AI Station under the Run and artifact IDs above.]"
    excerpted = len(header) + len(text) > MAX_BODY_CHARS
    report = text[: MAX_BODY_CHARS - len(header) - len(notice)] + notice if excerpted else text
    return {
        "subject": (scope.subject_prefix + " · " + name)[:200],
        "body": header + report,
        "excerpted": excerpted,
    }
