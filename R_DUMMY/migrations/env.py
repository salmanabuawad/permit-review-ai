"""Alembic environment. The database URL comes from the app settings (BBP_DATABASE_URL), so the
same migrations run on SQLite (POC) and PostgreSQL (production). SQLite needs batch mode for
ALTER TABLE operations."""
from logging.config import fileConfig

from alembic import context

from app.config import settings
from app.db import Base, make_engine
from app import models  # noqa: F401 — registers all tables on Base.metadata

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, render_as_batch=True, user_module_prefix="models.")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        engine = make_engine(config.attributes.get("url") or settings.database_url)
        with engine.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                      user_module_prefix="models.", compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
