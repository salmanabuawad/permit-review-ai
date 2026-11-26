"""Copy the application database from SQLite to PostgreSQL (one-time move; the SQLite file is only read).

    python scripts/sqlite_to_postgres.py --source sqlite:////path/bbp.sqlite3 \
        --target "postgresql+psycopg://permit@/permit_review?host=/var/run/postgresql" [--check]

* The target schema is built by the Alembic migrations (same head as the source) and must be empty.
* Tables are copied in foreign-key order through the application's own column types, in one transaction.
* Integer ID sequences are moved past the copied rows.
* Verification: identical row counts for every table, and every authority's audit chain verifies exactly as in the
  source (a break already present in SQLite is reported, never repaired: the log is append-only).
--check only compares an existing copy.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import Integer, create_engine, func, inspect, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import models  # noqa: E402,F401 — registers every table
from app.audit import chain_report, verify_chain  # noqa: E402
from app.db import Base, make_engine, run_migrations  # noqa: E402

BATCH = 500


def counts(eng) -> dict[str, int]:
    with eng.connect() as c:
        return {t.name: c.execute(select(func.count()).select_from(t)).scalar_one() for t in Base.metadata.sorted_tables}


def copy(src, dst) -> None:
    with dst.connect() as c:
        if any(c.execute(select(func.count()).select_from(t)).scalar_one() for t in Base.metadata.sorted_tables):
            raise SystemExit("target is not empty — refusing to copy over existing data")
    with src.connect() as s, dst.begin() as d:
        for t in Base.metadata.sorted_tables:
            n = 0
            rows = s.execute(select(t)).mappings()
            while chunk := rows.fetchmany(BATCH):
                d.execute(t.insert(), [dict(r) for r in chunk])
                n += len(chunk)
            print(f"{t.name}: {n}")
        for t in Base.metadata.sorted_tables:       # serial IDs continue after the copied rows
            pk = list(t.primary_key.columns)
            if len(pk) == 1 and isinstance(pk[0].type, Integer) and pk[0].autoincrement in (True, "auto"):
                seq = d.execute(text("select pg_get_serial_sequence(:t, :c)"), {"t": t.name, "c": pk[0].name}).scalar()
                if seq:
                    d.execute(text(f"select setval('{seq}', coalesce((select max({pk[0].name}) from {t.name}), 0) + 1, false)"))


def check(src, dst) -> bool:
    a, b = counts(src), counts(dst)
    ok = a == b
    for name in a:
        if a[name] != b.get(name):
            print(f"COUNT MISMATCH {name}: sqlite {a[name]} != postgres {b.get(name)}")
    # the copy must verify exactly as the source does (a break already in the source is reported, not repaired)
    with Session(src) as s1, Session(dst) as s2:
        for tenant in s2.scalars(select(models.Municipality.id)):
            before, after = chain_report(s1, tenant), chain_report(s2, tenant)
            same = before == after
            state = "ok" if verify_chain(s2, tenant)[0] else f"same as source: {after['broken_links']}, edited {after['edited_rows']}"
            print(f"audit chain {tenant}: {state if same else 'DIFFERS FROM SOURCE'}")
            ok &= same
    extra = set(inspect(src).get_table_names()) - set(a) - {"alembic_version"}
    if extra:
        print(f"note: tables in SQLite not in the model (not copied): {sorted(extra)}")
    print("rows:", sum(a.values()), "tables:", len(a), "->", "OK" if ok else "FAILED")
    return ok


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    if not a.source.startswith("sqlite") or not a.target.startswith("postgresql"):
        raise SystemExit("source must be sqlite, target postgresql")
    src = create_engine(a.source.replace("sqlite:///", "sqlite:///file:", 1) + "?mode=ro&uri=true")
    dst = make_engine(a.target)
    if not a.check:
        run_migrations(dst)
        with src.connect() as s, dst.connect() as d:
            sv = s.execute(text("select version_num from alembic_version")).scalar()
            dv = d.execute(text("select version_num from alembic_version")).scalar()
        if sv != dv:
            raise SystemExit(f"schema mismatch: sqlite at {sv}, postgres at {dv} — migrate the source first")
        copy(src, dst)
    sys.exit(0 if check(src, dst) else 1)


if __name__ == "__main__":
    main()
