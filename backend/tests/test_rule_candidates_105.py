"""Bnei Brak 105 package: sources are registered with provenance, candidates are never enforced,
and re-importing changes nothing (reports/105_reconciliation_report.md)."""
import dataclasses
import importlib.util
import re
from pathlib import Path

import pytest
import yaml

from app import knowledge
from app.config import settings
from app.services import file_rules_for_tenant

ROOT = Path(__file__).resolve().parents[2]
KN = ROOT / "knowledge"
CANDIDATES = yaml.safe_load((KN / "rule_candidates" / "bb_105.yaml").read_text(encoding="utf-8"))["candidates"]
SOURCES_105 = yaml.safe_load((KN / "sources.d" / "bb_105.yaml").read_text(encoding="utf-8"))["sources"]


def _importer():
    spec = importlib.util.spec_from_file_location("import_105_package", ROOT / "scripts" / "import_105_package.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_package_sources_are_registered_with_provenance():
    sources = knowledge.load_sources()
    assert len(SOURCES_105) == 16
    for s in SOURCES_105:
        assert sources[s["id"]] == s
        assert re.fullmatch(r"[0-9a-f]{64}", s["sha256"])
        assert s["verification"] in ("OCR_UNVERIFIED", "FOUND_NOT_READ")
        assert s["plan_number_verified"] is False
        assert s["legal_status_verified"] is False and s["geography_verified"] is False
        assert s["related_source"] in sources          # linked to the existing LISTING_ONLY entry, which is unchanged
    assert sources["MAVAT-BB-105"]["verification"] == "LISTING_ONLY"


def test_every_ocr_page_listed_by_a_source_exists():
    ocr = KN / "source_texts" / "bb_105" / "ocr"
    for s in SOURCES_105:
        if s.get("ocr_pages"):
            assert len(list(ocr.glob(Path(s["file_name"]).stem + "_p*.txt"))) == s["ocr_pages"]


def test_candidates_are_never_enforced():
    rule_ids = {r.id for t in ("bnei-brak", "demo") for r in file_rules_for_tenant(t)}
    in_rule_files = "\n".join(p.read_text(encoding="utf-8") for p in (KN / "rules").glob("*.yaml"))
    assert len(CANDIDATES) == 15
    for c in CANDIDATES:
        assert c["enforcement_enabled"] is False
        assert c["verification_status"] == "CANDIDATE_UNVERIFIED"
        assert c["id"] not in rule_ids and c["id"] not in in_rule_files


def test_candidates_cite_a_registered_page_and_their_value_appears_in_the_evidence():
    sources = knowledge.load_sources()
    for c in CANDIDATES:
        src = sources[c["source"]["source_id"]]
        assert 1 <= c["source"]["page"] <= src["pages"]
        # an OCR digit slip between the extracted value and the quoted evidence must not go unnoticed
        numbers = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", c["source"]["ocr_evidence_he"])}
        assert float(c["candidate_value"]) in numbers, c["id"]


def test_conflicting_roof_setback_keeps_both_sources():
    r011 = next(c for c in CANDIDATES if c["id"] == "BB-105-CAND-R011")
    assert r011["status"] == "NEEDS_REVIEW" and r011["reconciliation"] == "CONFLICT"
    assert "BB-POL26-RR-SETBACK" in r011["related_existing"]
    assert "BB-POL26-RR-SETBACK" in {r.id for r in file_rules_for_tenant("bnei-brak")}
    assert all(c["status"] == "NEEDS_REVIEW" for c in CANDIDATES if c["reconciliation"] in ("CONFLICT", "NEEDS_REVIEW"))


def test_reimport_adds_nothing():
    imp = _importer()
    ocr_dir = KN / "source_texts" / "bb_105" / "ocr"
    stored_ocr = {p.name: p.read_text(encoding="utf-8") for p in ocr_dir.glob("*.txt")}
    new_src, new_ocr, changed_ocr, new_cand = imp.pending(SOURCES_105, stored_ocr, CANDIDATES)
    assert (new_src, new_ocr, changed_ocr, new_cand) == ([], {}, [], [])


def test_duplicate_source_id_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "sources.d").mkdir()
    (tmp_path / "sources.yaml").write_text("sources:\n  - {id: X, title_he: a}\n", encoding="utf-8")
    (tmp_path / "sources.d" / "extra.yaml").write_text("sources:\n  - {id: X, title_he: b}\n", encoding="utf-8")
    monkeypatch.setattr(knowledge, "settings", dataclasses.replace(settings, knowledge_dir=tmp_path))
    knowledge.load_sources.cache_clear()
    try:
        with pytest.raises(ValueError, match="duplicate source id X"):
            knowledge.load_sources()
    finally:
        monkeypatch.undo()
        knowledge.load_sources.cache_clear()
