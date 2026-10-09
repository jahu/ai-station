from pathlib import Path

import pytest
from app.api import app
from app.config import get_settings
from app.db import session_factory
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.skills import SkillError, list_skills, load_skill, snapshot_skills, verify_snapshots
from fastapi.testclient import TestClient


def drain(session, worker="skill-test", limit=30):
    for _ in range(limit):
        if tick(session, worker) is None:
            return
    raise AssertionError("worker queue did not drain")


def workflow_step(api, parent_id, key):
    parent = api.get("/api/runs/" + parent_id).json()
    step = next(item for item in parent["workflow"]["steps"] if item["key"] == key)
    return api.get("/api/runs/" + step["run_id"]).json()


def _skill_dir(skill_id: str) -> Path:
    path = get_settings().data_dir / "skills" / skill_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def install_skill(
    skill_id="daily-brief",
    *,
    name="Daily brief",
    version="1.0.0",
    description="Local status report format",
    permissions="",
    instructions="Always mention GPU memory if it is present in the observations.",
) -> Path:
    path = _skill_dir(skill_id) / "SKILL.md"
    path.write_text(
        (
            f"---\nid: {skill_id}\nname: {name}\nversion: {version}\n"
            f"description: {description}\nrequired_permissions: {permissions}\n---\n\n"
            f"{instructions}\n"
        ),
        encoding="utf-8",
    )
    return path


def test_catalog_skips_invalid_skills_and_serves_installed_documents():
    install_skill()
    (_skill_dir("broken") / "SKILL.md").write_text("not frontmatter", encoding="utf-8")
    api = TestClient(app)
    catalog = api.get("/api/skills")
    assert catalog.status_code == 200
    assert [item["id"] for item in catalog.json()] == ["daily-brief"]
    detail = api.get("/api/skills/daily-brief")
    assert detail.status_code == 200
    assert "GPU memory" in detail.json()["instructions"]
    assert api.get("/api/skills/missing-skill").status_code == 404


def test_symlink_and_unknown_permissions_are_rejected():
    target = get_settings().data_dir / "outside.md"
    target.write_text("secret", encoding="utf-8")
    linked = _skill_dir("linked-skill") / "SKILL.md"
    linked.symlink_to(target)
    with pytest.raises(SkillError, match="regular SKILL.md"):
        load_skill("linked-skill")
    install_skill("needs-shell", permissions="not-a-permission")
    with pytest.raises(SkillError, match="unknown permissions"):
        snapshot_skills(["needs-shell"])


def test_agent_rejects_missing_skill_and_ungranted_skill_permissions():
    api = TestClient(app)
    missing = api.post(
        "/api/agents",
        json={"name": "Test", "goal": "Report", "skills": ["unimplemented"]},
    )
    assert missing.status_code == 422
    install_skill("needs-net", permissions="network_read")
    denied = api.post(
        "/api/agents",
        json={"name": "Test", "goal": "Report", "skills": ["needs-net"]},
    )
    assert denied.status_code == 422 and "not granted" in denied.text
    allowed = api.post(
        "/api/agents",
        json={
            "name": "Test",
            "goal": "Report",
            "tools": ["web_search"],
            "search_query": "open models",
            "skills": ["needs-net"],
        },
    )
    assert allowed.status_code == 201
    assert allowed.json()["skills"] == ["needs-net"]


def test_factory_attaches_mentioned_installed_skills_without_enabling():
    install_skill()
    api = TestClient(app)
    draft = api.post(
        "/api/agents/draft",
        json={
            "instruction": "Every morning write a Daily brief of workstation status",
            "model": "fake-local",
        },
    ).json()
    assert draft["enabled"] is False
    assert draft["skills"] == ["daily-brief"]
    ignored = api.post(
        "/api/agents/draft",
        json={"instruction": "Every morning summarize GPU memory", "model": "fake-local"},
    ).json()
    assert ignored["skills"] == []


def test_queued_run_fails_when_installed_skill_changes(monkeypatch):
    received = []

    async def complete(self, **kwargs):
        received.append(kwargs)
        yield "Skill-informed report."

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    path = install_skill()
    api = TestClient(app)
    created = api.post(
        "/api/agents",
        json={
            "name": "Brief",
            "goal": "Summarize available context",
            "model": "fake-local",
            "skills": ["daily-brief"],
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    queued = api.post(f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]})
    assert queued.status_code == 202, queued.text
    snapshots = queued.json()["parameters"]["skill_snapshots"]
    assert snapshots[0]["id"] == "daily-brief"
    path.write_text(path.read_text(encoding="utf-8") + "\nChanged after queue.\n", encoding="utf-8")
    parent_id = queued.json()["id"]
    with session_factory()() as session:
        drain(session, "skill-test")
    failed = workflow_step(api, parent_id, "report")
    assert failed["status"] == "failed"
    assert "changed after this run was queued" in failed["error_message"]
    assert received == []


def test_verified_skill_text_is_injected_and_recorded(monkeypatch):
    received = []

    async def complete(self, **kwargs):
        received.append(kwargs)
        yield "A factual local report."

    monkeypatch.setattr(LocalChatProvider, "stream", complete)
    install_skill(instructions="Cite only supplied observations.")
    api = TestClient(app)
    agent = api.post(
        "/api/agents",
        json={
            "name": "Brief",
            "goal": "Summarize available context",
            "model": "fake-local",
            "skills": ["daily-brief"],
            "enabled": True,
        },
    ).json()
    queued = api.post(
        f"/api/agents/{agent['id']}/run", json={"expected_updated_at": agent["updated_at"]}
    ).json()
    with session_factory()() as session:
        drain(session, "skill-test")
    run = workflow_step(api, queued["id"], "report")
    assert run["status"] == "succeeded"
    system = received[0]["messages"][0]["content"]
    assert "Cite only supplied observations." in system
    assert "do not grant tools" in system.lower()
    events = api.get(f"/api/runs/{run['id']}/events").json()
    verified = [item for item in events if item["event_type"] == "skills.verified"]
    assert verified and verified[0]["payload"]["skills"][0]["id"] == "daily-brief"
    current = verify_snapshots(run["parameters"]["skill_snapshots"])
    assert current[0]["sha256"] == run["parameters"]["skill_snapshots"][0]["sha256"]
    assert list_skills()[0].id == "daily-brief"
