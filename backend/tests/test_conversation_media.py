import io
from uuid import uuid4

import pytest
from app.api import app
from app.conversation_media import followup_action
from app.db import session_factory, utcnow
from app.engine import tick
from app.models import Artifact, Message, Run
from app.runs import transition
from app.state import RunStatus
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select


def completed_image(client, cid):
    response = client.post(
        f"/api/chat/conversations/{cid}/messages", json={"content": "Generate an image of a landscape"}
    )
    assert response.status_code == 202, response.text
    with session_factory()() as session:
        tick(session, "test-media-followup")
        producer = session.scalar(select(Run).where(Run.parent_run_id == response.json()["id"]))
        for status in [RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.SUCCEEDED]:
            transition(session, producer, status, event_type="test.transition")
        session.commit()
        producer_id = producer.id
    data = io.BytesIO()
    Image.new("RGB", (64, 64)).save(data, "PNG")
    uploaded = client.post(
        "/api/images/uploads", files={"file": ("result.png", data.getvalue(), "image/png")}
    ).json()
    with session_factory()() as session:
        session.get(Artifact, uploaded["id"]).run_id = producer_id
        session.commit()
    return uploaded["id"], producer_id


def conversation(client, mode="work"):
    r = client.post("/api/chat/conversations", json={"model": "test", "execution_mode": mode})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.parametrize(
    ("content", "action"),
    [
        ("Powiększ to", "image.upscale"),
        ("Describe it", "image.describe"),
        ("Opisz tę grafikę", "image.describe"),
        ("Co znajduje się na wygenerowanym zdjęciu? Nie twórz kolejnego obrazu.", "image.describe"),
        ("What is in the generated image? Do not create another image.", "image.describe"),
        ("What do you see in this photo?", "image.describe"),
        ("How many apples are in the previous picture?", "image.describe"),
        ("Jakiego koloru jest jabłko na wygenerowanym zdjęciu?", "image.describe"),
        ("Opisz wygenerowane zdjęcie.", "image.describe"),
        ("Describe the generated photograph.", "image.describe"),
        ("Powiększ tę grafikę", "image.upscale"),
        ("Edytuj tę grafikę: dodaj czerwone logo", "image.edit"),
        ("Upscale the previous image.", "image.upscale"),
        ("Ożyw ten obraz: spokojny ruch kamery", "video.generate"),
        ("Animate it into a 5 second video", "video.generate"),
        ("Zmień ten obraz: dodaj kapelusz", "image.edit"),
        ("Edit this image: add a red hat", "image.edit"),
        (
            "Zmień kolor roweru na niebieski. Zachowaj resztę obrazu i użyj poprzedniego zdjęcia jako źródła.",
            "image.edit",
        ),
        (
            "Zmień czerwony kwadrat na żółty w poprzednim załączonym obrazku. Zachowaj inne figury i wymiary. Utwórz nowy obraz, nie opis tekstowy.",
            "image.edit",
        ),
        ("Change the bicycle to blue in the previous image. Keep the background.", "image.edit"),
        ("Proszę zmień ten obraz na portret w zimowym ubraniu", "image.edit"),
        ('Edytuj ten obraz: "dodaj niebieski kapelusz"', "image.edit"),
    ],
)
@pytest.mark.parametrize("web_enabled", [False, True])
def test_followup_is_bound_to_visible_same_conversation_result(content, action, web_enabled):
    with TestClient(app) as client:
        cid = conversation(client)
        aid, producer = completed_image(client, cid)
        completed_image(client, conversation(client))
        web_preference = client.get("/api/chat/preferences").json()["web_search_enabled"]
        request = {
            "content": content,
            "web_search": {"enabled": web_enabled},
            "client_request_id": str(uuid4()),
            "conversation_id": cid,
            "expected_settings_version": 1,
        }
        response = client.post("/api/chat/turns", json=request)
        assert response.status_code == 202, response.text
        run = response.json()["run"]
        assert run["parameters"]["action"] == action
        assert run["parameters"]["image_artifact_ids"] == [aid]
        assert "external_ai" not in run["effective_permissions"]
        assert not run["parameters"]["web_search"]["enabled"]
        assert client.get("/api/chat/preferences").json()["web_search_enabled"] == web_preference
        view = client.get(f"/api/chat/conversations/{cid}").json()
        user = next(m for m in view["messages"] if m["id"] == response.json()["user_message_id"])
        assert user["metadata"]["conversation_reference"]["run_id"] == producer
        assert user["metadata"]["images"][0]["id"] == aid
        assert client.post("/api/chat/turns", json=request).json()["run"]["id"] == run["id"]


@pytest.mark.parametrize(
    "content",
    [
        "Jak zmienić kolor roweru w poprzednim zdjęciu?",
        "Explain how to change the bicycle in the previous image",
        "Do not change the bicycle in the previous image",
        "Zmień prompt, aby opisywał rower na poprzednim zdjęciu",
        "Zmień kod Pythona, aby wykrywał rower na poprzednim zdjęciu",
        "Change the documentation explaining the bicycle in the previous image",
        "> Zmień rower na niebieski na poprzednim zdjęciu",
        "```text\nChange the bicycle to blue in the previous image\n```",
        'Explain the instruction "Change the bicycle to blue in the previous image"',
        'Explain the question "What is in the generated image?"',
        '"Co znajduje się na wygenerowanym zdjęciu?"',
        "> What do you see in this photo?",
        "```text\nCo znajduje się na wygenerowanym zdjęciu?\n```",
        "What is the best way to edit the code for image processing?",
        "How can I generate a photograph?",
        "Co oznacza słowo fotografia?",
    ],
)
def test_image_mentions_in_advice_quotes_or_code_edits_do_not_select_pixels(content):
    assert followup_action(content) is None


@pytest.mark.parametrize("problem", ["trashed", "failed", "ambiguous"])
@pytest.mark.parametrize("content", ["Upscale it", "What do you see in the generated image?"])
def test_unavailable_or_ambiguous_latest_result_never_falls_back(problem, content):
    with TestClient(app) as client:
        cid = conversation(client)
        completed_image(client, cid)
        aid, producer = completed_image(client, cid)
        with session_factory()() as session:
            if problem == "trashed":
                session.get(Artifact, aid).trashed_at = utcnow()
            elif problem == "failed":
                session.get(Run, producer).status = "failed"
            else:
                a = session.get(Artifact, aid)
                session.add(
                    Artifact(
                        artifact_type="image",
                        mime_type="image/png",
                        relative_path=a.relative_path,
                        run_id=producer,
                    )
                )
            before = len(list(session.scalars(select(Run))))
            session.commit()
        r = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": content})
        assert r.status_code == 422, r.text
        with session_factory()() as session:
            assert len(list(session.scalars(select(Run)))) == before


def test_only_final_derived_image_is_selected_and_chat_uses_same_contract():
    with TestClient(app) as client:
        cid = conversation(client, "chat")
        aid, producer = completed_image(client, cid)
        with session_factory()() as session:
            a = session.get(Artifact, aid)
            derived = Artifact(
                artifact_type="image",
                mime_type="image/png",
                relative_path=a.relative_path,
                run_id=producer,
                parent_artifact_ids=[aid],
                metadata_json=a.metadata_json,
            )
            session.add(derived)
            session.flush()
            final = derived.id
            session.commit()
        r = client.post(f"/api/chat/conversations/{cid}/messages", json={"content": "Powiększ to"})
        assert r.status_code == 202, r.text
        assert r.json()["parameters"]["image_artifact_ids"] == [final]
        with session_factory()() as session:
            tick(session, "test-media-followup")
            child = session.scalar(select(Run).where(Run.parent_run_id == r.json()["id"]))
            assert child.parameters["mode"] == "upscale"
            assert child.parameters["parent_artifact_ids"] == [final]


def test_explicit_sources_are_never_replaced():
    with TestClient(app) as client:
        cid = conversation(client)
        old, _ = completed_image(client, cid)
        completed_image(client, cid)
        r = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Powiększ to", "image_artifact_ids": [old], "action": "image.upscale"},
        )
        assert r.status_code == 202
        assert r.json()["parameters"]["image_artifact_ids"] == [old]


def test_missing_result_rejects_without_creating_messages_or_receipts():
    with TestClient(app) as client:
        cid = conversation(client)
        r = client.post(
            "/api/chat/turns",
            json={
                "client_request_id": str(uuid4()),
                "conversation_id": cid,
                "expected_settings_version": 1,
                "content": "Upscale it",
            },
        )
        assert r.status_code == 422
        assert client.get(f"/api/chat/conversations/{cid}").json()["messages"] == []


@pytest.mark.parametrize(
    "text",
    [
        "Explain how to upscale this image",
        "Do not upscale it",
        "Can we discuss this image?",
        "Change this project: add login",
        "Animate my project",
        "Generate an image",
        "Upscale",
        "Edit this image",
    ],
)
def test_noncommands_never_acquire_previous_sources(text):
    assert followup_action(text) is None


@pytest.mark.parametrize(
    "web",
    [
        {"enabled": True, "query": "an explicit public topic"},
        {"enabled": True, "render_pages": True},
    ],
)
@pytest.mark.parametrize("content", ["Upscale it", "What do you see in the generated image?"])
def test_explicit_research_scope_does_not_acquire_a_previous_image(web, content):
    with TestClient(app) as client:
        cid = conversation(client)
        completed_image(client, cid)
        r = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": content, "web_search": web}
        )
        assert r.status_code == 202, r.text
        assert r.json()["parameters"]["action"] == "auto"
        assert r.json()["parameters"]["image_artifact_ids"] == []
        assert r.json()["parameters"]["web_search"] == web | ({"query": ""} if "query" not in web else {})


def test_disabled_saved_query_does_not_block_a_media_reference():
    with TestClient(app) as client:
        cid = conversation(client)
        aid, _ = completed_image(client, cid)
        r = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Upscale it", "web_search": {"enabled": False, "query": "old query"}},
        )
        assert r.status_code == 202, r.text
        assert r.json()["parameters"]["image_artifact_ids"] == [aid]


@pytest.mark.parametrize("has_old_image", [False, True])
def test_generic_description_after_text_does_not_acquire_an_old_image(has_old_image):
    with TestClient(app) as client:
        cid = conversation(client)
        if has_old_image:
            completed_image(client, cid)
        with session_factory()() as session:
            session.add(
                Message(
                    conversation_id=cid, role="assistant", content="A plain explanation of a text concept."
                )
            )
            session.commit()
        r = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Describe it", "web_search": {"enabled": True}},
        )
        assert r.status_code == 202, r.text
        assert (
            r.json()["parameters"]["action"] == "auto" and r.json()["parameters"]["image_artifact_ids"] == []
        )


@pytest.mark.parametrize("web_enabled", [False, True])
def test_failed_latest_generation_without_output_never_reuses_older_image(web_enabled):
    with TestClient(app) as client:
        cid = conversation(client)
        completed_image(client, cid)
        new = client.post(
            f"/api/chat/conversations/{cid}/messages", json={"content": "Generate an image of a mountain"}
        )
        assert new.status_code == 202, new.text
        with session_factory()() as session:
            assert tick(session, "failed-image-dispatch")
            producer = session.scalar(select(Run).where(Run.parent_run_id == new.json()["id"]))
            for status in [RunStatus.CLAIMED, RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.FAILED]:
                transition(session, producer, status, event_type="test.transition")
            session.commit()
            before = len(list(session.scalars(select(Run))))
        r = client.post(
            f"/api/chat/conversations/{cid}/messages",
            json={"content": "Upscale it", "web_search": {"enabled": web_enabled}},
        )
        assert r.status_code == 422 and "latest image task" in r.text, r.text
        with session_factory()() as session:
            assert len(list(session.scalars(select(Run)))) == before
