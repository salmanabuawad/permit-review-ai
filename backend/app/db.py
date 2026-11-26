from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or settings.database_url
    if url.startswith("sqlite"):
        from pathlib import Path
        path = url.replace("sqlite:///", "", 1)
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # a writer waits up to 30 s for another one instead of failing at once ("database is locked"); WAL lets readers
        # go on while a background job writes
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(eng, "connect")
        def _fk(dbapi_conn, _):  # enforce FKs in SQLite
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
            dbapi_conn.execute("PRAGMA busy_timeout=30000")
            if path and path != ":memory:":
                dbapi_conn.execute("PRAGMA journal_mode=WAL")
        return eng
    return create_engine(url, pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


BASELINE_REVISION = "0001"


def run_migrations(eng=None) -> None:
    """Bring the schema to the latest Alembic revision.

    A database created before migrations existed (tables present, no alembic_version) is stamped
    at the baseline first, so its data is kept and only the new changes are applied."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    eng = eng or engine
    here = Path(__file__).resolve().parents[1]
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "migrations"))
    cfg.attributes["configure_logger"] = False
    with eng.connect() as conn:
        if eng.dialect.name == "sqlite":          # batch ALTERs rebuild tables; FK checks must be off meanwhile
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        cfg.attributes["connection"] = conn
        tables = set(inspect(conn).get_table_names())
        if "alembic_version" not in tables and "permit_cases" in tables:
            command.stamp(cfg, BASELINE_REVISION)
        command.upgrade(cfg, "head")
        conn.commit()
        if eng.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def drop_everything(eng=None) -> None:
    from sqlalchemy import text
    eng = eng or engine
    Base.metadata.drop_all(eng)
    with eng.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def get_session() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
