"""Create schema + demo tenant/users/cases from fixtures. `python -m app.seed --reset`

Modes:
  default        demo tenant with fictitious sample cases (local development + tests);
                 DEMO_FIXTURE rules are active only there. Also creates an empty bnei-brak tenant.
  --no-samples   clean pilot install: bnei-brak tenant with role users only, no cases or files.
"""
from __future__ import annotations

import shutil
import sys

from sqlalchemy.orm import Session

from . import audit, services
from .config import ROOT, settings
from .db import drop_everything, engine, run_migrations
from .models import Municipality, PermitCase, User

FIX = ROOT / "fixtures" / "demo"

USERS = [
    ("u-admin", "demo", "מנהל מערכת (הדגמה)", "sysadmin"),
    ("u-engineer", "demo", "מהנדס העיר (הדגמה)", "city_engineer"),
    ("u-manager", "demo", "מנהלת אגף רישוי (הדגמה)", "dept_manager"),
    ("u-reviewer", "demo", "בודק תכניות א׳ (הדגמה)", "reviewer"),
    ("u-reviewer2", "demo", "בודקת תכניות ב׳ (הדגמה)", "reviewer"),
    ("u-planner", "demo", "עורך בקשה (הדגמה)", "planner"),
    ("u-secretary", "demo", "מזכירות (הדגמה)", "secretariat"),
    ("u-bb-admin", "bnei-brak", "מנהל מערכת — בני ברק", "sysadmin"),
]

CASES = [
    dict(case_number="DEMO-0001", title="[הדגמה] הרחבת דירה באגף אחורי — חריגה מקו בניין",
         permit_type="addition_extension", applicable_plans=["DEMO/1", "בב/105"], zone="residential_B",
         gush="DEMO", helka="1", address="רחוב הדגמה 1 (פיקטיבי)", assigned_to="u-reviewer",
         declared={"multi_floor_addition": True, "has_unbuilt_floor_in_wing": True,
                   "unbuilt_floor_railing_height_m": 1.0, "survey_map_date": "2025-12-01"},
         files=[("case1_extension_exceeds.dxf", "architectural_plan"), ("case1_area_table.xlsx", "area_table"),
                ("application_form.pdf", "application_form"), ("survey_map.pdf", "survey_map"),
                ("permit_info.pdf", "permit_info")]),
    dict(case_number="DEMO-0002", title="[הדגמה] הרחבת דירה תקינה בתוך קווי הבניין",
         permit_type="addition_extension", applicable_plans=["DEMO/1"], zone="residential_B",
         gush="DEMO", helka="2", address="רחוב הדגמה 2 (פיקטיבי)", assigned_to="u-reviewer2",
         declared={"multi_floor_addition": False, "has_unbuilt_floor_in_wing": False,
                   "survey_map_date": "2026-09-01"},
         files=[("case2_extension_ok.dxf", "architectural_plan"), ("case2_area_table.xlsx", "area_table"),
                ("application_form.pdf", "application_form"), ("survey_map.pdf", "survey_map"),
                ("permit_info.pdf", "permit_info"), ("photos.pdf", "existing_building_photos"),
                ("master_plan.pdf", "building_master_plan"), ("sections.pdf", "sections_elevations")]),
    dict(case_number="DEMO-0003", title="[הדגמה] חדר גג — תכנית לתוספת זכויות (מדיניות 13.1.2026), נסיגה 2.49 מ׳",
         permit_type="roof_room_addition", track="policy_2026_roof_rights", stage="plan_review",
         applicable_plans=["DEMO/1"], zone="residential_B", gush="DEMO", helka="3",
         address="רחוב הדגמה 3 (פיקטיבי)", assigned_to="u-reviewer",
         declared={"typical_floors_above_entry": 5, "roof_room_separate_access": False,
                   "roof_attachment_status": "attached_to_roof_apartment", "consent_pct": 75,
                   "submission_date": "2026-03-01"},
         files=[("case3_roof_room_249.dxf", "architectural_plan"), ("consents.pdf", "consents"),
                ("photos.pdf", "existing_building_photos")]),
    dict(case_number="DEMO-0004", title="[הדגמה] מרפסת סוכה — קרבה לגבול מגרש",
         permit_type="addition_sukkah", applicable_plans=["DEMO/1"], zone="residential_C",
         gush="DEMO", helka="4", address="רחוב הדגמה 4 (פיקטיבי)", assigned_to=None,
         declared={}, files=[("case4_sukkah.dxf", "architectural_plan"), ("application_form.pdf", "application_form")]),
]


PILOT_USERS = [
    ("u-admin", "מנהל מערכת", "sysadmin"),
    ("u-engineer", "מהנדס העיר", "city_engineer"),
    ("u-manager", "מנהל/ת אגף רישוי", "dept_manager"),
    ("u-reviewer", "בודק/ת תכניות א׳", "reviewer"),
    ("u-reviewer2", "בודק/ת תכניות ב׳", "reviewer"),
    ("u-planner", "עורך/ת בקשה", "planner"),
    ("u-secretary", "מזכירות", "secretariat"),
]


HOF_ASHKELON = ("hof-ashkelon", "הוועדה המקומית לתכנון ובנייה חוף אשקלון")
HOF_ASHKELON_USERS = [
    ("u-ha-admin", "מנהל מערכת — חוף אשקלון", "sysadmin"),
    ("u-ha-engineer", "מהנדס הוועדה — חוף אשקלון", "city_engineer"),
    ("u-ha-manager", "מנהל/ת רישוי — חוף אשקלון", "dept_manager"),
    ("u-ha-reviewer", "בודק/ת תכניות — חוף אשקלון", "reviewer"),
    ("u-ha-planner", "עורך/ת בקשה — חוף אשקלון", "planner"),
    ("u-ha-secretary", "מזכירות — חוף אשקלון", "secretariat"),
]


def ensure_hof_ashkelon(s: Session) -> bool:
    """The Hof Ashkelon local committee tenant with its role users. Idempotent; True if anything was added."""
    added = False
    if s.get(Municipality, HOF_ASHKELON[0]) is None:
        s.add(Municipality(id=HOF_ASHKELON[0], name_he=HOF_ASHKELON[1], is_demo=False))
        s.flush()
        added = True
    for uid, name, role in HOF_ASHKELON_USERS:
        if s.get(User, uid) is None:
            s.add(User(id=uid, tenant_id=HOF_ASHKELON[0], display_name=name, role=role))
            added = True
    return added


def seed_empty() -> None:
    """Clean pilot install: Bnei Brak tenant with role users only — no sample cases, no files,
    and no demo tenant (so the fictitious DEMO/1 rules never run)."""
    run_migrations()
    with Session(engine) as s:
        if s.get(Municipality, "bnei-brak"):
            print("already seeded (use --reset)")
            return
        s.add(Municipality(id="bnei-brak", name_he="עיריית בני ברק", is_demo=False))
        s.flush()
        s.add_all([User(id=i, tenant_id="bnei-brak", display_name=n, role=r) for i, n, r in PILOT_USERS])
        ensure_hof_ashkelon(s)
        s.commit()
    print("seeded empty Bnei Brak and Hof Ashkelon tenants with role users and no sample data")


def add_hof_ashkelon() -> None:
    """Add the Hof Ashkelon tenant to an existing install without touching anything else."""
    run_migrations()
    with Session(engine) as s:
        changed = ensure_hof_ashkelon(s)
        s.commit()
    print("added Hof Ashkelon tenant" if changed else "Hof Ashkelon tenant already present")


def seed(reset: bool = False, samples: bool = True) -> None:
    if reset:
        drop_everything()
        if settings.storage_dir.exists():
            shutil.rmtree(settings.storage_dir)
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if not samples:
        seed_empty()
        return
    run_migrations()
    if not FIX.exists():
        raise SystemExit("fixtures missing — run: python scripts/make_fixtures.py")
    with Session(engine) as s:
        if s.get(Municipality, "demo"):
            print("already seeded (use --reset)")
            return
        s.add_all([Municipality(id="demo", name_he="סביבת הדגמה (נתונים פיקטיביים)", is_demo=True),
                   Municipality(id="bnei-brak", name_he="עיריית בני ברק", is_demo=False)])
        s.flush()
        s.add_all([User(id=i, tenant_id=t, display_name=n, role=r) for i, t, n, r in USERS])
        ensure_hof_ashkelon(s)
        s.flush()
        for spec in CASES:
            spec = dict(spec)
            files = spec.pop("files")
            c = PermitCase(tenant_id="demo", is_demo=True, sla_due=services.sla_default(), **spec)
            s.add(c)
            s.flush()
            audit.record(s, "demo", "u-secretary", "case.create", "permit_case", c.id,
                         {"case_number": c.case_number, "permit_type": c.permit_type})
            for fname, dtype in files:
                services.ingest_file(s, c, fname, (FIX / fname).read_bytes(), dtype, "u-secretary")
            s.flush()
            s.refresh(c)
            services.run_checks(s, c, "u-reviewer")
        s.commit()
    print("seeded demo tenant with", len(CASES), "fictitious cases")


if __name__ == "__main__":
    if "--add-hof-ashkelon" in sys.argv:
        add_hof_ashkelon()
    else:
        seed(reset="--reset" in sys.argv, samples="--no-samples" not in sys.argv)
