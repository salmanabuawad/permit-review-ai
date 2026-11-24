"""Content signals read from one uploaded document, stored in CaseFile.ingest_report["signals"].

Added after the review of Beit Shemesh application 10000197313 (school, plot 201). Its package
showed four problems that a "file present?" check cannot see:

* 15 required documents were a file named "יישלח בהמשך.pdf" (a placeholder, not a document);
* the "electric company approval" was a HOT letter (and a Bezeq letter) for another block/plot;
* the "Antiquities Authority approval" was a supervision/payment demand, not an approval;
* the architect's licence card had expired before submission.

Every signal is a hint for a reviewer, never a decision. Signals are computed from the text layer
only; a scanned page without text yields no signal (the file is NEEDS_OCR), so absence of a signal
is not evidence of compliance.
"""
from __future__ import annotations

import datetime as dt
import re

PLACEHOLDER_RX = re.compile(r"(?:יי?שלח|יוגש|יועבר|יצורף|יי?מסר|ימציא)\s*(?:ב)?המשך|to\s*be\s*(?:sent|submitted)\s*later",
                            re.IGNORECASE)
PLACEHOLDER_MAX_TEXT = 200          # a real document says more than "יישלח בהמשך"

# A block (גוש) number is read only in a short window after the label: protocol, phone and
# antiquities-site numbers elsewhere in a letter must not count. Years (19xx/20xx) are skipped.
BLOCK_LABEL_RX = re.compile(r"גוש|שוג")
BLOCK_WINDOW = 60
BLOCK_NUM_RX = re.compile(r"(?<!\d)(\d{4,5})(?!\d)")

ISSUERS = {   # who a document mentions — used to check that an approval comes from the right body
    "iec": re.compile(r"חברת\s*(?:ה)?חשמל|חח\"?י|Israel\s*Electric|\bIEC\b", re.IGNORECASE),
    "iaa": re.compile(r"רשות\s*(?:ה)?עתיקות|antiquities\.org\.il|Antiquities\s*Authority", re.IGNORECASE),
    "hot": re.compile(r"\bHOT\b|הוט\b|hot-gis"),
    "bezeq": re.compile(r"בזק|bezeq", re.IGNORECASE),
}
ISSUER_HE = {"iec": "חברת החשמל", "iaa": "רשות העתיקות", "hot": "HOT", "bezeq": "בזק"}

# An Antiquities Authority letter that sets conditions/demands payment is not the approval
# ("אישור רשות העתיקות (חתימה על תכנית) ולא דרישת תשלום" — Beit Shemesh preconditions, 10000197313).
IAA_DEMAND_RX = re.compile(r"דרישת\s*(?:פיקוח|תשלום)|הזמנת\s*פיקוח|עליכם\s*לשאת\s*בעלות|"
                           r"מתנה\s*רשות\s*העתיקות\s*את\s*מתן\s*האישור")

DATE = r"(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})"
LICENSE_VALID_RX = re.compile(r"(?:רישיון|רשיון)?\s*בתוקף\s*עד\s*:?\s*" + DATE)
FEE_RECEIPT_RX = re.compile(r"אגרה\s*שנתית")
ANY_DATE_RX = re.compile(DATE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _date(d: str, m: str, y: str) -> str | None:
    try:
        return dt.date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def block_numbers(text: str) -> list[str]:
    t = _norm(text)
    out: list[str] = []
    for m in BLOCK_LABEL_RX.finditer(t):
        for n in BLOCK_NUM_RX.findall(t[m.end():m.end() + BLOCK_WINDOW]):
            if 1900 <= int(n) <= 2099:
                continue
            if n not in out:
                out.append(n)
    return out


def document_signals(filename: str, text: str | None) -> dict:
    name = re.sub(r"[_\-.]+", " ", filename or "")
    t = _norm(text or "")
    sig: dict = {"has_text": bool(t)}
    sig["placeholder"] = bool(PLACEHOLDER_RX.search(name)) or (
        bool(t) and len(t) <= PLACEHOLDER_MAX_TEXT and bool(PLACEHOLDER_RX.search(t)))
    if not t:
        return sig
    sig["blocks"] = block_numbers(t)
    sig["issuers"] = [k for k, rx in ISSUERS.items() if rx.search(t)]
    sig["iaa_demand"] = "iaa" in sig["issuers"] and bool(IAA_DEMAND_RX.search(t))
    if m := LICENSE_VALID_RX.search(t):
        sig["license_valid_until"] = _date(*m.groups())
    if FEE_RECEIPT_RX.search(t) and (m := ANY_DATE_RX.search(t)):
        sig["fee_receipt_date"] = _date(*m.groups())
    return sig
