"""Process360: configurable permit workflow per authority — tasks, dependencies, SLAs, escalation, bottlenecks.

* A template is a list of steps {key, name_he, role, sla_days, depends_on, decision}. Steps without unmet
  dependencies are ready together (parallel); a step becomes ready when all its dependencies are done or skipped.
* A `decision` step (e.g. the committee decision, permit issuance) is a legally required act: only its role or a
  system administrator completes it, with a note — never the system.
* SLA: the due date is counted from when the step became ready. Overdue tasks escalate to the department manager when
  they pass twice their SLA. No fabricated progress: status is what people recorded.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .models import PermitCase, WorkflowTask, WorkflowTemplate

DEFAULT_STEPS = [
    {"key": "intake", "name_he": "קליטת הבקשה", "role": "secretariat", "sla_days": 3, "depends_on": []},
    {"key": "completeness", "name_he": "בדיקת שלמות מסמכים", "role": "reviewer", "sla_days": 7, "depends_on": ["intake"]},
    {"key": "engineering", "name_he": "בדיקה הנדסית", "role": "reviewer", "sla_days": 14, "depends_on": ["completeness"]},
    {"key": "regulatory", "name_he": "בדיקה תכנונית / רגולטורית", "role": "reviewer", "sla_days": 14, "depends_on": ["completeness"]},
    {"key": "external", "name_he": "אישורי גורמי חוץ", "role": "secretariat", "sla_days": 30, "depends_on": ["completeness"]},
    {"key": "committee", "name_he": "החלטת ועדה / רשות רישוי", "role": "city_engineer", "sla_days": 30,
     "depends_on": ["engineering", "regulatory", "external"], "decision": True},
    {"key": "conditions", "name_he": "מילוי תנאים להיתר", "role": "secretariat", "sla_days": 45, "depends_on": ["committee"]},
    {"key": "permit", "name_he": "הפקת היתר", "role": "city_engineer", "sla_days": 7, "depends_on": ["conditions"], "decision": True},
]
STATUS_HE = {"waiting": "ממתין לשלבים קודמים", "ready": "מוכן לביצוע", "in_progress": "בטיפול", "done": "הושלם", "skipped": "דולג"}


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def validate_steps(steps: list) -> list[str]:
    errs, keys = [], set()
    for i, st in enumerate(steps or []):
        k = st.get("key")
        if not k or k in keys:
            errs.append(f"שלב {i + 1}: מפתח חסר או כפול")
        keys.add(k)
        if not st.get("name_he") or not st.get("role"):
            errs.append(f"שלב {k}: חסר שם או תפקיד")
        if not isinstance(st.get("sla_days", 0), int) or st.get("sla_days", 0) < 0:
            errs.append(f"שלב {k}: SLA לא תקין")
    for st in steps or []:
        for d in st.get("depends_on") or []:
            if d not in keys:
                errs.append(f"שלב {st.get('key')}: תלות לא קיימת {d}")
    # no cycles
    graph = {st["key"]: list(st.get("depends_on") or []) for st in steps or [] if st.get("key")}
    seen, stack = set(), set()

    def visit(n):
        if n in stack:
            raise ValueError(n)
        if n in seen:
            return
        stack.add(n)
        for m in graph.get(n, []):
            visit(m)
        stack.discard(n)
        seen.add(n)
    try:
        for n in graph:
            visit(n)
    except ValueError as e:
        errs.append(f"מעגל תלויות סביב {e}")
    return errs


def template_for(s: Session, tenant: str) -> WorkflowTemplate:
    t = s.scalars(select(WorkflowTemplate).where(WorkflowTemplate.tenant_id == tenant, WorkflowTemplate.active.is_(True))
                  .order_by(WorkflowTemplate.id.desc())).first()
    if t is None:
        t = WorkflowTemplate(tenant_id=tenant, name_he="תהליך רישוי (ברירת מחדל)", steps=DEFAULT_STEPS, active=True)
        s.add(t)
        s.flush()
    return t


def start(s: Session, case: PermitCase, user: str) -> list[WorkflowTask]:
    if s.scalars(select(WorkflowTask).where(WorkflowTask.case_id == case.id)).first():
        raise ValueError("לתיק כבר קיים תהליך")
    t = template_for(s, case.tenant_id)
    tasks = [WorkflowTask(tenant_id=case.tenant_id, case_id=case.id, template_id=t.id, step_key=st["key"], name_he=st["name_he"],
                          role=st["role"], depends_on=list(st.get("depends_on") or []), decision=bool(st.get("decision")),
                          sla_days=int(st.get("sla_days") or 0), status="waiting") for st in t.steps]
    s.add_all(tasks)
    s.flush()
    _promote(tasks)
    audit.record(s, case.tenant_id, user, "workflow.start", "permit_case", case.id, {"template": t.id, "steps": len(tasks)})
    return tasks


def _promote(tasks: list[WorkflowTask]) -> None:
    done = {t.step_key for t in tasks if t.status in ("done", "skipped")}
    for t in tasks:
        if t.status == "waiting" and all(d in done for d in t.depends_on or []):
            t.status, t.ready_at = "ready", now()
            t.due_at = t.ready_at + dt.timedelta(days=t.sla_days) if t.sla_days else None


def act(s: Session, task: WorkflowTask, user: str, role: str, action: str, note: str = "", assignee: str | None = None) -> None:
    """start | done | skip | assign. Decisions need their role (or sysadmin) and a note."""
    tasks = list(s.scalars(select(WorkflowTask).where(WorkflowTask.case_id == task.case_id)))
    if action == "assign":
        task.assignee = assignee
    elif action == "start":
        if task.status != "ready":
            raise ValueError("ניתן להתחיל רק שלב שמוכן לביצוע (כל השלבים הקודמים הושלמו)")
        task.status, task.started_at, task.assignee = "in_progress", now(), task.assignee or user
    elif action in ("done", "skip"):
        if task.status not in ("ready", "in_progress"):
            raise ValueError("השלב אינו פתוח")
        if task.decision and role not in (task.role, "sysadmin"):
            raise PermissionError("החלטה זו מחייבת בעל תפקיד מוסמך")
        if (task.decision or action == "skip") and len(note.strip()) < 3:
            raise ValueError("נדרש נימוק")
        if task.decision and action == "skip":
            raise ValueError("החלטה מחויבת בדין אינה ניתנת לדילוג")
        task.status, task.done_at, task.done_by, task.note = ("done" if action == "done" else "skipped"), now(), user, note or None
        _promote(tasks)
    else:
        raise ValueError("פעולה לא מוכרת")
    audit.record(s, task.tenant_id, user, f"workflow.{action}", "workflow_task", str(task.id),
                 {"case_id": task.case_id, "step": task.step_key, "note": note, "assignee": assignee})
    s.flush()


def task_dict(t: WorkflowTask, at: dt.datetime | None = None) -> dict:
    at = at or now()
    overdue = bool(t.due_at and t.status in ("ready", "in_progress") and at > t.due_at)
    escalated = bool(overdue and t.sla_days and at > (t.ready_at + dt.timedelta(days=2 * t.sla_days)))
    return {"id": t.id, "case_id": t.case_id, "step": t.step_key, "name_he": t.name_he, "role": t.role, "status": t.status,
            "status_he": STATUS_HE[t.status], "decision": t.decision, "depends_on": t.depends_on, "assignee": t.assignee,
            "sla_days": t.sla_days, "ready_at": t.ready_at and t.ready_at.isoformat(), "started_at": t.started_at and t.started_at.isoformat(),
            "due_at": t.due_at and t.due_at.isoformat(), "done_at": t.done_at and t.done_at.isoformat(), "done_by": t.done_by,
            "note": t.note, "overdue": overdue, "escalated_to": "dept_manager" if escalated else None}


def bottlenecks(s: Session, tenant: str) -> list[dict]:
    """Per step: tasks open now, overdue, and average waiting (ready → started) and working (started → done) days."""
    out: dict[str, dict] = {}
    at = now()
    for t in s.scalars(select(WorkflowTask).where(WorkflowTask.tenant_id == tenant)):
        b = out.setdefault(t.step_key, {"step": t.step_key, "name_he": t.name_he, "open": 0, "overdue": 0, "wait": [], "work": []})
        d = task_dict(t, at)
        if t.status in ("ready", "in_progress"):
            b["open"] += 1
            b["overdue"] += d["overdue"]
        if t.ready_at and t.started_at:
            b["wait"].append((t.started_at - t.ready_at).total_seconds() / 86400)
        if t.started_at and t.done_at:
            b["work"].append((t.done_at - t.started_at).total_seconds() / 86400)
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
    return sorted(({**{k: v for k, v in b.items() if k not in ("wait", "work")}, "avg_wait_days": avg(b["wait"]),
                    "avg_work_days": avg(b["work"]), "samples": len(b["work"])} for b in out.values()),
                  key=lambda x: (-x["overdue"], -x["open"]))
