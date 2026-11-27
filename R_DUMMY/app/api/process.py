"""API: Process360 — the case's workflow tasks, my tasks, overdue and escalations, bottlenecks, the authority's template."""
from fastapi import APIRouter

from .common import *  # noqa: F401,F403 — shared imports, schemas and helpers

router = APIRouter()


class TaskActIn(BaseModel):
    action: str                     # start | done | skip | assign
    note: str = ""
    assignee: str | None = None


class TemplateIn(BaseModel):
    name_he: str
    steps: list[dict]


@router.get("/api/cases/{case_id}/tasks")
def case_tasks(case_id: str, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    from .. import workflow as W
    from ..models import WorkflowTask
    c = get_case(s, p, case_id)
    return [W.task_dict(t) for t in s.scalars(select(WorkflowTask).where(WorkflowTask.case_id == c.id).order_by(WorkflowTask.id))]


@router.post("/api/cases/{case_id}/tasks/start")
def case_tasks_start(case_id: str, p: Principal = Depends(require("case.assign")), s: Session = Depends(get_session)):
    from .. import workflow as W
    c = get_case(s, p, case_id)
    if c.kind == "design":
        raise HTTPException(422, "לתכנון לפני הגשה אין תהליך רישוי")
    try:
        tasks = W.start(s, c, p.id)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    s.commit()
    return [W.task_dict(t) for t in tasks]


@router.post("/api/tasks/{task_id}")
def task_act(task_id: int, body: TaskActIn, p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    from .. import workflow as W
    from ..models import WorkflowTask
    t = s.get(WorkflowTask, task_id)
    if not t or t.tenant_id != p.tenant_id:
        raise HTTPException(404)
    get_case(s, p, t.case_id)
    if body.action == "assign" and not p.can("case.assign"):
        raise HTTPException(403, "אין הרשאה לשיוך")
    if body.action != "assign" and p.role not in (t.role, "sysadmin", "dept_manager"):
        raise HTTPException(403, "שלב זה מבוצע על ידי בעל התפקיד שלו")
    try:
        W.act(s, t, p.id, p.role, body.action, body.note, body.assignee)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    s.commit()
    return W.task_dict(t)


@router.get("/api/tasks")
def my_tasks(scope: str = "mine", p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    """mine: open tasks of my role or assigned to me; overdue: every overdue task of the authority."""
    from .. import workflow as W
    from ..models import WorkflowTask
    q = select(WorkflowTask, PermitCase).join(PermitCase, WorkflowTask.case_id == PermitCase.id).where(
        WorkflowTask.tenant_id == p.tenant_id, WorkflowTask.status.in_(("ready", "in_progress")))
    out = []
    for t, c in s.execute(q.order_by(WorkflowTask.due_at)):
        d = W.task_dict(t)
        if scope == "mine" and not (t.assignee == p.id or (t.assignee is None and t.role == p.role)):
            continue
        if scope == "overdue" and not d["overdue"]:
            continue
        out.append({**d, "case_number": c.case_number, "case_title": c.title})
    return out


@router.get("/api/workflow/bottlenecks")
def workflow_bottlenecks(p: Principal = Depends(require("dashboard.read")), s: Session = Depends(get_session)):
    from .. import workflow as W
    return W.bottlenecks(s, p.tenant_id)


@router.get("/api/workflow/template")
def workflow_template(p: Principal = Depends(require("case.read")), s: Session = Depends(get_session)):
    from .. import workflow as W
    t = W.template_for(s, p.tenant_id)
    s.commit()
    return {"id": t.id, "name_he": t.name_he, "steps": t.steps}


@router.put("/api/workflow/template")
def workflow_template_save(body: TemplateIn, p: Principal = Depends(require("user.manage")), s: Session = Depends(get_session)):
    """A new active template version for the authority; running cases keep the tasks they started with."""
    from .. import workflow as W
    from ..models import WorkflowTemplate
    errs = W.validate_steps(body.steps)
    if errs:
        raise HTTPException(422, "; ".join(errs))
    for old in s.scalars(select(WorkflowTemplate).where(WorkflowTemplate.tenant_id == p.tenant_id, WorkflowTemplate.active.is_(True))):
        old.active = False
    t = WorkflowTemplate(tenant_id=p.tenant_id, name_he=body.name_he.strip() or "תהליך רישוי", steps=body.steps, active=True)
    s.add(t)
    s.flush()
    audit.record(s, p.tenant_id, p.id, "workflow.template", "workflow_template", str(t.id), {"steps": [x.get("key") for x in body.steps]})
    s.commit()
    return {"id": t.id}
