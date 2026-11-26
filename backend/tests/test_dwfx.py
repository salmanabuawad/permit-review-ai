"""DWFX drawings: accepted on upload, converted to PDF on the AI PC (never on the server), then shown and searched.

The DWFX here is a minimal XPS package built in the test: one fixed page with a rectangle and a Hebrew label stored
the way AutoCAD plots store it (visual order, i.e. reversed); the converted PDF must read it in logical order."""
import importlib.util
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.seed import seed

AGENT_DIR = Path(__file__).resolve().parents[2] / "agent"
TOKEN = "test-relay-token"


def make_dwfx(label_visual: str = "םירוגמ תיב") -> bytes:
    page = f"""<FixedPage xmlns="http://schemas.microsoft.com/xps/2005/06" Width="800" Height="600" xml:lang="he-IL">
  <Path Data="M 100,100 L 700,100 L 700,500 L 100,500 Z" Stroke="#FF000000" StrokeThickness="2"/>
  <Glyphs FontRenderingEmSize="24" OriginX="200" OriginY="300" UnicodeString="{label_visual}"
          FontUri="/font.ttf" Fill="#FF000000"/>
</FixedPage>"""
    font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="fdseq" ContentType="application/vnd.ms-package.xps-fixeddocumentsequence+xml"/>
  <Default Extension="fdoc" ContentType="application/vnd.ms-package.xps-fixeddocument+xml"/>
  <Default Extension="fpage" ContentType="application/vnd.ms-package.xps-fixedpage+xml"/>
  <Default Extension="ttf" ContentType="application/vnd.ms-opentype"/>
</Types>""")
        z.writestr("_rels/.rels", """<?xml version="1.0" encoding="utf-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Type="http://schemas.microsoft.com/xps/2005/06/fixedrepresentation" Target="/FixedDocumentSequence.fdseq" Id="R0"/>
</Relationships>""")
        z.writestr("FixedDocumentSequence.fdseq", """<FixedDocumentSequence xmlns="http://schemas.microsoft.com/xps/2005/06">
  <DocumentReference Source="/Documents/1/FixedDocument.fdoc"/></FixedDocumentSequence>""")
        z.writestr("Documents/1/FixedDocument.fdoc", """<FixedDocument xmlns="http://schemas.microsoft.com/xps/2005/06">
  <PageContent Source="/Documents/1/Pages/1.fpage"/></FixedDocument>""")
        z.writestr("Documents/1/Pages/1.fpage", page)
        if font.exists():
            z.writestr("font.ttf", font.read_bytes())
    return buf.getvalue()


def load_converter():
    spec = importlib.util.spec_from_file_location("dwfx_convert", AGENT_DIR / "dwfx_convert.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def client():
    seed(reset=True)
    old = settings.llm_relay_token
    object.__setattr__(settings, "llm_relay_token", TOKEN)     # settings is a frozen dataclass
    with TestClient(app) as c:
        yield c
    object.__setattr__(settings, "llm_relay_token", old)


def test_converter_renders_sheet_and_fixes_hebrew_order(tmp_path):
    conv = load_converter()
    src, dst = tmp_path / "plan.dwfx", tmp_path / "plan.pdf"
    src.write_bytes(make_dwfx())
    info = conv.convert(src, dst)
    assert info["sheets"][0]["width_pt"] == pytest.approx(800 * 0.75, rel=0.01)
    import pymupdf
    pdf = pymupdf.open(str(dst))
    assert pdf.page_count == 1 and pdf[0].get_images()
    if info["text_layer"] and info["sheets"][0]["words"]:
        assert "בית" in pdf[0].get_text() and "מגורים" in pdf[0].get_text()


def test_converter_rejects_classic_dwf(tmp_path):
    conv = load_converter()
    src = tmp_path / "old.dwf"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("manifest.xml", "<dwf/>")
        z.writestr("sheet.w2d", b"(W2D V06.00)")
    with pytest.raises(conv.NotDwfx):
        conv.convert(src, tmp_path / "x.pdf")


def test_dwfx_upload_is_queued_then_converted_by_the_agent(client, tmp_path):
    H = {"X-User": "u-secretary"}
    case = next(c for c in client.get("/api/cases", headers=H).json() if c["case_number"] == "DEMO-0004")
    data = make_dwfx()
    r = client.post(f"/api/cases/{case['id']}/files", headers=H, data={"doc_type": "architectural_plan"},
                    files={"file": ("PERMIT.dwfx", data)})
    assert r.status_code == 200, r.text
    f = next(x for x in r.json()["files"] if x["filename"] == "PERMIT.dwfx")
    assert f["kind"] == "dwfx" and f["ingest_status"] == "PENDING_CONVERSION"
    assert client.get(f"/api/files/{f['id']}/page/1.png", headers=H).status_code == 400   # nothing to show yet

    agent = {"Authorization": f"Bearer {TOKEN}"}
    assert client.post("/api/agent/conversions/next").status_code == 401                  # agent token required
    job = client.post("/api/agent/conversions/next", headers=agent).json()
    assert job["file_id"] == f["id"]
    assert client.post("/api/agent/conversions/next", headers=agent).status_code == 204   # claimed: not offered twice
    src = client.get(f"/api/agent/conversions/{f['id']}/source", headers=agent).content
    assert src == data

    (tmp_path / "in.dwfx").write_bytes(src)
    load_converter().convert(tmp_path / "in.dwfx", tmp_path / "out.pdf")          # what the AI PC does
    r = client.post(f"/api/agent/conversions/{f['id']}/result", headers={**agent, "X-Conversion-Status": "ok",
                    "Content-Type": "application/pdf"}, content=(tmp_path / "out.pdf").read_bytes())
    assert r.status_code == 200 and r.json()["ingest_status"] == "OK"
    png = client.get(f"/api/files/{f['id']}/page/1.png", headers=H)
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    files = client.get(f"/api/cases/{case['id']}", headers=H).json()["files"]
    rep = next(x for x in files if x["id"] == f["id"])["ingest_report"]
    assert rep["conversion"]["state"] == "done" and rep["page_count"] == 1
    assert client.post(f"/api/agent/conversions/{f['id']}/result", headers=agent, content=b"%PDF-").status_code == 410


def test_failed_conversion_is_reported_on_the_file(client):
    H = {"X-User": "u-secretary"}
    case = next(c for c in client.get("/api/cases", headers=H).json() if c["case_number"] == "DEMO-0003")
    r = client.post(f"/api/cases/{case['id']}/files", headers=H, data={"doc_type": "architectural_plan"},
                    files={"file": ("broken.dwfx", make_dwfx("א"))})
    fid = next(x for x in r.json()["files"] if x["filename"] == "broken.dwfx")["id"]
    agent = {"Authorization": f"Bearer {TOKEN}"}
    assert client.post("/api/agent/conversions/next", headers=agent).json()["file_id"] == fid
    r = client.post(f"/api/agent/conversions/{fid}/result", headers={**agent, "X-Conversion-Status": "failed"},
                    content="חבילת DWF ללא דפי XPS".encode())
    assert r.json()["ingest_status"] == "ERROR"
    f = next(x for x in client.get(f"/api/cases/{case['id']}", headers=H).json()["files"] if x["id"] == fid)
    assert "DWF" in f["ingest_report"]["warnings"][0]


def test_unsupported_extension_message_lists_dwfx(client):
    H = {"X-User": "u-secretary"}
    case = next(c for c in client.get("/api/cases", headers=H).json() if c["case_number"] == "DEMO-0004")
    r = client.post(f"/api/cases/{case['id']}/files", headers=H, data={"doc_type": "other"},
                    files={"file": ("x.jpg", b"\xff\xd8\xff")})
    assert r.status_code == 422 and "DWFX" in r.json()["detail"]


def test_unconverted_drawing_never_confirms_missing_sheets(client):
    """V9: a DWFX still waiting for the AI PC may contain the sections and elevations — their absence is NOT_CHECKED,
    not a confirmed defect, until the drawing is converted."""
    H = {"X-User": "u-secretary"}
    cid = client.post("/api/cases", headers=H, json={"case_number": "V9-PEND-1", "title": "t", "permit_type": "addition_extension",
                                                     "applicable_plans": ["DEMO/1"], "zone": "residential_B"}).json()["id"]
    client.post(f"/api/cases/{cid}/files", headers=H, data={"doc_type": "architectural_plan"},
                files={"file": ("PLAN-PENDING.dwfx", make_dwfx("א ב"))})
    run = client.post(f"/api/cases/{cid}/run", headers={"X-User": "u-reviewer"}).json()["run_id"]
    rep = client.get(f"/api/runs/{run}/report/reviewer", headers={"X-User": "u-reviewer"}).json()
    by = {f["rule_id"]: f for f in rep["findings"]}
    for rid in ("QA-REQ-SECTIONS", "QA-REQ-ELEVATIONS"):
        assert by[rid]["status"] != "FAIL" and "STATUS_CONFIRMED_DEFECT" not in by[rid]["flags"], rid
        assert "STATUS_NOT_CHECKED" in by[rid]["flags"]


def test_single_read_height_never_confirms_a_violation():
    """339-340: ridge read twice +6.85, one stray reading +13.20 — the excess is UNRESOLVED, not a confirmed defect;
    a corroborated value above the limit still fails."""
    from types import SimpleNamespace as NS
    from app.services import guard_single_read_height
    rules = [NS(id="HA-633-HEIGHT", check={"operand": "declared.building_height_m"})]
    r = NS(rule_id="HA-633-HEIGHT", status="FAIL", computed_result="FAIL", threshold=9.0, explanation_he="", flags=[])
    facts = {"building_height_m": 13.2, "building_height_corroborated_m": 6.85}
    assert guard_single_read_height([r], rules, facts, {}) == 1
    assert r.status == "UNCERTAIN" and "REVIEW:UNRESOLVED" in r.flags and "+13.20" in r.explanation_he
    r2 = NS(rule_id="HA-633-HEIGHT", status="FAIL", computed_result="FAIL", threshold=9.0, explanation_he="", flags=[])
    assert guard_single_read_height([r2], rules, {"building_height_m": 13.2, "building_height_corroborated_m": 9.6}, {}) == 0
    assert r2.status == "FAIL"
    assert guard_single_read_height([r2], rules, facts, {"building_height_m": 13.2}) == 0      # declared: not ours


def test_geometric_height_settles_a_stray_reading():
    """339-340: labels +6.85 (twice), one stray +13.20, section geometry 6.32 m — both independent sources are under
    9 m, so the height passes on measured evidence; geometry above the limit never passes."""
    from types import SimpleNamespace as NS
    from app.services import guard_single_read_height
    rules = [NS(id="HA-633-HEIGHT", check={"operand": "declared.building_height_m"})]
    mk = lambda: NS(rule_id="HA-633-HEIGHT", status="FAIL", computed_result="FAIL", threshold=9.0, explanation_he="",
                    flags=["NEEDS_DRAWING_READ"], evidence=[])
    r = mk()
    facts = {"building_height_m": 13.2, "building_height_corroborated_m": 6.85, "building_height_geometric_m": 6.32,
             "building_height_geometric_u_m": 0.124}
    assert guard_single_read_height([r], rules, facts, {}) >= 1
    assert r.status == "PASS" and "MEASURED" in r.flags and "+13.20" in r.explanation_he and "6.32" in r.explanation_he
    r2 = mk()
    guard_single_read_height([r2], rules, {**facts, "building_height_geometric_m": 9.5}, {})
    assert r2.status == "UNCERTAIN"                                   # geometry over the limit: never a pass
    r3 = mk()
    guard_single_read_height([r3], rules, {k: v for k, v in facts.items() if "geometric" not in k}, {})
    assert r3.status == "UNCERTAIN"                                   # no geometry: the stray read stays unresolved
