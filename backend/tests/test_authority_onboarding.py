import json
import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app.main import app
from app.seed import seed
from app.db import SessionLocal
from app.models import Municipality, User, CandidatePassage, SourceDocument, SourceSnapshot, RuleDraft
from app import authority_onboarding as A
from app.source_monitor import fetch as F, service as S

ADMIN={'X-User':'u-ha-admin'}

@pytest.fixture
def client(monkeypatch):
    seed(reset=True,samples=False)
    monkeypatch.setenv('BBP_AUTHORITY_CREATORS','["u-ha-admin"]')
    monkeypatch.delenv('BBP_AUTHORITY_CATALOG',raising=False)
    def fake_start(factory,tenant,actor):
        A.start_onboarding_real(factory,tenant,actor,wait=True,fetcher=fake_fetch,sleep=lambda _:None)
    monkeypatch.setattr(A,'start_onboarding_real',A.start_onboarding,raising=False)
    monkeypatch.setattr(A,'start_onboarding',fake_start)
    with TestClient(app) as c: yield c

SITE='https://planning.example.org/'
PAGE=SITE+'guidelines'
DOC=SITE+'guidelines.pdf'

def pdf():
    d=pymupdf.open();p=d.new_page();p.insert_text((30,30),'Test regulation 29 metres');data=d.tobytes();d.close();return data

def fake_fetch(url,cfg,hosts,*args):
    if 'local_committees_1' in url:
        return F.Fetched('ok',url,200,'text/html',('<table><tr><td>רשות בדיקה</td><td><a href="'+SITE+'">אתר הוועדה</a></td></tr></table>').encode())
    if url==SITE: return F.Fetched('ok',url,200,'text/html',('<a href="'+PAGE+'">הנחיות מרחביות</a>').encode())
    if url==PAGE: return F.Fetched('ok',url,200,'text/html',('<a href="'+DOC+'">הנחיות בנייה</a>').encode())
    if url==DOC: return F.Fetched('ok',url,200,'application/pdf',pdf())
    return F.Fetched('blocked',url,403,message='blocked')


def create(c):
    r=c.post('/api/authorities',headers=ADMIN,json={'id':'test-city','name_he':'רשות בדיקה'});assert r.status_code==201,r.text
    return {**ADMIN,'X-Authority':'test-city'}

def test_discovery_and_selection(client):
    h=create(client)
    data=client.get('/api/authorities',headers=ADMIN).json()
    assert any(x['id']=='test-city' and x['onboarding']['state']=='CANDIDATES_READY' for x in data['authorities'])
    assert client.get('/api/me',headers=h).json()['tenant_id']=='test-city'
    assert client.get('/api/me',headers=ADMIN).json()['tenant_id']=='hof-ashkelon'
    assert client.get('/api/me',headers={**ADMIN,'X-Authority':'not-permitted'}).status_code==403
    assert any(x['title'] or x['url']==DOC for x in client.get('/api/source-monitor',headers=h).json()['documents'] if x['url']==DOC)
    assert client.get('/api/knowledge/candidates?q=29',headers=h).json()
    assert client.get('/api/knowledge/candidates?q=29',headers=ADMIN).json()==[]
    assert client.post('/api/authorities',headers=ADMIN,json={'id':'test-city','name_he':'רשות בדיקה'}).status_code==409

def test_upload_existing_and_new_and_dedup(client):
    h=create(client);data='גובה המבנה לא יעלה על 29 מטרים'.encode()
    def send(headers, content=data): return client.post('/api/source-monitor/upload',headers=headers,files={'file':('rule.txt',content,'text/plain')})
    a=send(h);assert a.status_code==200,a.text
    b=send(h);assert b.json()['id']==a.json()['id'];assert b.json()['change_state']=='unchanged'
    assert client.get('/api/knowledge/candidates?q=גובה',headers=h).json()
    assert client.get('/api/knowledge/candidates?q=גובה',headers=ADMIN).json()==[]
    c=send(ADMIN);assert c.status_code==200 and c.json()['id']!=a.json()['id']
    assert client.get('/api/source-monitor/documents/'+str(a.json()['id'])+'/file',headers=ADMIN).status_code==404
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(SourceSnapshot).where(SourceSnapshot.document_id==a.json()['id']))==1
    r=client.post('/api/source-monitor/upload',headers=h,files={'file':('bad.pdf',b'html','application/pdf')});assert r.status_code==422

def test_create_permission(client,monkeypatch):
    monkeypatch.setenv('BBP_AUTHORITY_CREATORS','[]')
    assert client.post('/api/authorities',headers=ADMIN,json={'id':'test-city','name_he':'רשות בדיקה'}).status_code==403

def test_exact_directory_match_and_ambiguity():
    h='<table><tr><td>רשות א</td><td><a href="https://a.example.org/">אתר</a></td></tr><tr><td>רשות אב</td><td><a href="https://b.example.org/">אתר</a></td></tr></table>'
    assert A.directory_links(h,'רשות א')==['https://a.example.org/']
    assert A.directory_links(h,'רשות')==[]
    assert not A.safe_url('https://127.0.0.1/');assert not A.safe_url('https://user@domain.org/')
    assert not F.public_target('http://127.0.0.1/')

def test_blocked_directory_is_not_success(monkeypatch):
    monkeypatch.delenv('BBP_AUTHORITY_CATALOG',raising=False)
    roots,errors,origin=A.discover('unknown','רשות בדיקה',lambda url,*a:F.Fetched('blocked',url,403),lambda _:None)
    assert not roots and len(errors)==6 and origin=='AMBIGUOUS_OR_NOT_FOUND'


def test_onboarding_job_is_durable_and_recovers_a_stale_lease():
    """A queued job survives a restart (it is a row state, not a thread); an expired lease is reclaimed; after
    MAX_ATTEMPTS the job fails visibly instead of staying pending."""
    from app import authority_onboarding as A
    from app.db import SessionLocal
    from app.models import Municipality
    with SessionLocal() as s:
        if not s.get(Municipality, 'durable-test'):
            s.add(Municipality(id='durable-test', name_he='רשות עמידות', is_demo=False, settings={}))
            s.commit()
    A.start_onboarding(SessionLocal, 'durable-test', 'u-admin')           # queued only — no thread
    with SessionLocal() as s:
        assert s.get(Municipality, 'durable-test').settings['onboarding']['state'] == 'DISCOVERY_PENDING'
    seen = set()
    while (t := A.claim_next(SessionLocal)) and t != 'durable-test':
        seen.add(t)                                                        # other tests' queued authorities
    assert t == 'durable-test'
    assert A.claim_next(SessionLocal) != 'durable-test'                     # leased: not claimed twice
    with SessionLocal() as s:
        ob = s.get(Municipality, 'durable-test').settings['onboarding']
        assert ob['state'] == 'DISCOVERING' and ob['attempts'] == 1 and ob['lease_until'] > A._now()
    for attempt in (2, 3):                                                 # the worker "dies": lease expires
        A._set(SessionLocal, 'durable-test', lease_until=A._now() - 1)
        while (t := A.claim_next(SessionLocal)) and t != 'durable-test':
            pass
        with SessionLocal() as s:
            ob = s.get(Municipality, 'durable-test').settings['onboarding']
        assert ob['attempts'] == attempt and ob['recovered'] is True
    A._set(SessionLocal, 'durable-test', lease_until=A._now() - 1)
    while (t := A.claim_next(SessionLocal)):
        assert t != 'durable-test', 'claimed beyond MAX_ATTEMPTS'
    with SessionLocal() as s:
        assert s.get(Municipality, 'durable-test').settings['onboarding']['state'] == 'FAILED'
