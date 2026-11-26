from types import SimpleNamespace
from app import knowledge, login
from app.defects_report import build_defects
from app.models import Municipality, User
from app.db import SessionLocal
from app.seed import seed
from app.main import app
from fastapi.testclient import TestClient
import datetime as dt


def test_jurisdiction_default_is_not_bnei_brak(monkeypatch):
    monkeypatch.setattr(knowledge, 'load_sources', lambda: {
        'legacy': {}, 'bb': {'jurisdiction': 'bnei-brak'}, 'ha': {'jurisdiction': 'hof-ashkelon'},
        'hf': {'jurisdiction': 'haifa'}, 'nat': {'jurisdiction': 'national'},
        'demo': {'jurisdiction': 'national', 'category': 'DEMO'}})
    assert set(knowledge.sources_for_tenant('haifa')) == {'hf', 'nat'}
    assert set(knowledge.sources_for_tenant('beit-shemesh')) == {'nat'}
    assert set(knowledge.sources_for_tenant('hof-ashkelon')) == {'ha', 'nat'}
    assert set(knowledge.sources_for_tenant('bnei-brak')) == {'legacy', 'bb', 'nat'}


def test_login_map_fails_closed(monkeypatch):
    monkeypatch.setenv('BBP_LOGIN_USER_MAP', '{"haifa":"hf-user","shemesh":"bs-user"}')
    assert login.resolve_login_user('haifa', 'legacy') == 'hf-user'
    assert login.resolve_login_user('unknown', 'legacy') is None
    monkeypatch.setenv('BBP_LOGIN_USER_MAP', 'invalid')
    assert login.resolve_login_user('haifa', 'legacy') is None
    monkeypatch.delenv('BBP_LOGIN_USER_MAP')
    assert login.resolve_login_user('legacy', 'legacy') == 'legacy'


def test_unknown_external_status_not_exported():
    case = SimpleNamespace(case_number='A', title='test', gush=None, helka=None, address=None, applicable_plans=[], tenant_id='haifa')
    f = SimpleNamespace(flags=['EXTERNAL','STATUS_UNRESOLVED'], evidence=[])
    run = SimpleNamespace(summary={}, findings=[f], version=1, started_at=dt.datetime.now(), input_hashes=[])
    rep = build_defects(case, run)
    assert rep['items'] == []
    assert rep['decision'] == 'INSUFFICIENT_EVIDENCE_FOR_FINAL_DECISION'


def test_new_authority_isolation_and_display():
    seed(reset=True, samples=False)
    with SessionLocal() as s:
        s.add(Municipality(id='haifa', name_he='עיריית חיפה', is_demo=False, settings={}))
        s.flush()
        s.add(User(id='hf-user', tenant_id='haifa', display_name='חיפה', role='sysadmin'))
        s.commit()
    with TestClient(app) as c:
        h = {'X-User': 'hf-user'}
        assert c.get('/api/me', headers=h).json()['municipality_name'] == 'עיריית חיפה'
        assert {u['tenant_id'] for u in c.get('/api/users', headers=h).json()} == {'haifa'}
        new = c.post('/api/cases', headers=h, json={'case_number':'HF-01','title':'Test','permit_type':'new_building'})
        assert new.status_code in (200, 201), new.text
        cid = new.json()['id']
        assert c.get('/api/cases/'+cid, headers={'X-User':'u-ha-admin'}).status_code == 404
        assert all(x['id'] != cid for x in c.get('/api/cases', headers={'X-User':'u-ha-admin'}).json())
