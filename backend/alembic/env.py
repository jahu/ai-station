"""Migrations use the same WAL and transaction configuration as the application."""

from alembic import context
from app import models  # noqa: F401
from app.db import Base, get_engine


def include_object(obj, name, type_, reflected, compare_to):
    # FTS5 and its shadow tables are managed explicitly in migrations, not ORM.
    return not (type_ == "table" and (name == "memory_fts" or name.startswith("memory_fts_")))


if context.is_offline_mode():
    context.configure(
        url=context.config.get_main_option("sqlalchemy.url"),
        target_metadata=Base.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
