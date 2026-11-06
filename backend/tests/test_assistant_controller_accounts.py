"""The real private worker/API path owns every controller and capability Task."""

from app.db import control_session_factory
from app.engine import tick
from app.models import Run
from sqlalchemy import select
from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_assistant_controller import finish, submit, tool
from test_assistant_controller import model as model
from test_images import bridge as bridge
from test_images import upload


def test_private_controller_keeps_capability_tasks_and_outputs_with_the_requesting_member(
    accounts, model, bridge
):
    _, alice, bob = accounts
    model["outcomes"][0].update(reference_mode="provided", source_inputs=["input:image:1"])
    model["decisions"] = [
        tool("image.recompose", instruction="Move the wardrobe into a garden", images=["input:image:1"]),
        finish(1),
    ]
    result = submit(alice, "A new version in a garden", image_artifact_ids=[upload(alice)["id"]])
    for index in range(30):
        with control_session_factory()() as db:
            if tick(db, "private-controller-" + str(index)) is None:
                break
    with control_session_factory()() as db:
        root = db.get(Run, result["run"]["id"])
        assert root.status == "succeeded", root.error_message
        graph = list(db.scalars(select(Run).where(Run.conversation_id == root.conversation_id)))
        assert len({row.task_id for row in graph}) == 2
        assert all(row.owner_id == root.owner_id for row in graph)
    path = "/api/chat/conversations/" + result["conversation_id"]
    own = alice.get(path)
    assert own.status_code == 200, own.text
    assert bob.get(path).status_code == 404
    assert bob.get("/api/runs/" + result["run"]["id"]).status_code == 404
    assert not bob.get("/api/artifacts").json()
    assert own.json()["messages"][-1]["controller_steps"][0]["status"] == "succeeded"
    assert len(own.json()["messages"]) == 2
