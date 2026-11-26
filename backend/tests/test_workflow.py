"""Process360: dependencies, roles, legally required decisions, SLA / escalation, bottlenecks, template validation."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import workflow as W
from app.db import SessionLocal
from app.main import app
from app.models import WorkflowTask
from app.seed import seed


def H(u):
    return {"X-User": u}


@pytest.fixture(scope="module")
def client():
    seed(reset=True)
    with TestClient(app) as c:
        yield c


def _case(client):
    return next(c for c in client.get("/api/cases", headers=H("u-reviewer")).json() if c["case_number"] == "DEMO-0001")


def test_dependencies_roles_and_decisions(client):
    case = _case(client)
    assert client.post(f"/api/cases/{case['id']}/tasks/start", headers=H("u-reviewer")).status_code == 403
    tasks = client.post(f"/api/cases/{case['id']}/tasks/start", headers=H("u-manager")).json()
    assert [t["status"] for t in tasks if t["step"] == "intake"] == ["ready"]
    assert all(t["status"] == "waiting" for t in tasks if t["step"] != "intake")
    assert client.post(f"/api/cases/{case['id']}/tasks/start", headers=H("u-manager")).status_code == 409
    by = {t["step"]: t for t in tasks}
    assert client.post(f"/api/tasks/{by['completeness']['id']}", headers=H("u-reviewer"), json={"action": "start"}).status_code == 422
    assert client.post(f"/api/tasks/{by['intake']['id']}", headers=H("u-reviewer"), json={"action": "start"}).status_code == 403
    assert client.post(f"/api/tasks/{by['intake']['id']}", headers=H("u-secretary"), json={"action": "done"}).status_code == 200
    assert client.post(f"/api/tasks/{by['completeness']['id']}", headers=H("u-reviewer"), json={"action": "done"}).status_code == 200
    now = {t["step"]: t["status"] for t in client.get(f"/api/cases/{case['id']}/tasks", headers=H("u-reviewer")).json()}
    assert now["engineering"] == now["regulatory"] == now["external"] == "ready" and now["committee"] == "waiting"   # parallel
    assert client.post(f"/api/tasks/{by['engineering']['id']}", headers=H("u-reviewer"), json={"action": "start"}).status_code == 200
    for step, user in (("engineering", "u-reviewer"), ("regulatory", "u-reviewer"), ("external", "u-secretary")):
        assert client.post(f"/api/tasks/{by[step]['id']}", headers=H(user), json={"action": "done"}).status_code == 200
    cid = by["committee"]["id"]
    assert client.post(f"/api/tasks/{cid}", headers=H("u-reviewer"), json={"action": "done", "note": "אושר"}).status_code == 403
    assert client.post(f"/api/tasks/{cid}", headers=H("u-engineer"), json={"action": "done"}).status_code == 422   # needs a note
    assert client.post(f"/api/tasks/{cid}", headers=H("u-engineer"), json={"action": "skip", "note": "x x x"}).status_code == 422
    assert client.post(f"/api/tasks/{cid}", headers=H("u-engineer"), json={"action": "done", "note": "החלטה בישיבה 12"}).status_code == 200
    mine = client.get("/api/tasks", headers=H("u-secretary")).json()
    assert any(t["step"] == "conditions" for t in mine)


def test_overdue_escalation_and_bottlenecks(client):
    with SessionLocal() as s:
        t = s.query(WorkflowTask).filter(WorkflowTask.step_key == "conditions").first()
        t.ready_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=100)
        t.due_at = t.ready_at + dt.timedelta(days=t.sla_days)
        s.commit()
    od = client.get("/api/tasks?scope=overdue", headers=H("u-manager")).json()
    assert od and od[0]["step"] == "conditions" and od[0]["overdue"] and od[0]["escalated_to"] == "dept_manager"
    b = client.get("/api/workflow/bottlenecks", headers=H("u-manager")).json()
    assert b[0]["step"] == "conditions" and b[0]["overdue"] == 1
    assert any(x["avg_work_days"] is not None for x in b)


def test_template_validation(client):
    bad = [{"key": "a", "name_he": "א", "role": "reviewer", "depends_on": ["b"]}, {"key": "b", "name_he": "ב", "role": "reviewer", "depends_on": ["a"]}]
    assert any("מעגל" in e for e in W.validate_steps(bad))
    assert client.put("/api/workflow/template", headers=H("u-admin"), json={"name_he": "x", "steps": bad}).status_code == 422
    ok = [{"key": "a", "name_he": "א", "role": "reviewer", "sla_days": 2, "depends_on": []}]
    assert client.put("/api/workflow/template", headers=H("u-admin"), json={"name_he": "קצר", "steps": ok}).status_code == 200
    assert client.get("/api/workflow/template", headers=H("u-reviewer")).json()["name_he"] == "קצר"
