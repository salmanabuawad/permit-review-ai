"""Clean pilot install (`app.seed --reset --no-samples`): no sample data and no demo artefacts."""
from fastapi.testclient import TestClient

from app.main import app
from app.seed import seed

from .conftest import FIX


def test_no_samples_install_is_clean():
    seed(reset=True, samples=False)
    with TestClient(app) as c:
        H = {"X-User": "u-reviewer"}
        users = c.get("/api/users").json()
        assert users and {u["tenant_id"] for u in users} == {"bnei-brak", "hof-ashkelon"}
        assert not any("הדגמה" in u["display_name"] for u in users)
        assert c.get("/api/cases", headers=H).json() == []
        assert not any(r["id"].startswith("DEMO-") for r in c.get("/api/rules", headers=H).json())
        assert not any(s["category"] == "DEMO" for s in c.get("/api/sources", headers=H).json())
        assert c.get("/api/dashboard", headers={"X-User": "u-manager"}).status_code == 200

        # a real case on this tenant: demo rules never run, even if someone lists plan DEMO/1
        cid = c.post("/api/cases", headers={"X-User": "u-secretary"}, json={
            "case_number": "2026-0001", "title": "הרחבת דירה", "permit_type": "addition_extension",
            "applicable_plans": ["DEMO/1"]}).json()["id"]
        c.post(f"/api/cases/{cid}/files", headers={"X-User": "u-secretary"},
               files={"file": ("plan.dxf", (FIX / "case1_extension_exceeds.dxf").read_bytes())},
               data={"doc_type": "architectural_plan"})
        run = c.post(f"/api/cases/{cid}/run", headers=H).json()
        rep = c.get(f"/api/runs/{run['run_id']}/report/reviewer", headers=H).json()
        assert rep["case"]["is_demo"] is False
        assert not any(f["rule_id"].startswith("DEMO-") for f in rep["findings"])
