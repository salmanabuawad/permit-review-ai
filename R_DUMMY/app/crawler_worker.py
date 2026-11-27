"""The crawler process: the only part of the system that fetches regulatory websites.

    python -m app.crawler_worker

Runs as its own OS user (permit-crawler) whose outbound traffic the server firewall limits to public addresses on
ports 80/443 (plus the local DNS resolver) — so a redirect, a DNS rebinding answer or a link in a crawled page can
never reach the server itself, the private network or a cloud metadata address. The app process queues crawls and
onboarding jobs in the database (BBP_CRAWLER_SEPARATE=true); this worker claims and runs them:
  * queued source crawls (oldest first) — a user's "crawl now", or a schedule the authority's administrator chose;
  * authority onboarding jobs (official-directory discovery + first crawl) a user started;
  * committee site probes and candidate-source fetches a platform administrator queued (national committee register);
  * XPLAN plan discovery for a case (Planning Administration map service; BBP_XPLAN_ENABLED=true).
Crawls run on demand only unless the administrator sets a daily or weekly schedule. Nothing is retried or resumed on
its own: a crawl left 'running' by a crawler that died is marked failed at start, an onboarding job whose lease
expired becomes FAILED; a user starts it again.
"""
from __future__ import annotations

import logging
import time

from . import authority_onboarding as A
from .db import SessionLocal
from .source_monitor import service

log = logging.getLogger("bbp.crawler")
_tick = 0


def run_once() -> bool:
    """One unit of work; True when something ran."""
    cid = service.claim_queued(SessionLocal)
    if cid:
        log.info("crawl %s", cid)
        service.run_claimed(SessionLocal, cid)
        return True
    tenant = A.claim_next(SessionLocal)
    if tenant:
        log.info("onboarding %s", tenant)
        A.run_onboarding(SessionLocal, tenant)
        return True
    from . import committees
    cid = committees.claim_probe(SessionLocal)     # committee site probes an administrator queued
    if cid:
        log.info("committee probe %s", cid)
        committees.run_probe(SessionLocal, cid)
        return True
    cid = committees.claim(SessionLocal, "fetch")     # fetch a committee's candidate sources into snapshots
    if cid:
        log.info("committee fetch %s", cid)
        committees.run_fetch(SessionLocal, cid)
        return True
    cid = committees.claim(SessionLocal, "deep")      # deep search of a committee an administrator asked for
    if cid:
        log.info("committee deep search %s", cid)
        committees.run_deep(SessionLocal, cid)
        return True
    from . import plan_discovery
    cid = plan_discovery.claim(SessionLocal)         # XPLAN plan discovery a user requested for a case
    if cid:
        log.info("xplan discovery %s", cid)
        plan_discovery.run_claimed(SessionLocal, cid)
        return True
    global _tick
    _tick += 1
    if _tick % 2:                                     # every other pass: a committee's meeting record (study material),
        cid = committees.claim(SessionLocal, "meetings")   # so indexing below keeps moving while it runs for hours
        if cid:
            from . import meetings
            log.info("committee meetings %s", cid)
            meetings.run_job(SessionLocal, cid)
            return True
    due = service.queue_due(SessionLocal)                 # only authorities whose administrator set a schedule
    if due:
        log.info("scheduled crawl(s) queued: %s", due)
        return True
    from . import hierarchy                               # idle: cut fetched pages into clauses
    with SessionLocal() as s:
        n = hierarchy.extract_clauses(s, limit=300)
    if n:
        log.info("clauses %d", n)
        return True
    from . import embeddings                              # idle: embed fetched text, a bounded batch at a time
    if embeddings.available():
        with SessionLocal() as s:
            out = embeddings.index(s, max_chunks=64)
        if out.get("embedded") or out.get("chunks_made"):
            log.info("embeddings %s", out)
            return True
    return False


def main(interval_s: float = 10.0) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    n = service.fail_interrupted(SessionLocal)
    if n:
        log.warning("%d interrupted crawl(s) marked failed", n)
    from . import committees
    n = committees.fail_interrupted(SessionLocal)
    if n:
        log.warning("%d interrupted committee job(s) marked failed", n)
    from . import plan_discovery
    n = plan_discovery.fail_interrupted(SessionLocal)
    if n:
        log.warning("%d interrupted XPLAN discovery job(s) marked failed", n)
    while True:
        try:
            if run_once():
                continue
        except Exception:                                  # noqa: BLE001 — logged; the worker never dies
            log.exception("crawler pass failed")
        time.sleep(interval_s)


if __name__ == "__main__":
    main()
