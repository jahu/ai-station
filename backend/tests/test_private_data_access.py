"""Repository boundaries only; not a claim of complete HTTP/worker isolation."""

from uuid import uuid4

import pytest
from app import models as m
from app.accounts import bootstrap_admin, create_user, login
from app.data_access import DataAccessError, DataScope, ScopedSession
from app.db import get_engine
from app.memory import search_memory, upsert_memory
from app.models import (
    Artifact,
    Conversation,
    MemoryEntry,
    Message,
    Project,
    Run,
    RunDependency,
    RunEvent,
    Setting,
    Task,
    User,
)
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import aliased


@pytest.fixture
def users(session):
    owner = bootstrap_admin(session, "Owner", "synthetic owner password", local_setup=True)
    device = login(session, "Owner", "synthetic owner password")
    alice = create_user(session, device.principal, "Alice", "synthetic alice password")
    bob = create_user(session, device.principal, "Bob", "synthetic bob password")
    session.commit()
    return owner.id, alice.id, bob.id


def scoped(user_id, *, inspect_all=False):
    return ScopedSession(bind=get_engine(), scope=DataScope(user_id, inspect_all), expire_on_commit=False)


def records(user_id):
    with scoped(user_id) as current:
        conversation = Conversation(title="Private conversation")
        current.add(conversation)
        current.flush()
        task = Task(title="Private task", conversation_id=conversation.id)
        current.add(task)
        current.flush()
        run = Run(task_id=task.id, conversation_id=conversation.id)
        current.add(run)
        current.flush()
        current.add(
            Message(conversation_id=conversation.id, role="user", content="Private prompt", run_id=run.id)
        )
        current.add(RunEvent(run_id=run.id, sequence=1, event_type="test", payload={"text": "private"}))
        artifact = Artifact(artifact_type="text", relative_path="artifacts/synthetic.txt", run_id=run.id)
        current.add(artifact)
        current.commit()
        return conversation.id, task.id, run.id, artifact.id


def test_missing_scope_fails_closed_for_list_lookup_and_write(users):
    with ScopedSession(bind=get_engine()) as current:
        with pytest.raises(DataAccessError, match="authenticated data owner"):
            current.scalars(select(Task)).all()
        with pytest.raises(DataAccessError):
            current.get(Task, str(uuid4()))
        current.add(Conversation())
        with pytest.raises(DataAccessError):
            current.flush()


def test_lists_lookup_counts_and_aliases_are_owner_scoped(users):
    _, alice, bob = users
    first, second = records(alice), records(bob)
    with scoped(alice) as current:
        assert [row.id for row in current.scalars(select(Task))] == [first[1]]
        assert current.scalar(select(func.count(Task.id))) == 1
        assert current.get(Task, second[1]) is None
        assert current.get(Artifact, second[3]) is None
        other = aliased(Run)
        assert [row.id for row in current.scalars(select(other))] == [first[2]]
        assert current.get(Task, first[1]).owner_id == alice


def test_relationships_and_direct_child_reads_cannot_escape_the_parent(users):
    _, alice, bob = users
    first, second = records(alice), records(bob)
    with scoped(alice) as current:
        assert len(current.get(Conversation, first[0]).messages) == 1
        assert [row.run_id for row in current.scalars(select(RunEvent))] == [first[2]]
        assert [row.conversation_id for row in current.scalars(select(Message))] == [first[0]]
        assert current.scalar(select(RunEvent).where(RunEvent.run_id == second[2])) is None
        assert len(current.get(Run, first[2]).events) == 1


def test_admin_can_inspect_all_owned_records_but_ownerless_records_are_quarantined(session, users):
    admin, alice, bob = users
    records(alice)
    records(bob)
    session.add(Task(title="Quarantined transitional record"))
    session.commit()
    with scoped(admin, inspect_all=True) as current:
        assert current.scalar(select(func.count(Task.id))) == 2
        assert current.scalar(select(func.count(Message.id))) == 2
    # Execution does not inherit the owner's administrative inspection right.
    with scoped(admin) as current:
        assert current.scalar(select(func.count(Task.id))) == 0


def test_new_records_use_frozen_owner_and_reassignment_is_rejected(users):
    _, alice, bob = users
    with scoped(alice) as current:
        task = Task(title="Owned")
        current.add(task)
        current.commit()
        assert task.owner_id == alice
        task.owner_id = bob
        with pytest.raises(DataAccessError, match="immutable"):
            current.commit()
        current.rollback()
        task = current.get(Task, task.id)
        assert task.owner_id == alice


def test_explicit_foreign_owner_cannot_be_smuggled_into_a_new_record(users):
    _, alice, bob = users
    with scoped(alice) as current:
        current.add(Task(title="Illegal", owner_id=bob))
        with pytest.raises(DataAccessError, match="executing owner"):
            current.commit()


def test_foreign_project_and_parent_run_references_are_rejected(users):
    _, alice, bob = users
    with scoped(bob) as current:
        project = Project(name="B project", repo_path="/synthetic/project")
        current.add(project)
        current.commit()
        project_id = project.id
    second = records(bob)
    with scoped(alice) as current:
        current.add(Task(title="Illegal reference", project_id=project_id))
        with pytest.raises(DataAccessError, match="unavailable"):
            current.flush()
        current.rollback()
        task = Task(title="Owned")
        current.add(task)
        current.flush()
        current.add(Run(task_id=task.id, parent_run_id=second[2]))
        with pytest.raises(DataAccessError, match="unavailable"):
            current.flush()


def test_admin_inspection_does_not_authorize_new_cross_owner_execution(users):
    admin, _, bob = users
    second = records(bob)
    with scoped(admin, inspect_all=True) as current:
        assert current.get(Task, second[1]) is not None
        current.add(Run(task_id=second[1]))
        with pytest.raises(DataAccessError, match="unavailable"):
            current.flush()


def test_cross_owner_dependency_and_source_artifact_are_rejected(users):
    _, alice, bob = users
    first, second = records(alice), records(bob)
    with scoped(alice) as current:
        current.add(RunDependency(run_id=first[2], prerequisite_id=second[2]))
        with pytest.raises(DataAccessError):
            current.flush()
        current.rollback()
        current.add(
            Artifact(
                artifact_type="image", relative_path="artifacts/new.png", parent_artifact_ids=[second[3]]
            )
        )
        with pytest.raises(DataAccessError, match="Source artifact"):
            current.flush()


@pytest.mark.parametrize("operation", ["raw", "table", "bulk_update", "bulk_delete", "from_statement"])
def test_unscoped_query_paths_and_bulk_mutations_fail_closed(users, operation):
    _, alice, _ = users
    records(alice)
    statements = {
        "raw": text("SELECT * FROM tasks"),
        "table": select(Task.__table__),
        "bulk_update": update(Task).values(title="changed"),
        "bulk_delete": delete(Task),
        "from_statement": select(Task).from_statement(text("SELECT * FROM tasks")),
    }
    with scoped(alice) as current:
        with pytest.raises(DataAccessError):
            current.execute(statements[operation])


def test_fts_search_filters_private_memories_before_pagination(session, users):
    _, alice, bob = users
    ids = []
    for owner, content in [
        (alice, "Synthetic private sharedword"),
        (bob, "sharedword sharedword sharedword"),
    ]:
        entry = upsert_memory(session, scope="global", content=content)
        entry.owner_id = owner
        ids.append(entry.id)
    session.commit()
    with scoped(alice) as current:
        result = search_memory(current, "sharedword", limit=1)
        assert [entry.id for entry in result] == ids[:1]
        assert current.get(MemoryEntry, ids[1]) is None


def test_cached_or_externally_attached_objects_do_not_bypass_get(session, users):
    _, alice, bob = users
    other_id = records(bob)[1]
    other = session.get(Task, other_id)
    session.expunge(other)
    session.commit()
    with scoped(alice) as current:
        current.add(other)
        assert current.get(Task, other_id) is None
        other.title = "Illegal change"
        with pytest.raises(DataAccessError):
            current.flush()


def test_accounts_and_machine_configuration_are_not_general_private_data(users):
    admin, alice, _ = users
    with scoped(alice) as current:
        assert [row.id for row in current.scalars(select(User))] == [alice]
        with pytest.raises(DataAccessError, match="administrator"):
            current.scalars(select(Setting)).all()
    with scoped(admin, inspect_all=True) as current:
        # Account administration must use the reauthenticated account service.
        current.add(User(username="Bypass", normalized_username="bypass"))
        with pytest.raises(DataAccessError, match="account or machine"):
            current.flush()


def test_every_mapped_table_has_an_explicit_policy():
    from app.data_access import ACCOUNTS, ADMIN, PARENTS, ROOTS, SHARED
    from app.db import Base

    groups = [set(ROOTS), set(PARENTS), set(SHARED), set(ADMIN), set(ACCOUNTS)]
    assert sum(map(len, groups)) == len(set().union(*groups))
    assert {mapper.class_ for mapper in Base.registry.mappers} == set().union(*groups)


def test_all_private_root_families_are_filtered(users):
    admin, alice, bob = users
    for owner in (alice, bob):
        _, _, run_id, _ = records(owner)
        with scoped(owner) as current:
            current.add_all(
                [
                    m.Project(name="Private project", repo_path="/synthetic/owned"),
                    m.Agent(name="Private agent"),
                    m.Approval(action="private.action", run_id=run_id),
                    m.MemoryEntry(scope="global", content="Private memory"),
                    m.Connector(key="same-personal-connector", name="Private connector"),
                    m.ChatProvider(key="same-personal-provider", name="Private provider"),
                ]
            )
            current.commit()
    from app.data_access import ROOTS

    with scoped(alice) as current:
        for model in ROOTS:
            rows = list(current.scalars(select(model)))
            assert len(rows) == 1 and rows[0].owner_id == alice, model.__name__
    with scoped(admin, inspect_all=True) as current:
        for model in ROOTS:
            assert current.scalar(select(func.count(model.id))) == 2, model.__name__


def test_personal_provider_secret_cannot_reference_other_accounts_or_host_environment(users):
    from app.chat_providers import _apply_secret
    from app.secrets import resolve_secret

    _, alice, bob = users
    refs = []
    for owner in (alice, bob):
        with scoped(owner) as current:
            provider = m.ChatProvider(key="external", name="Private provider", location="external")
            current.add(provider)
            current.flush()
            _apply_secret(provider, secret="synthetic personal credential", secret_ref="", clear=False)
            current.commit()
            refs.append((provider.id, provider.secret_ref))
            assert f"accounts/{owner}/chat_providers-{provider.id}" in provider.secret_ref
    with scoped(bob) as current:
        provider = current.get(m.ChatProvider, refs[1][0])
        for other in [refs[0][1], "env:AI_STATION_SMTP_PASSWORD", f"file:secrets/accounts/{bob}/totp-other"]:
            with pytest.raises(ValueError, match="secret reference is unavailable"):
                _apply_secret(provider, secret=None, secret_ref=other, clear=False)
            assert provider.secret_ref == refs[1][1]
            assert resolve_secret(refs[1][1]) == "synthetic personal credential"


def test_direct_foreign_secret_assignment_also_fails_at_flush(users):
    _, alice, _ = users
    with scoped(alice) as current:
        current.add(m.Connector(key="illegal", name="Illegal", secret_ref="env:HOST_SECRET"))
        with pytest.raises(DataAccessError, match="secret reference is unavailable"):
            current.flush()


def test_builtin_model_credentials_are_usable_only_for_the_fixed_configured_endpoint(users, monkeypatch):
    from app.chat_providers import ensure_builtin
    from app.config import clear_settings_cache

    monkeypatch.setenv("AI_STATION_LLM_API_KEY", "synthetic model service credential")
    clear_settings_cache()
    _, alice, _ = users
    with scoped(alice) as current:
        provider = ensure_builtin(current)
        current.commit()
        assert provider.secret_ref == "env:AI_STATION_LLM_API_KEY"
        provider.endpoint = "https://unrelated.example/v1"
        with pytest.raises(DataAccessError, match="secret reference is unavailable"):
            current.flush()


def test_memory_mutations_keep_the_other_accounts_index_and_embeddings(users):
    from app.memory import delete_memory

    _, alice, bob = users
    ids = []
    for owner in (alice, bob):
        run_id = records(owner)[2]
        with scoped(owner) as current:
            entry = upsert_memory(current, scope="global", content="Synthetic searchable phrase")
            current.add(
                m.MemoryEmbedding(
                    memory_id=entry.id,
                    vector=[0.1, 0.9],
                    dimension=2,
                    model="synthetic",
                    content_hash="a" * 64,
                    source_run_id=run_id,
                )
            )
            current.commit()
            ids.append(entry.id)
    with scoped(alice) as current:
        with pytest.raises(KeyError):
            delete_memory(current, ids[1])
        entry = upsert_memory(current, scope="global", content="Updated synthetic phrase", entry_id=ids[0])
        current.commit()
        assert entry.owner_id == alice
        assert [row.id for row in search_memory(current, "Updated")] == ids[:1]
        delete_memory(current, ids[0])
        current.commit()
        assert search_memory(current, "synthetic") == []
        assert list(current.scalars(select(m.MemoryEmbedding))) == []
    with scoped(bob) as current:
        assert [row.id for row in search_memory(current, "searchable")] == ids[1:]
        assert current.get(m.MemoryEmbedding, ids[1]).vector == [0.1, 0.9]


def test_http_scope_factory_rechecks_the_actual_role_instead_of_a_forged_flag(session, users):
    from app.accounts import AccountError, Principal
    from app.data_access import data_session_for

    _, alice, _ = users
    device = login(session, "Alice", "synthetic alice password")
    session.commit()
    forged = Principal(alice, device.principal.session_id, True)
    with pytest.raises(AccountError):
        data_session_for(forged, inspect_all=True)
    with data_session_for(device.principal) as current:
        assert current.scope.user_id == alice and not current.scope.inspect_all


def test_worker_scope_is_frozen_to_the_run_owner_and_never_inherits_admin_inspection(session, users):
    from app.data_access import data_session_for_run

    admin, alice, _ = users
    _, _, run_id, _ = records(admin)
    records(alice)
    with pytest.raises(DataAccessError, match="does not match"):
        data_session_for_run(run_id, alice)
    with data_session_for_run(run_id, admin) as current:
        assert not current.scope.inspect_all
        assert [row.id for row in current.scalars(select(Run))] == [run_id]
    session.get(User, admin).enabled = False
    session.commit()
    with pytest.raises(DataAccessError, match="disabled"):
        data_session_for_run(run_id, admin)
