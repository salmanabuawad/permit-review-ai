import datetime as dt
import json
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.seed import seed
from app.models import PermitCase, SourceCrawl, RegulatoryEntry
from app.source_monitor import service as S, fetch as F
from app.regulatory import EntryIn,save_entry,resolve_case,detect_conflicts
from app.plan_discovery import discover
from fastapi.testclient import TestClient
from app.main import app

GEO={'type':'Polygon','coordinates':[[[154000,613000],[154020,613000],[154020,613020],[154000,613020],[154000,613000]]]}
HEAD={'X-User':'u-ha-admin'}
@pytest.fixture
def env():
    seed(reset=True,samples=False)
    with TestClient(app) as c: yield c

def source(s,tenant='hof-ashkelon',actor='u-ha-admin'):
    from app.models import SourceSnapshot
    d=S.ingest_upload(s,tenant,actor,'source.txt',b'Applicable test provision for verified plot and height.','text/plain')
    s.flush();return s.scalars(select(SourceSnapshot).where(SourceSnapshot.document_id==d.id)).first().id

def entry(s,sid,**kw):
    data=dict(snapshot_id=sid,title='Test',clause='4.1',page=1,quote='Applicable test provision',effective_from='2020-01-01',scope='property',block='2832',parcel='27')
    data.update(kw);return save_entry(s,'hof-ashkelon','u-ha-admin',EntryIn(**data))

def test_scope_conflict_and_history(env):
    with SessionLocal() as s:
        sid=source(s)
        entry(s,sid,kind='parcel',geometry=GEO)
        a=entry(s,sid,component='parking',attribute='inner_height',unit='m',operator='<=',value=2.2)
        b=entry(s,sid,component='parking',attribute='inner_height',unit='m',operator='>=',value=2.5)
        entry(s,sid,component='parking',attribute='inner_height',unit='m',operator='<=',value=1,effective_from='2030-01-01')
        entry(s,sid,component='roof',attribute='height',unit='m',operator='<=',value=9,parcel='28')
        c=PermitCase(tenant_id='hof-ashkelon',case_number='reg-test',title='test',permit_type='new',gush='2832',helka='27',declared={'submission_date':'2026-01-01'},applicable_plans=[]);s.add(c);s.flush()
        r=resolve_case(s,c)
        assert len(r['conflicts'])==1 and r['conflicts'][0]['status']=='INCOMPATIBLE_LIMITS'
        assert {x['status'] for x in r['entries']}=={'APPLIES','NOT_APPLICABLE'}
        assert not r['coverage_complete']
        entry(s,sid,component='parking',attribute='inner_height',unit='m',operator='<=',value=2.8,replaces=[a.id])
        assert not resolve_case(s,c)['conflicts']
        s.commit()
        assert env.get('/api/cases/'+c.id+'/regulatory-resolution',headers=HEAD).status_code==200
        assert env.get('/api/cases/'+c.id+'/regulatory-resolution',headers={'X-User':'u-reviewer'}).status_code==404

def test_evidence_scope_and_missing_date(env):
    with SessionLocal() as s:
        sid=source(s)
        with pytest.raises(ValueError): entry(s,sid,quote='nonexistent source quote')
        with pytest.raises(LookupError): save_entry(s,'bnei-brak','u-reviewer',EntryIn(snapshot_id=sid,title='x',scope='authority',clause='1',page=1,quote='Applicable test provision',effective_from='2020-01-01'))
        entry(s,sid,scope='geometry',geometry=GEO,block=None,parcel=None,component='roof',attribute='height',operator='<=',unit='m',value=9)
        c=PermitCase(tenant_id='hof-ashkelon',case_number='unknown',title='test',permit_type='new',declared={},applicable_plans=['999-1234567']);s.add(c);s.flush()
        r=resolve_case(s,c);assert r['entries'][0]['status']=='UNRESOLVED';assert r['unresolved'];s.rollback()

def test_xplan_metadata_pagination():
    """Kept: an unreachable service is UNAVAILABLE, never an exception (full XPLAN tests: test_plan_discovery.py)."""
    r=discover(GEO,lambda url,*a:F.Fetched('blocked',url,403));assert r['status']=='UNAVAILABLE' and not r['coverage_complete']

def test_crawl_recovery_after_failure(env,monkeypatch):
    targets=[{'url':'https://test.example/a.txt','source_id':None,'title':None,'from':None},{'url':'https://test.example/b.txt','source_id':None,'title':None,'from':None}]
    monkeypatch.setattr(S,'register_targets',lambda *a:targets)
    monkeypatch.setattr(S,'allowed_hosts',lambda *a:{'test.example'})
    calls=[]
    def fail(url,*a):
        calls.append(url)
        if url.endswith('b.txt'): raise RuntimeError('simulated interruption')
        return F.Fetched('ok',url,200,'text/plain',b'first document')
    cid=S.start_crawl(SessionLocal,'hof-ashkelon','u-ha-admin',wait=True,fetcher=fail,sleep=lambda x:None)
    with SessionLocal() as s:
        c=s.get(SourceCrawl,cid);assert c.status=='failed';assert c.checkpoint['visited']==[targets[0]['url']]
    calls.clear()
    def ok(url,*a): calls.append(url);return F.Fetched('ok',url,200,'text/plain',b'second document')
    assert S.start_crawl(SessionLocal,'hof-ashkelon','u-ha-admin',wait=True,fetcher=ok,sleep=lambda x:None)==cid
    assert calls==[targets[1]['url']]
    with SessionLocal() as s:
        c=s.get(SourceCrawl,cid);assert c.status=='done';assert c.checkpoint is None;assert c.summary['checked']==2

def test_crawl_limit_checkpoint(env,monkeypatch):
    targets=[{'url':f'https://test.example/{i}.txt','source_id':None,'title':None,'from':None} for i in range(2)]
    cfg={**S.load_config(),'max_documents_per_crawl':1}
    monkeypatch.setattr(S,'load_config',lambda:cfg)
    monkeypatch.setattr(S,'register_targets',lambda *a:targets)
    monkeypatch.setattr(S,'allowed_hosts',lambda *a:{'test.example'})
    def ok(url,*a):return F.Fetched('ok',url,200,'text/plain',url.encode())
    cid=S.start_crawl(SessionLocal,'hof-ashkelon','u-ha-admin',wait=True,fetcher=ok,sleep=lambda x:None)
    with SessionLocal() as s: assert s.get(SourceCrawl,cid).status=='partial'
    assert S.start_crawl(SessionLocal,'hof-ashkelon','u-ha-admin',wait=True,fetcher=ok,sleep=lambda x:None)==cid
    with SessionLocal() as s: assert s.get(SourceCrawl,cid).status=='done'

def test_resume_only_on_demand_or_by_schedule(env,monkeypatch):
    """A partial crawl is never resumed on its own for an on-demand authority; a scheduled one goes on,
    and a failed scheduled crawl waits an hour before it is retried."""
    from app.models import Municipality
    targets=[{'url':f'https://test.example/{i}.txt','source_id':None,'title':None,'from':None} for i in range(2)]
    cfg={**S.load_config(),'max_documents_per_crawl':1}
    monkeypatch.setattr(S,'load_config',lambda:cfg)
    monkeypatch.setattr(S,'register_targets',lambda *a:targets)
    monkeypatch.setattr(S,'allowed_hosts',lambda *a:{'test.example'})
    def ok(url,*a):return F.Fetched('ok',url,200,'text/plain',url.encode())
    cid=S.start_crawl(SessionLocal,'hof-ashkelon','u-ha-admin',wait=True,fetcher=ok,sleep=lambda x:None)
    assert S.queue_due(SessionLocal)==[]                       # on demand: stays partial
    with SessionLocal() as s:
        assert s.get(SourceCrawl,cid).status=='partial'
        org=s.get(Municipality,'hof-ashkelon');org.settings={**(org.settings or {}),'source_monitor':{'schedule':'daily'}};s.commit()
    assert S.queue_due(SessionLocal)==[cid]                    # scheduled: the same crawl resumes
    with SessionLocal() as s:
        c=s.get(SourceCrawl,cid);assert c.status=='queued' and c.checkpoint is not None
        c.status,c.finished_at='failed',dt.datetime.now(dt.timezone.utc);s.commit()
    assert S.queue_due(SessionLocal)==[]                       # failed just now: wait
    with SessionLocal() as s:
        c=s.get(SourceCrawl,cid);c.finished_at=dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=2);s.commit()
    assert S.queue_due(SessionLocal)==[cid]

def test_candidate_conflicts_not_active(env):
    from app.models import RuleDraft,SourceSnapshot,SourceDocument
    from app.regulatory import candidate_conflicts
    with SessionLocal() as s:
        for n in (2.2,2.5):
            doc=S.ingest_upload(s,'hof-ashkelon','u-ha-admin',f'parking-{n}.txt',f'parking test {n}'.encode(),'text/plain');s.flush()
            snap=s.scalars(select(SourceSnapshot).where(SourceSnapshot.document_id==doc.id)).first()
            s.add(RuleDraft(tenant_id='hof-ashkelon',document_id=doc.id,snapshot_id=snap.id,key=f'k-{n}',page=1,kind='numeric_limit',topics=['חניה'],text_he=f'גובה חניה לא יעלה על {n} מטר',values=[{'value':n,'unit':"מ'",'op':'<='}]))
        s.flush();out=candidate_conflicts(s,'hof-ashkelon');assert len(out)==1 and out[0]['status']=='POSSIBLE_CONFLICT_VERIFY_SCOPE'
        assert candidate_conflicts(s,'bnei-brak')==[]
        assert s.scalars(select(RegulatoryEntry)).all()==[]
        s.commit()
