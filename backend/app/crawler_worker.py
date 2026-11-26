"""The crawler process: the only part of the system that fetches regulatory websites.

    python -m app.crawler_worker

Runs as its own OS user (permit-crawler) whose outbound traffic the server firewall limits to public addresses on
ports 80/443 (plus the local DNS resolver) — so a redirect, a DNS rebinding answer or a link in a crawled page can
never reach the server itself, the private network or a cloud metadata address. The app process queues crawls and
onboarding jobs in the database (BBP_CRAWLER_SEPARATE=true); this worker claims and runs them:
  * queued source crawls (oldest first) — a user's "crawl now", or a schedule the authority's administrator chose;
  * authority onboarding jobs (official-directory discovery + first crawl) a user started;
  * committee site probes a platform administrator queued (national committee register).
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
    due = service.queue_due(SessionLocal)                 # only authorities whose administrator set a schedule
    if due:
        log.info("scheduled crawl(s) queued: %s", due)
    return bool(due)


def main(interval_s: float = 10.0) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    n = service.fail_interrupted(SessionLocal)
    if n:
        log.warning("%d interrupted crawl(s) marked failed", n)
    while True:
        try:
            if run_once():
                continue
        except Exception:                                  # noqa: BLE001 — logged; the worker never dies
            log.exception("crawler pass failed")
        time.sleep(interval_s)


if __name__ == "__main__":
    main()
