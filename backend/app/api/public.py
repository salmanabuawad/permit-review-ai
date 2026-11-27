"""API: public, unauthenticated endpoints used by the product website (permit.kortexd.com).

- GET  /api/public/committee — the committee responsible for a block / parcel, from official boundaries only
  (Survey of Israel cadastre × Planning Administration planning areas). Read-only public data, rate-limited.
- POST /api/public/demo-request — a demo / contact request, e-mailed to the Permit360 inbox; nothing is stored.
  Consent is required; a hidden honeypot field and per-address limits keep automated submissions out."""
import re
import threading
import time

from fastapi import APIRouter

from .common import *  # noqa: F401,F403 — shared imports, schemas and helpers

router = APIRouter()

LOOKUPS_PER_MIN, DEMOS_PER_HOUR = 20, 3
ROLES = {"engineer", "architect", "committee", "owner", "other"}
LANGS = {"he", "en", "ar", "ru"}
EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
_hits: dict[str, list[float]] = {}
_lock = threading.Lock()


def _addr(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


def _limited(key: str, n: int, window: float) -> bool:
    t = time.time()
    with _lock:
        recent = [x for x in _hits.get(key, []) if t - x < window]
        if len(recent) >= n:
            _hits[key] = recent
            return True
        recent.append(t)
        _hits[key] = recent
        return False


@router.get("/api/public/committee")
def public_committee(gush: str, helka: str, request: Request, s: Session = Depends(get_session)):
    from .. import jurisdiction as J
    if not re.fullmatch(r"\d{1,6}", gush or "") or not re.fullmatch(r"\d{1,5}", helka or "") or int(gush) == 0 or int(helka) == 0:
        raise HTTPException(422, "invalid")
    if _limited("lookup:" + _addr(request), LOOKUPS_PER_MIN, 60):
        raise HTTPException(429, "rate")
    r = J.discover(s, gush, helka)
    s.commit()                                         # the discovery cache
    cands = [{"committee": c.get("committee_name"), "area": c.get("name_he"), "code": c.get("code"),
              "area_type": c.get("area_type_he"), "district": c.get("district"), "share": c.get("share")}
             for c in r.get("candidates", [])]
    return {"status": r.get("status"), "reason": r.get("reason"), "gush": r.get("gush", gush), "helka": r.get("helka", helka),
            "parcel_area_m2": (r.get("parcel") or {}).get("area_m2"), "candidates": cands,
            "localities": [x.get("name_he") for x in r.get("localities", []) if x.get("name_he") and x.get("name_he") != "שטח כללי"],
            "source": "Survey of Israel cadastre · Planning Administration planning areas"}


class DemoIn(BaseModel):
    name: str
    email: str
    organization: str = ""
    role: str = "other"
    phone: str = ""
    message: str = ""
    lang: str = "he"
    consent: bool = False
    website: str = ""          # honeypot: people never see or fill it


@router.post("/api/public/demo-request", status_code=202)
def public_demo_request(body: DemoIn, request: Request):
    from .. import mailer
    if body.website.strip():                                   # a bot filled the hidden field: accept silently
        return {"ok": True}
    name, email = body.name.strip()[:120], body.email.strip().lower()[:254]
    if len(name) < 2 or not EMAIL.fullmatch(email) or not body.consent:
        raise HTTPException(422, "required")
    if _limited("demo:" + _addr(request), DEMOS_PER_HOUR, 3600) or _limited("demo-mail:" + email, DEMOS_PER_HOUR, 3600):
        raise HTTPException(429, "rate")
    if not mailer.configured():
        raise HTTPException(503, "unavailable")
    import os
    to = os.environ.get("BBP_DEMO_NOTIFY") or os.environ.get("BBP_SIGNUP_NOTIFY") or os.environ.get("BBP_MAIL_FROM")
    role = body.role if body.role in ROLES else "other"
    lang = body.lang if body.lang in LANGS else "he"
    text = (f"Permit360 demo request (website, {lang})\n\nName: {name}\nE-mail: {email}\n"
            f"Organization: {body.organization.strip()[:200]}\nRole: {role}\nPhone: {body.phone.strip()[:40]}\n\n"
            f"{body.message.strip()[:3000]}\n\nConsent to be contacted: yes\n")
    if not to or not mailer.send(to, f"Permit360 — demo request: {name}", text):
        raise HTTPException(503, "unavailable")
    return {"ok": True}
