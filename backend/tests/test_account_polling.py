"""Long-running owner-scoped polls must not accumulate ORM loader state."""

from app.models import Run
from sqlalchemy import inspect
from test_private_data_access import records, scoped
from test_private_data_access import users as users


def test_repeated_refresh_does_not_accumulate_inherited_owner_policies(users):
    _, alice, _ = users
    identifiers = records(alice)
    with scoped(alice) as session:
        run = session.get(Run, identifiers[2])
        initial = len(inspect(run).load_options)
        assert initial
        for _ in range(12):
            session.refresh(run)
            session.refresh(run.task, ["metadata_json"])
            session.commit()
            assert len(inspect(run).load_options) <= initial, "Owner policies grow on each refresh"
