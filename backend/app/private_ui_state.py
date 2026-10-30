"""Non-secret, versioned operator policy; node keys belong only to the Runner."""

from copy import deepcopy

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.data_access import DataAccessError, ScopedSession
from app.models import Run, Setting

KEY = "private_ui_access"
DEFAULT = {"revision": 0, "enabled": False, "password_required": False}


def read(session=None, *, run=None):
    if session is None:
        from app.db import control_session_factory

        try:
            with control_session_factory()() as current:
                return read(current)
        except OperationalError:
            return dict(DEFAULT)
    if isinstance(session, ScopedSession):
        if run is not None:
            from app.private_access_accounts import check_run

            check_run(session, run)
        value = _fixed_value(session)
        if not session.scope.administrator and run is None:
            value.pop("pending_run_id", None)
        return value
    row = session.get(Setting, KEY)
    return dict(row.value) if row and isinstance(row.value, dict) else dict(DEFAULT)


def lock(session, *, run=None):
    if isinstance(session, ScopedSession):
        from app.private_access_accounts import authority

        authority(session, run=run, mutation=True)
        value = _fixed_value(session, locked=True)
        if value is None:
            try:
                with session.begin_nested():
                    session.connection().execute(
                        Setting.__table__.insert().values(key=KEY, value=dict(DEFAULT))
                    )
            except IntegrityError:
                pass
            value = _fixed_value(session, locked=True)
        return _Policy(session, run, value)
    row = session.get(Setting, KEY)
    if row is None:
        try:
            with session.begin_nested():
                session.add(Setting(key=KEY, value=dict(DEFAULT)))
                session.flush()
        except IntegrityError:
            pass
    session.execute(update(Setting).where(Setting.key == KEY).values(value=Setting.value))
    row = session.get(Setting, KEY, populate_existing=True)
    return row


def _fixed_value(session, *, locked=False):
    table = Setting.__table__
    query = select(table.c.value).where(table.c.key == KEY)
    if locked:
        query = query.with_for_update()
    value = session.connection().scalar(query)
    if value is None and locked:
        return None
    return deepcopy(value) if isinstance(value, dict) else dict(DEFAULT)


class _Policy:
    def __init__(self, session, run, value):
        self._session, self._run, self._value = session, run, value

    @property
    def value(self):
        return deepcopy(self._value)

    @value.setter
    def value(self, value):
        from app.private_access import validated_tailnet_origin
        from app.private_access_accounts import authority, check_run

        session = self._session
        revision = authority(session, run=self._run, mutation=True)
        if set(value) - {"revision", "enabled", "password_required", "pending_run_id", "origin", "node_id"}:
            raise ValueError("Unknown private access policy field")
        if type(value.get("revision")) is not int or value["revision"] < 0:
            raise ValueError("Invalid private access revision")
        if any(type(value.get(key)) is not bool for key in ("enabled", "password_required")):
            raise ValueError("Invalid private access policy")
        if value.get("origin") is not None:
            validated_tailnet_origin(value["origin"])
        if value.get("node_id") is not None and (
            not isinstance(value["node_id"], str) or not 1 <= len(value["node_id"]) <= 128
        ):
            raise ValueError("Invalid private device")
        run = self._run or session.get(Run, value.get("pending_run_id"))
        if run is None:
            raise DataAccessError("Private access operation is unavailable")
        check_run(session, run)
        if (
            value.get("pending_run_id") != run.id
            or value["revision"] != run.parameters.get("policy_revision")
            or revision != run.parameters.get("authority_revision")
            or _fixed_value(session, locked=True) != self._value
        ):
            raise ValueError("Private access policy changed; review the operation")
        operation = run.parameters["operation"]
        if session.scope.execution:
            if run.status != "running" or not run.metadata_json.get("dispatch_attempted"):
                raise ValueError("Only an inspected running operation can publish private access")
            expected = dict(self._value)
            if operation == "enable" and value != self._value and value.get("enabled"):
                selected = run.parameters["request"]
                expected.update(enabled=True, origin=selected["origin"], node_id=selected["node_id"])
            elif operation == "disable":
                expected.update(enabled=False, origin=None, node_id=None, password_required=False)
        else:
            # HTTP only queues an approved operation. It cannot publish an
            # enabled origin by borrowing that operation's policy capability.
            expected = {
                **self._value,
                "revision": self._value.get("revision", 0) + 1,
                "pending_run_id": run.id,
                "password_required": True,
            }
            if operation == "disable":
                expected.update(enabled=False, origin=None)
        if value != expected:
            raise ValueError("Private access policy does not match the approved operation stage")
        session.flush()
        table = Setting.__table__
        session.connection().execute(update(table).where(table.c.key == KEY).values(value=deepcopy(value)))
        self._value = deepcopy(value)


def operation_facts(session, policy):
    """Only fixed busy/inspection facts cross account ownership boundaries."""
    identity = policy.get("pending_run_id")
    if not identity:
        return {"busy": False, "needs_inspection": False}
    table = Run.__table__
    row = (
        session.connection()
        .execute(
            select(table.c.status, table.c.metadata["cleanup_requires_inspection"].as_boolean()).where(
                table.c.id == identity,
                table.c.executor_type == "private_access",
                table.c.capability == "system.private_access",
            )
        )
        .first()
    )
    if row is None:
        return {"busy": True, "needs_inspection": True}
    from app.state import ACTIVE

    return {"busy": row[0] in ACTIVE, "needs_inspection": row[1] is True}
