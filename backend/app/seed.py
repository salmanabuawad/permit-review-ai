"""Create schema + demo tenant/users/cases from fixtures. `python -m app.seed --reset`

Tenants:
  demo       — is_demo=True; fictitious cases; DEMO_FIXTURE rules are active here only.
  bnei-brak  — real tenant, intentionally EMPTY (no invented case data).
"""
from __future__ import annotations

import shutil
import sys

from sqlalchemy.orm import Session

from . import services
from .config import ROOT, settings
from .db import Base, engine
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
                   "unbuilt_floor_railing_height_m": 1.0},
         files=[("case1_extension_exceeds.dxf", "architectural_plan"), ("case1_area_table.xlsx", "area_table"),
                ("application_form.pdf", "application_form"), ("survey_map.pdf", "survey_map"),
                ("permit_info.pdf", "permit_info")]),
    dict(case_number="DEMO-0002", title="[הדגמה] הרחבת דירה תקינה בתוך קווי הבניין",
         permit_type="addition_extension", applicable_plans=["DEMO/1"], zone="residential_B",
         gush="DEMO", helka="2", address="רחוב הדגמה 2 (פיקטיבי)", assigned_to="u-reviewer2",
         declared={"multi_floor_addition": False, "has_unbuilt_floor_in_wing": False},
         files=[("case2_extension_ok.dxf", "architectural_plan"), ("case2_area_table.xlsx", "area_table"),
                ("application_form.pdf", "application_form"), ("survey_map.pdf", "survey_map"),
                ("permit_info.pdf", "permit_info"), ("photos.pdf", "existing_building_photos"),
                ("master_plan.pdf", "building_master_plan")]),
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


def seed(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
        if settings.storage_dir.exists():
            shutil.rmtree(settings.storage_dir)
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
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
        s.flush()
        for spec in CASES:
            spec = dict(spec)
            files = spec.pop("files")
            c = PermitCase(tenant_id="demo", is_demo=True, sla_due=services.sla_default(), **spec)
            s.add(c)
            s.flush()
            for fname, dtype in files:
                services.ingest_file(s, c, fname, (FIX / fname).read_bytes(), dtype, "u-secretary")
            s.flush()
            s.refresh(c)
            services.run_checks(s, c, "u-reviewer")
        s.commit()
    print("seeded demo tenant with", len(CASES), "fictitious cases")


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
