import json

import pytest
from app.assistant_intents import AutomationSchedule, IntentPlan, validate_plan


def test_future_work_is_not_counted_as_immediate_images():
    plan = IntentPlan.model_validate(
        {
            "reason": "One change then recurrence",
            "immediate": [
                {
                    "kind": "image",
                    "description": "A blue cabinet",
                    "reference_mode": "provided",
                    "source_inputs": ["input:image:1"],
                }
            ],
            "automations": [
                {
                    "goal": "New cabinet settings",
                    "media_kind": "image",
                    "image_source": "latest_result",
                    "schedule": {"trigger": "interval", "interval_seconds": 900},
                }
            ],
        }
    )
    outcomes = plan.canonical().outcomes
    assert [(item.kind, item.count) for item in outcomes] == [("image", 1), ("agent_draft", 1)]
    assert outcomes[1].automation["schedule"]["interval_seconds"] == 900


@pytest.mark.parametrize(
    "values",
    [
        {"trigger": "interval"},
        {"trigger": "manual", "interval_seconds": 900},
        {"trigger": "interval", "interval_seconds": True},
        {"trigger": "datetime", "run_at": "2026-11-06T12:00:00"},
        {"trigger": "cron", "cron_expr": "nonsense"},
    ],
)
def test_invalid_or_ambiguous_schedule_is_rejected(values):
    with pytest.raises(ValueError):
        AutomationSchedule.model_validate(values)


def test_only_current_owned_reference_aliases_can_enter_future_scope():
    value = {
        "reason": "Recurring view",
        "immediate": [],
        "automations": [
            {
                "goal": "A new view",
                "media_kind": "image",
                "image_source": "supplied",
                "source_images": ["invented-image"],
            }
        ],
    }
    with pytest.raises(ValueError, match="supplied image aliases"):
        validate_plan(json.dumps(value), {"inputs_and_results": []})


def test_planning_keeps_the_current_request_after_history_and_marks_reference_data():
    from app.assistant_intents import planning_messages

    context = {
        "instruction": "Prepare only a recurring agent instead",
        "recent_context": [
            {"role": "user", "content": "Make an image"},
            {"role": "assistant", "content": "Which setting?"},
        ],
        "inputs_and_results": [{"alias": "previous:image:1", "type": "image"}],
    }
    messages = planning_messages(context)
    assert messages[-3:-1] == context["recent_context"]
    current = json.loads(messages[-1]["content"])
    assert current["instruction"] == context["instruction"]
    reference = json.loads(messages[1]["content"])
    assert "instruction" not in reference and "recent_context" not in reference
    assert reference["available_inputs"][0]["alias"] == "previous:image:1"
    assert "Read-only" in reference["context_role"]


def test_planning_describes_working_deliverables_and_available_affordances():
    import json

    from app.assistant_intents import PLANNING_SYSTEM, planning_messages

    tools = {"project.create_code": {"description": "Create a new owned implementation"}}
    messages = planning_messages(
        {"instruction": "Build a new version from this public source", "tools": tools}
    )
    assert json.loads(messages[1]["content"])["available_tools"] == tools
    assert "working deliverables" in PLANNING_SYSTEM and "design proposal" in PLANNING_SYSTEM
    assert "project/local_changes/files" in PLANNING_SYSTEM
    assert json.loads(messages[-1]["content"])["instruction"] == "Build a new version from this public source"
