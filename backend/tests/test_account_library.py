"""Library lineage must remain usable under the actual private account policy."""

from app.data_access import DataScope, ScopedSession
from app.db import control_session_factory, get_engine
from app.library import derived_artifact_ids
from app.models import Artifact
from test_account_private_api import accounts, private_app, upload  # noqa: F401


def test_lineage_filters_private_derived_artifacts_before_limit(accounts):  # noqa: F811
    _, alice, bob = accounts
    owner = alice.get("/api/auth").json()["user"]["id"]
    foreign = bob.get("/api/auth").json()["user"]["id"]
    source, _ = upload(alice, "red")
    other_source, _ = upload(bob, "blue")
    with control_session_factory()() as session:
        own = [
            Artifact(
                owner_id=owner,
                artifact_type="image",
                relative_path=f"artifacts/own-{index}.png",
                parent_artifact_ids=[source],
            )
            for index in range(2)
        ]
        session.add_all(own)
        session.flush()
        expected = {row.id for row in own}
        # Deliberately inconsistent control-plane fixture: a private foreign
        # child names the known source. It must not fill the source owner's page.
        session.add_all(
            Artifact(
                owner_id=foreign,
                artifact_type="image",
                relative_path=f"artifacts/foreign-{index}.png",
                parent_artifact_ids=[source],
            )
            for index in range(60)
        )
        session.commit()
        child = own[0].id
    response = alice.get(f"/api/artifacts/{source}/lineage")
    assert response.status_code == 200, response.text
    assert {row["id"] for row in response.json()["derived"]} == expected
    response = alice.get(f"/api/artifacts/{child}/lineage")
    assert [row["id"] for row in response.json()["sources"]] == [source]
    assert bob.get(f"/api/artifacts/{source}/lineage").status_code == 404
    assert alice.get(f"/api/artifacts/{other_source}/lineage").status_code == 404
    with ScopedSession(bind=get_engine(), scope=DataScope(owner)) as session:
        first = derived_artifact_ids(session, source, limit=1)
        assert len(first) == 1 and first[0] in expected
