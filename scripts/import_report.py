"""Generate docs/reports/import_test_report.md from ACTUAL runs (no hand-written results).

  python scripts/import_report.py [package.zip] [full_protocol.pdf] [--with-tests]

Runs, on a fresh temporary database: import of the package, re-import, and import of the full
protocol; records counts, timings, per-application extraction results and agreement with the
package's index.csv. With --with-tests it also runs the pytest suite on SQLite and (if pgserver is
installed) on an embedded PostgreSQL, and records the summary lines. Personal names (applicant,
architect, objectors in comment texts) are not written to the report.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PKG = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else Path(r"C:\Users\A\Downloads\bnei_brak_31_permit_applications.zip")
PROTO = Path(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else Path(r"C:\Users\A\Downloads\samples.pdf")
WITH_TESTS = "--with-tests" in sys.argv

tmp = Path(tempfile.mkdtemp(prefix="bbp_report_"))
os.environ["BBP_DATABASE_URL"] = f"sqlite:///{(tmp / 'r.sqlite3').as_posix()}"
os.environ["BBP_STORAGE_DIR"] = str(tmp / "storage")
sys.path.insert(0, str(BACKEND))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient  # noqa: E402

from app.intake import text as T  # noqa: E402
from app.main import PERMIT_TYPES, app  # noqa: E402
from app.seed import seed  # noqa: E402

H = {"X-User": "u-secretary"}
OUT_HE = {"approved": "אושר", "approved_with_conditions": "אושר בתנאים/בהערות", "renewed": "חידוש אישור",
          "objection_partially_accepted": "התנגדות התקבלה בחלקה — אושר", "objection_rejected": "התנגדות נדחתה — אושר",
          "deferred": "הדיון נדחה", "rejected": "נדחה", "other": "אחר — נדרש עיון"}


def imp(c, name, data):
    t0 = time.perf_counter()
    pv = c.post("/api/import/analyze", headers=H, files=[("files", (name, data))]).json()
    t1 = time.perf_counter()
    apps = [{"key": a["key"], "include": True, "fields": {}, "documents": [{"ref": d["ref"], "include": True} for d in a["documents"]]}
            for a in pv["applications"]]
    r = c.post("/api/import/commit", headers=H, json={"token": pv["token"], "applications": apps, "run_checks": False}).json()
    return pv, r, t1 - t0, time.perf_counter() - t1


def pytest_summary(env_extra: dict) -> str:
    env = {**os.environ, **env_extra}
    env.pop("BBP_DATABASE_URL", None)
    env.pop("BBP_STORAGE_DIR", None)
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-W", "ignore", "-p", "no:cacheprovider"], cwd=BACKEND,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    lines = [l for l in p.stdout.splitlines() if re.search(r"\d+ (passed|failed|error)", l)]
    return lines[-1].strip() if lines else (p.stdout[-300:] + p.stderr[-300:])


def main():
    data = PKG.read_bytes()
    with zipfile.ZipFile(PKG) as z:
        members = z.namelist()
        rows = list(csv.DictReader(io.StringIO(z.read("index.csv").decode("utf-8-sig"))))
    seed(reset=True, samples=False)
    with TestClient(app) as c:
        pv1, r1, a1, c1 = imp(c, PKG.name, data)
        pv2, r2, a2, c2 = imp(c, PKG.name, data)
        proto = imp(c, PROTO.name, PROTO.read_bytes()) if PROTO.exists() else None
        cases = {x["case_number"]: x for x in c.get("/api/cases", headers=H).json()}
        ex = {n: c.get(f"/api/cases/{x['id']}/extracted", headers=H).json() for n, x in cases.items()}

    L = []
    w = L.append
    w("# דוח בדיקת קליטה — 31 בקשות מפרוטוקול ועדת המשנה (2016)\n")
    w(f"הופק אוטומטית ב־{dt.datetime.now():%d/%m/%Y %H:%M} ע\"י `scripts/import_report.py` מתוך הרצה בפועל על מסד נתונים זמני ונקי. "
      "שמות מבקשים, עורכים ומתנגדים אינם נכללים בדוח.\n")
    w("> הנתונים מפרוטוקול היסטורי משמשים לבדיקת חילוץ מסמכים וניתוח החלטות מנהליות בלבד. "
      "אינם תחליף לתכניות אדריכליות מקוריות ואינם בדיקת עמידה בדין התכנון העדכני.\n")
    w("## קלט\n")
    w(f"| פריט | ערך |\n|---|---|\n| חבילה | `{PKG.name}` — {len(members)} קבצים, SHA-256 `{hashlib.sha256(data).hexdigest()[:16]}…` |")
    if PROTO.exists():
        w(f"| פרוטוקול מלא | `{PROTO.name}` — SHA-256 `{hashlib.sha256(PROTO.read_bytes()).hexdigest()[:16]}…` |")
    w("| ספק חילוץ | `local_rules` (מקומי, דטרמיניסטי) — לפי מדיניות ה־AI ברירת המחדל |\n")

    s1, s2 = r1["summary"], r2["summary"]
    w("## תוצאות מרכזיות\n")
    w("| בדיקה | צפוי | בפועל | עבר |\n|---|---|---|---|")
    chk = lambda a, b: "✅" if a == b else "❌"  # noqa: E731
    w(f"| בקשות שנוצרו בייבוא ראשון | 31 | {s1['created']} | {chk(s1['created'], 31)} |")
    w(f"| קובצי אינדקס (index.csv/json/html) שסווגו כמטא-נתונים ולא כבקשה | 3 | {s1['metadata_files']} | {chk(s1['metadata_files'], 3)} |")
    w(f"| כשלונות | 0 | {s1['failed']} | {chk(s1['failed'], 0)} |")
    w(f"| ייבוא חוזר — נוצרו | 0 | {s2['created']} | {chk(s2['created'], 0)} |")
    w(f"| ייבוא חוזר — זוהו ככפולות | 31 | {s2['duplicate']} | {chk(s2['duplicate'], 31)} |")
    w(f"| מספר תיקים במערכת לאחר כל הייבואים | 31 | {len(cases)} | {chk(len(cases), 31)} |")
    if proto:
        pp, pr = proto[0], proto[1]
        w(f"| פרוטוקול מלא — בקשות שזוהו | 31 | {pp['counts']['applications']} | {chk(pp['counts']['applications'], 31)} |")
        w(f"| פרוטוקול מלא — פריטים תכנוניים (לא נוצרו מהם בקשות) | 4 | {pp['counts']['planning_items']} | {chk(pp['counts']['planning_items'], 4)} |")
        w(f"| פרוטוקול מלא — בקשות חדשות שנוצרו | 0 | {pr['summary']['created']} | {chk(pr['summary']['created'], 0)} |")
        w(f"| פרוטוקול מלא — מסמך נוסף צורף לבקשה קיימת | 31 | {pr['summary']['updated']} | {chk(pr['summary']['updated'], 31)} |")
    w(f"\nזמני ריצה (ללא הרצת מנוע הכללים): ניתוח {a1:.1f} ש׳ + ייבוא {c1:.1f} ש׳; ייבוא חוזר: ניתוח {a2:.1f} ש׳ + {c2:.1f} ש׳"
      + (f"; פרוטוקול מלא: {proto[2]:.1f} + {proto[3]:.1f} ש׳." if proto else "."))

    cls = Counter((d["classification"] or {}).get("doc_class_he") for d in pv1["documents"])
    w("\n## סיווג מסמכים (לפי תוכן)\n")
    w("| סוג מסמך | מספר |\n|---|---|")
    for k, v in cls.most_common():
        w(f"| {k} | {v} |")

    by_no = {r["מספר בקשה"]: r for r in rows}
    fields = ["application_number", "building_file_number", "address", "gush", "helka", "zone", "plot_area_m2",
              "application_type", "permit_type", "description", "applicable_plans", "deviations"]
    he = {"application_number": "מספר בקשה", "building_file_number": "תיק בניין", "address": "כתובת", "gush": "גוש",
          "helka": "חלקה", "zone": "יעוד", "plot_area_m2": "שטח מגרש", "application_type": "סוג בקשה (כנוסחו)",
          "permit_type": "סוג בקשה (סיווג)", "description": "מהות הבקשה", "applicable_plans": "תוכניות חלות",
          "deviations": "הקלות"}
    w("\n## כיסוי שדות (31 בקשות)\n")
    w("| שדה | נמצא | ודאות ממוצעת | מתחת לסף אימות (80%) |\n|---|---|---|---|")
    for f in fields:
        vals = [x for e in ex.values() for x in e["fields"] if x["field"] == f]
        avg = sum(x["confidence"] for x in vals) / len(vals) if vals else 0
        low = sum(1 for x in vals if x["confidence"] < 0.8)
        w(f"| {he[f]} | {len(vals)}/31 | {avg:.0%} | {low} |")
    nc = sum(1 for e in ex.values() if e["comments"])
    nd = sum(1 for e in ex.values() if e["decisions"])
    na = sum(1 for e in ex.values() if e["areas"])
    w(f"| שטחים (טבלה) | {na}/31 | 60% (פענוח מבני) | כולן |")
    w(f"| הערות גורמי מקצוע | {nc}/31 | 85% | — |")
    w(f"| החלטת ועדה | {nd}/31 | — | — |")
    agree, mism = 0, []
    for n, e in ex.items():
        f = {x["field"]: x["value"] for x in e["fields"]}
        r = by_no[n]
        ok = f.get("gush") == r["גוש"] and f.get("helka") == r["חלקה"] and f.get("application_number") == n
        mism += [] if ok else [n]
        dec, exc = T.compact(e["decisions"][0]["text"]) if e["decisions"] else "", T.compact(r["תחילת נוסח ההחלטה (לבדיקה במקור)"])
        win = [exc[i:i + 10] for i in range(0, max(len(exc) - 10, 1), 10)]
        agree += bool(win) and sum(x in dec for x in win) / len(win) >= 0.5
    w(f"\nהתאמה לאינדקס: מספר בקשה+גוש+חלקה זהים ב־{31 - len(mism)}/31 בקשות"
      + (f" (חריגות: {', '.join(mism)})" if mism else "") + f"; נוסח ההחלטה תואם לתחילת הנוסח באינדקס ב־{agree}/31.\n")

    w("## פירוט לפי בקשה\n")
    w("| סעיף | מספר בקשה | קובץ | עמ׳ במקור | כתובת | גוש/חלקה | תיק בניין | סוג בקשה (סיווג) | החלטה | הערות | שטחים |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        n = r["מספר בקשה"]
        e = ex.get(n, {"fields": [], "comments": [], "decisions": [], "areas": []})
        f = {x["field"]: x for x in e["fields"]}
        g = lambda k: (f.get(k) or {}).get("value", "—")  # noqa: E731
        op = (f.get("application_number") or {}).get("source") or {}
        dec = OUT_HE.get(e["decisions"][0]["outcome"], "—") if e["decisions"] else "**לא נמצאה**"
        w(f"| {r['סעיף']} | {n} | `{r['קובץ']}` | {op.get('original_page', '—')} | {g('address')} | {g('gush')}/{g('helka')} | "
          f"{g('building_file_number')} | {PERMIT_TYPES.get(g('permit_type'), g('permit_type'))} | {dec} | {len(e['comments'])} | {len(e['areas'])} |")

    b = ex.get("201600156")
    if b:
        f = {x["field"]: x for x in b["fields"]}
        w("\n## בקשה 201600156 — ביאליק 25 (בדיקה מפורטת)\n")
        w("| שדה | ערך שחולץ | מקור (קובץ · עמוד · עמוד במקור) | ודאות |\n|---|---|---|---|")
        for k in fields:
            if k in f:
                s = f[k]["source"] or {}
                v = PERMIT_TYPES.get(f[k]["value"], f[k]["value"]) if k == "permit_type" else f[k]["value"]
                w(f"| {he[k]} | {v} | `{s.get('file')}` · {s.get('page')} · {s.get('original_page')} | {f[k]['confidence']:.0%} |")
        w("\nשטחים: " + "; ".join(f"{a['value']['floor'] or ''} {('קיים' if a['value']['status'] == 'existing' else 'מוצע' if a['value']['status'] == 'proposed' else '')} {a['value']['label']} {a['value']['value_m2']} מ\"ר"
                                   for a in b["areas"]))
        w("\nהערות לפי גורם: " + ", ".join(f"{k} — {v}" for k, v in Counter(c["department_he"] for c in b["comments"]).items()))
        d = b["decisions"][0]
        w(f"\nהחלטת הוועדה ({OUT_HE[d['outcome']]}, ישיבה {d['meeting_number']} מיום {d['meeting_date']}): «{d['text']}»")

    if WITH_TESTS:
        w("\n## הרצת בדיקות אוטומטיות\n")
        w(f"- SQLite: `{pytest_summary({})}`")
        try:
            import pgserver
            srv = pgserver.get_server(Path(tempfile.gettempdir()) / "bbp_pg_report", cleanup_mode="stop")
            import psycopg
            uri = srv.get_uri()
            with psycopg.connect(uri, autocommit=True) as conn:
                conn.execute("DROP DATABASE IF EXISTS bbp_report")
                conn.execute("CREATE DATABASE bbp_report")
            pg = uri.replace("postgresql://", "postgresql+psycopg://").rsplit("/", 1)[0] + "/bbp_report"
            w(f"- PostgreSQL ({srv.psql('select version();').split(chr(10))[2].strip()[:30]}…): `{pytest_summary({'BBP_TEST_DATABASE_URL': pg})}`")
            srv.cleanup()
        except Exception as exc:  # noqa: BLE001
            w(f"- PostgreSQL: לא הורץ ({exc})")

    out = ROOT / "docs" / "reports" / "import_test_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("written", out)


if __name__ == "__main__":
    main()
