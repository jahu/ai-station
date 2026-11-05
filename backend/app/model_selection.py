"""Logical GGUF selections over shared physical model objects.

Existing file references retain the default definition. Additional complete sets
use their definition UUID; neither source paths nor file observations are aliases.
"""

from uuid import UUID

from sqlalchemy import select

from app.models import ModelDefinition, ModelFile


def default_definition(session, file_id):
    return session.scalar(
        select(ModelDefinition).where(
            ModelDefinition.file_id == file_id, ModelDefinition.binding_key.is_(None)
        )
    )


def definition_for(session, model, definition_id=None):
    if definition_id is None:
        return default_definition(session, model.id)
    definition = session.get(ModelDefinition, str(definition_id))
    if definition is None or definition.file_id != model.id or not definition.binding_key:
        raise ValueError("The selected logical model does not belong to this primary file")
    return definition


def resolve(session, reference):
    try:
        identity = str(UUID(str(reference).removeprefix("llamacpp:")))
    except ValueError:
        return None, None
    model = session.get(ModelFile, identity)
    if model is not None:
        definition = default_definition(session, model.id)
        return (
            (None, None) if definition is not None and definition.status == "removed" else (model, definition)
        )
    definition = session.get(ModelDefinition, identity)
    if (
        definition is None
        or not definition.binding_key
        or not definition.file_id
        or definition.status == "removed"
    ):
        return None, None
    return session.get(ModelFile, definition.file_id), definition


def selection_id(model, definition=None):
    return definition.id if definition is not None and definition.binding_key else model.id


def definition_id(definition):
    return definition.id if definition is not None and definition.binding_key else None


def matches(metadata, model, definition=None):
    return metadata.get("model_file_id") == model.id and metadata.get("model_definition_id") == definition_id(
        definition
    )


def choices(session):
    files = list(
        session.scalars(
            select(ModelFile)
            .where(ModelFile.category == "llm", ModelFile.format == "gguf")
            .order_by(ModelFile.filename, ModelFile.id)
            .limit(200)
        )
    )
    definitions = (
        list(
            session.scalars(select(ModelDefinition).where(ModelDefinition.file_id.in_([f.id for f in files])))
        )
        if files
        else []
    )
    by_file = {}
    for definition in definitions:
        by_file.setdefault(definition.file_id, []).append(definition)
    for model in files:
        rows = by_file.get(model.id, [])
        default = next((row for row in rows if row.binding_key is None), None)
        if default is None or default.status != "removed":
            yield model, default
        for definition in sorted((r for r in rows if r.binding_key), key=lambda r: r.id):
            if definition.status != "removed":
                yield model, definition
