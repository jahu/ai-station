"""Real ReAct/Run engine, isolated accounts and fake media; no inference qualification."""

import json
from copy import deepcopy
from datetime import timedelta

import pytest
from app.assistant_controller import controller_results, missing_outcomes
from app.assistant_controller_tools import available_tools, subtree
from app.data_access import DataScope, ScopedSession
from app.db import control_session_factory, get_engine, utcnow
from app.engine import tick
from app.local_provider import LocalChatProvider
from app.models import Run, StudioMaterial, StudioRevision
from app.recovery import recover_stale
from app.runs import claim_next
from app.studio_assistant import child_tasks
from app.task_control import cancel_task
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_assistant_controller import submit
from test_creative_projects import create
from test_studio_audio_production import generators as generators
from test_studio_materials import board
from test_studio_production import movie as movie
from test_studio_render import ready as ready


@pytest.fixture
def director(monkeypatch):
    state = {
        "studio": {"format": "film", "aspect": "landscape", "audio": "silent"},
        "plans": [],
        "contexts": [],
    }
    monkeypatch.setattr(LocalChatProvider, "models", lambda _: ["test-model"])

    async def stream(self, **params):
        messages = params["messages"]
        first = messages[0]["content"]
        if first.startswith("Infer the user's requested outcomes"):
            state["contexts"].append(json.loads(messages[1]["content"]))
            yield json.dumps(
                {
                    "reason": "A complete edited film",
                    "immediate": state.get("immediate")
                    or [
                        {
                            "kind": "studio_material",
                            "description": "An edited explanatory film",
                            "studio": state["studio"],
                            **state.get("outcome", {}),
                        }
                    ],
                    "automations": [],
                }
            )
        elif first.startswith("You are the director"):
            context = json.loads(messages[1]["content"])
            state["plans"].append(context)
            audio = context["options"]["audio"]
            if state.get("revise_from_parent") and context.get("prior_storyboard"):
                revised = deepcopy(context["prior_storyboard"])
                for visual in context.get("prior_visuals", []):
                    shot = revised["scenes"][visual["scene"]]
                    shot.update(
                        visual_kind="library",
                        source_artifact_id=visual["artifact_id"],
                        reuse_scene=None,
                        reference_artifact_ids=[],
                    )
                revised["title"] = "A revised prism film"
                revised["scenes"][0]["title"] = "Look at it differently"
                yield json.dumps(revised)
                return
            yield json.dumps(
                board(
                    audio,
                    scenes=[
                        {
                            "purpose": "An opening visual",
                            "duration_frames": 150,
                            "visual_kind": "image",
                            "visual_brief": "A prism lit by a narrow beam.",
                            "narration": "A small change reveals a pattern."
                            if audio in {"voice", "voice_music"}
                            else "",
                        }
                    ],
                )
            )
        elif first.startswith("You are the Studio narration editor"):
            state.setdefault("narration_edits", []).append(messages)
            yield json.dumps({"lines": [{"scene": 0, "text": state.get("repair_text", "Still short.")}]})
        else:
            current = next(
                m["content"]
                for m in messages
                if m["content"].startswith("CURRENT REQUEST AND AVAILABLE STATE:")
            )
            context = json.loads(current.split("\n", 1)[1])
            state.setdefault("react_states", []).append(context)
            if context.get("missing_outcomes") and "Tool Name: studio_produce" not in first:
                if state.get("missing_source_question"):
                    yield (
                        "Thought: The prior source changed; confirm the current input.\nAction: ask_user\nAction Input: "
                        + json.dumps({"question": state["missing_source_question"]})
                    )
                else:
                    yield "Thought: Planning exhausted its corrections; preserve the draft.\nAnswer: The local model could not meet the requested script limits; the draft and its error remain available."
            elif context.get("missing_outcomes"):
                args = {
                    "instruction": "Explain a prism with an actual visual and the requested sound",
                    "title": "A prism film",
                }
                eligible = [o for o in context["missing_outcomes"] if not o.get("studio_planning_exhausted")]
                if eligible:
                    args["outcome_index"] = eligible[0]["outcome_index"]
                if state.get("presenter_reference"):
                    args["presenter_reference"] = state["presenter_reference"]
                yield (
                    "Thought: Produce the requested complete material.\nAction: studio_produce\nAction Input: "
                    + json.dumps(args)
                )
            else:
                assert "step:1:video:1" in json.dumps(messages)
                assert context["missing_outcomes"] == []
                yield "Thought: The complete film is verified.\nAnswer: Your complete film is ready."

    monkeypatch.setattr(LocalChatProvider, "stream", stream)
    return state


def advance(movie, count=100):
    # Fresh session/worker identities exercise persisted coordination, not a
    # retained framework agent or Python continuation.
    for i in range(count):
        with control_session_factory()() as db:
            if tick(db, f"studio-chat-{i}", executors=movie) is None:
                break


def owned(api):
    return ScopedSession(
        bind=get_engine(), scope=DataScope(api.get("/api/auth").json()["user"]["id"]), expire_on_commit=False
    )


@pytest.mark.parametrize("audio", ["silent", "music", "voice", "voice_music"])
@pytest.mark.parametrize("legacy", [False, True])
def test_real_react_composes_final_film_and_preserves_audio_policy(accounts, director, movie, audio, legacy):
    _, alice, bob = accounts
    director["studio"]["audio"] = audio
    result = submit(alice, "Make a complete film explaining a prism")
    if legacy:
        with owned(alice) as db:
            root = db.get(Run, result["run"]["id"])
            root.parameters = {
                k: v for k, v in root.parameters.items() if k != "controller_studio_timing_policy"
            }
            db.commit()
    advance(movie)
    with owned(alice) as db:
        root = db.get(Run, result["run"]["id"])
        assert root.status == "succeeded", [
            (r.executor_type, r.status, r.error_message) for r in db.scalars(select(Run))
        ]
        step = root.metadata_json["controller_steps"][0]
        assert step["tool"] == "studio.produce" and step["observation"]["status"] == "succeeded"
        assert step["observation"]["produced_types"] == ["video"]
        assert missing_outcomes([step["observation"]], root.metadata_json["controller_outcomes"]) == []
        wrapper = db.get(Run, step["run_id"])
        assert len(subtree(db, root, wrapper.id)) == 1
        assert len(child_tasks(db, wrapper)) == 2
        assert wrapper.parameters.get("timing_policy") == (None if legacy else "fit")
        produced = next(primary for kind, primary in child_tasks(db, wrapper) if kind == "production")
        assert produced.parameters["request"].get("timing_policy") == (None if legacy else "fit")
        public = controller_results(db, root)
        assert len(public["artifacts"]) == 1 and public["artifacts"][0]["type"] == "video"
        assert not any(a["type"] in {"audio", "image", "json"} for a in public["artifacts"])
        material = db.get(StudioMaterial, wrapper.metadata_json["studio_material_id"])
        assert material.creative_project_id is None and material.options["audio"] == audio
        revisions = list(db.scalars(select(StudioRevision).where(StudioRevision.material_id == material.id)))
        assert all(r.options["audio"] == audio for r in revisions)
        material_id = material.id
    assert bob.get("/api/studio/materials/" + material_id).status_code == 404
    assert len(director["plans"]) == 1


def test_brand_selection_is_semantic_alias_frozen_before_later_edits(accounts, director, movie):
    _, alice, bob = accounts
    first = create(
        alice,
        name="Northwind",
        aliases=["northwind.example"],
        identity={"colors": ["#123456"], "tone": "Calm"},
    )
    create(alice, name="Personal identity", identity={"colors": ["#FF2211"], "tone": "Bold"})
    create(bob, name="Not visible")
    director["studio"] = {
        "project": "brand:" + first["id"],
        "project_resolution": "selected",
        "format": "presentation",
        "aspect": "landscape",
        "audio": "silent",
    }
    result = submit(alice, "Create a presentation for northwind.example, without sound")
    # Catalog is frozen on submission, even before the first intent inference.
    with owned(alice) as db:
        from app.models import CreativeProject

        project = db.get(CreativeProject, first["id"])
        project.identity = {**project.identity, "tone": "A later tone"}
        db.commit()
    advance(movie)
    assert len(director["plans"]) == 1
    planned = director["plans"][0]
    assert planned["project_snapshot"]["name"] == "Northwind"
    assert planned["project_snapshot"]["identity"]["tone"] == "Calm"
    assert planned["project_snapshot"]["identity"]["colors"] == ["#123456"]
    assert planned["options"]["aspect"] == "landscape" and planned["options"]["audio"] == "silent"
    names = {p["name"] for p in director["contexts"][0]["creative_projects"].values()}
    assert names == {"Northwind", "Personal identity"}
    with owned(alice) as db:
        assert db.get(Run, result["run"]["id"]).status == "succeeded"


def test_stop_forwards_owned_planning_task_and_does_not_publish_production(accounts, director, movie):
    _, alice, _ = accounts
    result = submit(alice, "Make an edited film")
    # controller, inference, dispatch, wrapper -> waiting on director
    advance(movie, count=4)
    with owned(alice) as db:
        root = db.get(Run, result["run"]["id"])
        wrapper = db.scalar(select(Run).where(Run.executor_type == "assistant_studio"))
        assert wrapper.status == "waiting_for_tool"
        kids = child_tasks(db, wrapper)
        assert len(kids) == 1 and kids[0][0] == "plan"
        cancel_task(db, root.task)
        db.commit()
        assert all(
            r.status in {"canceled", "cancel_requested"}
            for r in db.scalars(select(Run).where(Run.task_id == kids[0][1].task_id))
        )
    advance(movie)
    assert not director["plans"]
    with owned(alice) as db:
        wrapper = db.get(Run, wrapper.id)
        assert wrapper.status == "canceled" and len(child_tasks(db, wrapper)) == 1


def test_interrupted_queue_publication_recovers_without_repeating_media(accounts, director, movie):
    _, alice, _ = accounts
    submit(alice, "Make an edited film")
    advance(movie, count=3)
    with control_session_factory()() as db:
        wrapper = claim_next(db, "disappeared-worker")
        assert wrapper.executor_type == "assistant_studio"
        wrapper.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with control_session_factory()() as db:
        assert wrapper.id in recover_stale(db)
        db.commit()
    advance(movie)
    assert len(director["plans"]) == 1
    with owned(alice) as db:
        wrapper = db.get(Run, wrapper.id)
        assert wrapper.status == "succeeded" and len(child_tasks(db, wrapper)) == 2


def test_completed_plan_or_raw_clip_cannot_fulfill_another_branded_material():
    outcomes = [
        {"kind": "studio_material", "count": 1, "description": str(i), "studio": {}} for i in range(2)
    ]
    observed = [
        {
            "tool": "studio.produce",
            "status": "succeeded",
            "produced_types": ["video"],
            "studio_outcome_index": 1,
        }
    ]
    assert [p["outcome_index"] for p in missing_outcomes(observed, outcomes)] == [0]
    assert len(missing_outcomes([{**observed[0], "produced_types": ["json"]}], outcomes)) == 2
    assert len(missing_outcomes([{**observed[0], "tool": "video.generate"}], outcomes)) == 2
    assert "studio.produce" not in available_tools(
        {"controller_provider": {"location": "external"}, "controller_studio_policy": "studio-v1"}
    )
    assert "studio.produce" not in available_tools({"controller_provider": {"location": "local"}})


def test_stop_during_production_reaches_capability_tasks_without_canceling_unrelated_work(
    accounts, director, movie
):
    from app.runs import create_run, create_task
    from app.studio_production import children

    _, alice, _ = accounts
    result = submit(alice, "Make a film")
    found = False
    for _ in range(12):
        advance(movie, count=1)
        with owned(alice) as db:
            wrapper = db.scalar(select(Run).where(Run.executor_type == "assistant_studio"))
            production = (
                next((r for k, r in child_tasks(db, wrapper) if k == "production"), None) if wrapper else None
            )
            if production and children(db, production):
                found = True
                root = db.get(Run, result["run"]["id"])
                step = root.metadata_json["controller_steps"][0]
                from app.assistant_controller_tools import observation

                active, observed = observation(db, root, step)
                assert active == [wrapper] and observed is None  # director/visuals are not a final film
                task = create_task(db, title="Unrelated", prompt="An unrelated task", capability="test")
                other = create_run(db, task, run_type="test", capability="test", executor_type="fake")
                cancel_task(db, root.task)
                db.commit()
                assert other.status == "queued" and not task.metadata_json.get("stop_requested_at")
                for child in children(db, production):
                    assert child.metadata_json.get("stop_requested_at")
                    assert all(
                        r.status in {"canceled", "cancel_requested", "succeeded"}
                        for r in db.scalars(select(Run).where(Run.task_id == child.id))
                    )
                break
    assert found


def test_failed_final_render_remains_unfulfilled_without_substituting_a_storyboard(accounts, director, movie):
    class FailedRender:
        def execute(self, session, run):
            raise ValueError("Synthetic final render failure")

    _, alice, _ = accounts
    result = submit(alice, "Make a complete film")
    advance({**movie, "motion_render": FailedRender()})
    with owned(alice) as db:
        root = db.get(Run, result["run"]["id"])
        step = root.metadata_json["controller_steps"][0]
        assert step["observation"]["status"] == "failed"
        assert "Synthetic final render failure" in step["observation"]["errors"][0]["error"]
        assert step["observation"]["artifacts"] == []
        assert missing_outcomes([step["observation"]], root.metadata_json["controller_outcomes"])
        assert controller_results(db, root)["artifacts"] == []
        assert len(director["plans"]) == 1


def test_conversation_remains_readable_when_its_final_film_is_moved_to_trash(accounts, director, movie):
    from app.models import Artifact

    _, alice, _ = accounts
    result = submit(alice, "Make a complete film")
    advance(movie)
    with owned(alice) as db:
        root = db.get(Run, result["run"]["id"])
        assert root.status == "succeeded"
        published = controller_results(db, root)
        output = db.get(Artifact, published["artifacts"][0]["id"])
        output.trashed_at = utcnow()
        db.commit()
        historical = controller_results(db, root)
        assert historical["artifacts"] == []
        assert historical["controller_steps"][0]["result"]["studio_material_id"]


def test_stop_rejects_a_forged_child_task_registry(accounts, director, movie):
    from app.runs import create_run, create_task

    _, alice, _ = accounts
    result = submit(alice, "Make a film")
    advance(movie, count=4)
    with owned(alice) as db:
        root = db.get(Run, result["run"]["id"])
        wrapper = db.scalar(select(Run).where(Run.executor_type == "assistant_studio"))
        task = create_task(
            db,
            title="Other task",
            prompt="Unrelated",
            capability="test",
            conversation_id=wrapper.conversation_id,
        )
        other = create_run(db, task, run_type="planning", capability="test", executor_type="studio_director")
        wrapper.metadata_json = {
            **wrapper.metadata_json,
            "studio_assistant_children": [{"kind": "plan", "task_id": task.id, "run_id": other.id}],
        }
        with pytest.raises(ValueError, match="ownership"):
            child_tasks(db, wrapper)
        with pytest.raises(ValueError, match="ownership"):
            cancel_task(db, root.task)
        assert other.status == "queued" and not task.metadata_json.get("stop_requested_at")
        db.rollback()


@pytest.mark.parametrize("stuck", [False, True])
def test_cold_renderer_check_waits_durably_without_replanning_or_duplicating_production(
    accounts, director, movie, monkeypatch, stuck
):
    from app.resources import RESOURCE_WAIT_KEY
    from app.studio_render import RAM_MIB

    _, alice, _ = accounts
    status = {"available": False, "readiness": "checking", "reason": "Checking the isolated renderer"}
    monkeypatch.setattr("app.studio_render.capabilities", lambda: dict(status))
    result = submit(alice, "Make a complete film")
    advance(movie)
    with owned(alice) as db:
        wrapper = db.scalar(select(Run).where(Run.executor_type == "assistant_studio"))
        assert wrapper.status == "waiting_for_tool"
        assert wrapper.worker_id is None and wrapper.lease_expires_at is None
        assert wrapper.metadata_json.get(RESOURCE_WAIT_KEY)
        assert len(child_tasks(db, wrapper)) == 1
        assert len(director["plans"]) == 1
        if stuck:
            wrapper.metadata_json = {
                **wrapper.metadata_json,
                "studio_renderer_check_started_at": (utcnow() - timedelta(minutes=3)).isoformat(),
                RESOURCE_WAIT_KEY: (utcnow() - timedelta(seconds=1)).isoformat(),
            }
        else:
            status.update(available=True, ram_mib=RAM_MIB, observation="a" * 64)
            wrapper.metadata_json = {
                **wrapper.metadata_json,
                RESOURCE_WAIT_KEY: (utcnow() - timedelta(seconds=1)).isoformat(),
            }
        db.commit()
        identity = wrapper.id
    advance(movie)
    with owned(alice) as db:
        wrapper = db.get(Run, identity)
        assert len(director["plans"]) == 1
        if stuck:
            assert wrapper.status == "failed" and "verification did not finish" in wrapper.error_message
            assert len(child_tasks(db, wrapper)) == 1
        else:
            assert wrapper.status == "succeeded", wrapper.error_message
            assert len(child_tasks(db, wrapper)) == 2
            assert db.get(Run, result["run"]["id"]).status == "succeeded"


def test_spoken_word_limits_survive_semantic_intent_to_complete_production(accounts, director, movie):
    _, alice, _ = accounts
    director["studio"].update(audio="voice", narration_words={"minimum": 6, "maximum": 6})
    result = submit(alice, "Create a complete film with exactly six spoken words")
    advance(movie)
    with owned(alice) as db:
        root = db.get(Run, result["run"]["id"])
        assert root.status == "succeeded"
        assert root.metadata_json["controller_outcomes"][0]["studio"]["narration_words"] == {
            "minimum": 6,
            "maximum": 6,
        }
        wrapper = db.get(Run, root.metadata_json["controller_steps"][0]["run_id"])
        material = db.get(StudioMaterial, wrapper.metadata_json["studio_material_id"])
        assert material.options["narration_words"] == {"minimum": 6, "maximum": 6}
        revisions = list(db.scalars(select(StudioRevision).where(StudioRevision.material_id == material.id)))
        assert revisions and all(
            r.options["narration_words"] == {"minimum": 6, "maximum": 6} for r in revisions
        )
        assert controller_results(db, root)["artifacts"][0]["type"] == "video"
    assert director["plans"][0]["options"]["narration_words"] == {"minimum": 6, "maximum": 6}


def test_exhausted_word_repairs_do_not_create_more_materials_in_the_same_turn(accounts, director, movie):
    _, alice, _ = accounts
    director["studio"].update(audio="voice", narration_words={"minimum": 20, "maximum": 20})
    result = submit(alice, "Make a complete film with exactly twenty spoken words")
    advance(movie)
    with owned(alice) as db:
        root = db.get(Run, result["run"]["id"])
        attempts = [s for s in root.metadata_json["controller_steps"] if s["tool"] == "studio.produce"]
        assert len(attempts) == 1 and attempts[0]["observation"]["studio_attempt_exhausted"] is True
        assert len(list(db.scalars(select(StudioMaterial)))) == 1
        assert controller_results(db, root)["artifacts"] == []
        assert missing_outcomes([attempts[0]["observation"]], root.metadata_json["controller_outcomes"])
        from app.studio_assistant import request_parameters

        with pytest.raises(ValueError, match="exhausted"):
            request_parameters(db, root, {"instruction": "A different paraphrase of the same failed task"})
    assert len(director["plans"]) == 1 and len(director["narration_edits"]) == 2
    assert director["react_states"][-1]["missing_outcomes"][0]["studio_planning_exhausted"] is True


def test_exhausted_plan_does_not_block_a_separately_requested_material(accounts, director, movie):
    _, alice, _ = accounts
    director["immediate"] = [
        {
            "kind": "studio_material",
            "description": "A twenty-word film",
            "studio": {"audio": "voice", "narration_words": {"minimum": 20, "maximum": 20}},
        },
        {"kind": "studio_material", "description": "A separate short film", "studio": {"audio": "voice"}},
    ]
    result = submit(alice, "Make two separate films, the first with twenty spoken words")
    advance(movie)
    with owned(alice) as db:
        root = db.get(Run, result["run"]["id"])
        attempts = [
            s["observation"] for s in root.metadata_json["controller_steps"] if s["tool"] == "studio.produce"
        ]
        assert [(o["studio_outcome_index"], o["status"]) for o in attempts] == [
            (0, "failed"),
            (1, "succeeded"),
        ]
        assert attempts[0]["studio_attempt_exhausted"] is True
        assert "studio_attempt_exhausted" not in attempts[1]
        assert len(list(db.scalars(select(StudioMaterial)))) == 2
        assert len(controller_results(db, root)["artifacts"]) == 1
        assert [
            o["outcome_index"] for o in missing_outcomes(attempts, root.metadata_json["controller_outcomes"])
        ] == [0]
