"""Run a source crawl from the command line (for a systemd timer / cron).

    python -m app.source_monitor --tenant bnei-brak
"""
import argparse
import json

from ..db import SessionLocal
from ..models import SourceCrawl
from .service import start_crawl


def main() -> None:
    ap = argparse.ArgumentParser(description="Crawl the official rule sources")
    ap.add_argument("--tenant", default="bnei-brak")
    ap.add_argument("--actor", default="system:source-monitor")
    a = ap.parse_args()
    cid = start_crawl(SessionLocal, a.tenant, a.actor, wait=True)
    with SessionLocal() as s:
        c = s.get(SourceCrawl, cid)
        print(json.dumps({"crawl": cid, "status": c.status, **(c.summary or {})}, ensure_ascii=False))


if __name__ == "__main__":
    main()
