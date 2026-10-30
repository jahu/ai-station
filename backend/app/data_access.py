"""Explicit account-scoped ORM sessions; HTTP/worker cutover is a separate gate.

The scope is fixed for a session's lifetime. Account authentication and trusted
machine coordination use separate services, never a silent unscoped fallback.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, event, inspect, select
from sqlalchemy.orm import Session, with_loader_criteria

from app import models as m


class DataAccessError(PermissionError):
    pass


@dataclass(frozen=True)
class DataScope:
    user_id: str
    inspect_all: bool = False
    administrator: bool = False
    read_only: bool = False
    execution: bool = False
    session_id: str | None = None

    def __post_init__(self):
        if self.inspect_all:
            object.__setattr__(self, "read_only", True)


ROOTS = (
    m.Task,
    m.Run,
    m.Artifact,
    m.Conversation,
    m.Project,
    m.Agent,
    m.Approval,
    m.MemoryEntry,
    m.Connector,
    m.ChatProvider,
)
SHARED = (m.ModelFile, m.ModelDefinition, m.Runtime, m.RuntimeInstance, m.TelemetrySample)
ADMIN = (m.Setting, m.StationNode, m.WorkerRow)
ACCOUNTS = (m.User, m.UserSession, m.UserSetting, m.AccountEvent)

# Each inherited record is visible only through all of its private parents.
PARENTS = {
    m.ResourceLock: (("run_id", m.Run),),
    m.RunDependency: (("run_id", m.Run), ("prerequisite_id", m.Run)),
    m.RunEvent: (("run_id", m.Run),),
    m.Message: (("conversation_id", m.Conversation), ("run_id", m.Run)),
    m.ChatWorkContext: (("conversation_id", m.Conversation), ("task_id", m.Task)),
    m.ChatTurnRequest: (
        ("conversation_id", m.Conversation),
        ("task_id", m.Task),
        ("run_id", m.Run),
        ("user_message_id", m.Message),
    ),
    m.Worktree: (("project_id", m.Project), ("run_id", m.Run)),
    m.MemoryEmbedding: (("memory_id", m.MemoryEntry), ("source_run_id", m.Run)),
    m.Notice: (("agent_id", m.Agent), ("run_id", m.Run)),
    m.ConversationSummary: (
        ("conversation_id", m.Conversation),
        ("run_id", m.Run),
        ("memory_id", m.MemoryEntry),
        ("covered_message_id", m.Message),
    ),
    m.MarketObservation: (("agent_id", m.Agent), ("run_id", m.Run)),
    m.MarketAlert: (
        ("observation_id", m.MarketObservation),
        ("baseline_id", m.MarketObservation),
        ("run_id", m.Run),
        ("notice_id", m.Notice),
    ),
    m.EmailDelivery: (("run_id", m.Run), ("connector_id", m.Connector)),
}
REFERENCES = {
    m.Task: (("project_id", m.Project), ("conversation_id", m.Conversation), ("agent_id", m.Agent)),
    m.Run: (
        ("task_id", m.Task),
        ("project_id", m.Project),
        ("conversation_id", m.Conversation),
        ("agent_id", m.Agent),
        ("parent_run_id", m.Run),
    ),
    m.Artifact: (("run_id", m.Run), ("purge_run_id", m.Run)),
    m.Agent: (("project_id", m.Project),),
    m.Approval: (("run_id", m.Run),),
    m.MemoryEntry: (
        ("source_run_id", m.Run),
        ("source_conversation_id", m.Conversation),
        ("source_message_id", m.Message),
    ),
    m.Connector: (("last_run_id", m.Run),),
}


def _criterion(model, scope: DataScope):
    if model in ROOTS:
        return model.owner_id.is_not(None) if scope.inspect_all else model.owner_id == scope.user_id
    clauses = []
    for field, parent in PARENTS[model]:
        column = getattr(model, field)
        condition = column.in_(select(parent.id).where(_criterion(parent, scope)))
        clauses.append((column.is_(None) | condition) if column.nullable else condition)
    return and_(*clauses)


class ScopedSession(Session):
    def __init__(self, *args, scope: DataScope | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.__scope = scope

    @property
    def scope(self) -> DataScope:
        if self.__scope is None:
            raise DataAccessError("An authenticated data owner is required")
        return self.__scope

    def get(self, entity, ident, **kwargs):
        scope = self.scope
        row = super().get(entity, ident, **kwargs)
        if row is None:
            return None
        # Session.get may return from the identity map without executing SQL.
        # Do not let an externally attached instance bypass the read policy.
        if isinstance(row, m.Owned) or type(row) in PARENTS:
            try:
                owner = _owner(self, row)
            except DataAccessError:
                return None
            if owner != scope.user_id and not scope.inspect_all:
                return None
        if isinstance(row, m.User) and row.id != scope.user_id:
            return None
        if isinstance(row, (m.UserSession, m.UserSetting)) and row.user_id != scope.user_id:
            return None
        if isinstance(row, m.UserSetting) and row.key.startswith("auth."):
            return None
        return row


def data_session_for(principal, *, inspect_all: bool = False) -> ScopedSession:
    """HTTP service factory: recheck the device/account before granting a scope."""
    from app.accounts import _actor
    from app.db import control_session_factory, get_engine

    with control_session_factory()() as auth:
        user = _actor(auth, principal, admin=inspect_all)
        scope = DataScope(
            user.id,
            inspect_all,
            administrator=user.is_admin,
            read_only=inspect_all,
            session_id=principal.session_id,
        )
    return ScopedSession(bind=get_engine(), scope=scope, expire_on_commit=False)


def data_session_for_run(run_id: str, expected_owner: str) -> ScopedSession:
    """Worker-only factory; ownership comes from the frozen, claimed Run.

    This is not an HTTP lookup/impersonation operation. Administrative identity
    never grants an executor the ability to inspect every account's context.
    """
    from app.db import control_session_factory, get_engine

    with control_session_factory()() as queue:
        run = queue.get(m.Run, run_id)
        if run is None or run.owner_id is None or run.owner_id != expected_owner:
            raise DataAccessError("The execution owner does not match the Run")
        user = queue.get(m.User, run.owner_id)
        if user is None or not user.enabled or user.bootstrap_pending:
            raise DataAccessError("The execution account is disabled")
        scope = DataScope(user.id, execution=True)
    return ScopedSession(bind=get_engine(), scope=scope, expire_on_commit=False)


def private_for_update(session: Session, model, identity):
    """Refresh and lock one private root through the ordinary owner filter.

    Services compare the refreshed version before mutating ORM fields. Reference
    and ownership validation still run at flush; raw SQL/bulk writes stay denied.
    SQLite serializes the transaction with BEGIN IMMEDIATE; PostgreSQL uses the
    row lock. A cached stale identity never substitutes for the locked snapshot.
    """
    if model not in ROOTS:
        raise DataAccessError("Only a private root can be locked for mutation")
    if isinstance(session, ScopedSession) and session.scope.read_only:
        raise DataAccessError("Administrative inspection is read-only")
    return session.scalar(
        select(model).where(model.id == identity).with_for_update().execution_options(populate_existing=True)
    )


def accessible_run_id(row, identity):
    """Shared infrastructure cannot publish an inaccessible private provenance ID."""
    from sqlalchemy.orm import object_session

    from app.data_context import UNBOUND, current_data_scope

    if not identity:
        return None
    session = object_session(row)
    if isinstance(session, ScopedSession):
        return identity if session.get(m.Run, identity) is not None else None
    # Detached/global coordination records are not an owner-authorized lookup.
    # The transitional unbound service path retains its old projection.
    return identity if current_data_scope() is UNBOUND else None


@event.listens_for(ScopedSession, "do_orm_execute")
def _filter(execute):
    scope = execute.session.scope
    if not execute.is_orm_statement or not execute.is_select:
        raise DataAccessError("Use an owner-checked service for raw SQL and bulk changes")
    known = set(ROOTS) | set(PARENTS) | set(SHARED) | set(ADMIN) | set(ACCOUNTS)
    for mapper in execute.all_mappers:
        if mapper.class_ not in known:
            raise DataAccessError("No data ownership policy exists for this record")
        if mapper.class_ in ADMIN and not scope.administrator:
            raise DataAccessError("Machine administration requires administrator access")
    options = [
        with_loader_criteria(model, _criterion(model, scope), include_aliases=True)
        for model in (*ROOTS, *PARENTS)
    ]
    options.extend(
        [
            with_loader_criteria(m.User, m.User.id == scope.user_id, include_aliases=True),
            with_loader_criteria(m.UserSession, m.UserSession.user_id == scope.user_id, include_aliases=True),
            with_loader_criteria(
                m.UserSetting,
                and_(
                    m.UserSetting.user_id == scope.user_id,
                    ~m.UserSetting.key.startswith("auth.", autoescape=True),
                ),
                include_aliases=True,
            ),
            with_loader_criteria(
                m.AccountEvent, m.AccountEvent.subject_user_id == scope.user_id, include_aliases=True
            ),
        ]
    )
    execute.statement = execute.statement.options(*options)


def _owner(session: ScopedSession, row) -> str:
    if isinstance(row, m.Owned):
        if row.owner_id is None:
            raise DataAccessError("Ownerless records require administrative inspection")
        return row.owner_id
    owners = set()
    for field, parent in PARENTS.get(type(row), ()):
        value = getattr(row, field)
        if value is not None:
            target = session.get(parent, value)
            if target is None:
                raise DataAccessError("Referenced private record is unavailable")
            owners.add(_owner(session, target))
    if len(owners) != 1:
        raise DataAccessError("Private references must have the same owner")
    return owners.pop()


def _references(session: ScopedSession, row, owner: str) -> None:
    for field, parent in REFERENCES.get(type(row), ()):
        value = getattr(row, field)
        if value is not None:
            target = session.get(parent, value)
            if target is None or _owner(session, target) != owner:
                raise DataAccessError("Referenced private record is unavailable")
    if isinstance(row, m.Artifact):
        for identity in row.parent_artifact_ids or []:
            target = session.get(m.Artifact, identity)
            if target is None or target.owner_id != owner:
                raise DataAccessError("Source artifact is unavailable")
    if isinstance(row, m.MemoryEntry) and row.scope != "global":
        parent = {"conversation": m.Conversation, "agent": m.Agent, "project": m.Project}.get(row.scope)
        target = session.get(parent, row.scope_id) if parent else None
        if target is None or target.owner_id != owner:
            raise DataAccessError("Memory scope is unavailable")


@event.listens_for(ScopedSession, "before_flush")
def _check_changes(session: ScopedSession, _context, _instances):
    scope = session.scope
    if scope.read_only and (
        session.new or session.deleted or any(session.is_modified(row) for row in session.dirty)
    ):
        raise DataAccessError("Administrative inspection is read-only")
    for row in set(session.new) | set(session.dirty) | set(session.deleted):
        if isinstance(row, m.Owned):
            state = inspect(row)
            if row in session.new:
                if row.owner_id is None:
                    row.owner_id = scope.user_id
                elif row.owner_id != scope.user_id:
                    raise DataAccessError("New records must belong to the executing owner")
            elif state.attrs.owner_id.history.has_changes():
                raise DataAccessError("Private record ownership is immutable")
            owner = _owner(session, row)
            if owner != scope.user_id and not scope.inspect_all:
                raise DataAccessError("Private record is unavailable")
            _references(session, row, owner)
            if isinstance(row, (m.Connector, m.ChatProvider)):
                from app.secrets import validate_record_secret_ref

                try:
                    validate_record_secret_ref(row, row.secret_ref or "")
                except ValueError as exc:
                    raise DataAccessError(str(exc)) from exc
        elif type(row) in PARENTS:
            owner = _owner(session, row)
            if owner != scope.user_id and (row in session.new or not scope.inspect_all):
                raise DataAccessError("Private record is unavailable")
        elif isinstance(row, m.UserSetting):
            from app.personal_settings import KEYS

            state = inspect(row)
            if row.user_id != scope.user_id or row.key not in KEYS:
                raise DataAccessError("Personal setting is unavailable")
            if row not in session.new and (
                state.attrs.user_id.history.has_changes() or state.attrs.key.history.has_changes()
            ):
                raise DataAccessError("Personal setting ownership is immutable")
        elif (
            type(row) in ADMIN
            and scope.administrator
            or type(row) in SHARED
            and (scope.administrator or scope.execution)
        ):
            # The authenticated operator may edit typed machine configuration.
            # Execution scopes never carry this administrative capability.
            continue
        else:
            if isinstance(row, m.RuntimeInstance):
                from app.runtime_coordination import consume_runtime_intent, consume_runtime_stop

                if consume_runtime_intent(session, row) or consume_runtime_stop(session, row):
                    continue
            # Authentication/admin services have their own explicit gates;
            # ordinary task execution cannot mutate identities or machine state.
            raise DataAccessError("Use the account or machine administration service")
