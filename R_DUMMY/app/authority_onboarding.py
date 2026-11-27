"""Authority membership and candidate discovery; no automatic legal approval."""
from __future__ import annotations
import json, os, re, uuid, time, unicodedata, hashlib
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin
from sqlalchemy import select
from .models import Municipality, User, AuthorityMembership

DIRECTORY='https://www.gov.il/he/pages/local_committees_1'

def can_create(user):
    """Superadmin: a login listed in BBP_SUPERADMINS (or the older BBP_AUTHORITY_CREATORS)."""
    from .security import superadmin_ids
    return user.role=='sysadmin' and user.id in superadmin_ids()

def member(s,user,tenant):
    if not tenant or tenant==user.tenant_id: return user
    m=s.get(AuthorityMembership,(user.id,tenant))
    a=s.get(User,m.actor_id) if m and m.active is not False else None
    return a if a and a.tenant_id==tenant else None

def workspaces(s,user):
    ids=[user.tenant_id]+list(s.scalars(select(AuthorityMembership.tenant_id).where(AuthorityMembership.account_id==user.id,AuthorityMembership.active.is_not(False))))
    return [dict(id=t,name_he=o.name_he,role=a.role,onboarding=(o.settings or {}).get('onboarding',{})) for t in dict.fromkeys(ids) if (a:=member(s,user,t)) and (o:=s.get(Municipality,t))]

def catalog():
    path=os.environ.get('BBP_AUTHORITY_CATALOG')
    data=json.loads(Path(path).read_text(encoding='utf-8')) if path else {}
    if not isinstance(data,dict): raise ValueError('invalid authority catalog')
    return data

def safe_url(u):
    try:
        p=urlsplit(u); h=p.hostname or ''
        return p.scheme=='https' and not p.username and not p.password and p.port in (None,443) and bool(re.fullmatch(r'[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',h)) and not h.endswith(('.local','.internal','.localhost'))
    except (ValueError,TypeError): return False

def seeds_for(tenant):
    return list(dict.fromkeys(u for u in catalog().get(tenant,{}).get('official_urls',[]) if safe_url(u)))

def authority_id(name):
    matches=[key for key,item in catalog().items() if norm(item.get('name_he',''))==norm(name)]
    if len(matches)==1: return matches[0]
    return 'authority-'+hashlib.sha256(norm(name).encode()).hexdigest()[:16]


def create_authority(s,account,tenant,name):
    if not can_create(account): raise PermissionError('אין הרשאה לפתיחת רשות')
    tenant=tenant or authority_id(name)
    if not re.fullmatch(r'[a-z][a-z0-9-]{2,39}',tenant) or not name.strip() or len(name.strip())>200: raise ValueError('מזהה או שם רשות אינו תקין')
    if s.get(Municipality,tenant) or any(norm(o.name_he)==norm(name) for o in s.scalars(select(Municipality))): raise FileExistsError('הרשות כבר קיימת — נדרשת הרשאה של מנהל המערכת')
    item=catalog().get(tenant,{})
    if item and name.strip()!=item.get('name_he',name.strip()): raise ValueError('שם הרשות אינו תואם לקטלוג')
    org=Municipality(id=tenant,name_he=name.strip(),is_demo=False,settings={'onboarding':{'state':'DISCOVERY_PENDING','knowledge_verified':False},'official_urls':[]})
    s.add(org);s.flush()
    actor=User(id=uuid.uuid4().hex,tenant_id=tenant,display_name=account.display_name,role='sysadmin')
    s.add(actor);s.flush();s.add(AuthorityMembership(account_id=account.id,tenant_id=tenant,actor_id=actor.id));s.flush()
    return org,actor

class Rows(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True);self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr': self.row=[]
        if tag in ('td','th') and self.row is not None: self.cell=['',[]]
        if tag in ('br','li') and self.cell is not None: self.cell[0]+='\n'
        if tag=='a' and self.cell is not None: self.cell[1].append(dict(attrs).get('href',''))
    def handle_data(self,data):
        if self.cell is not None: self.cell[0]+=' '+data
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None: self.row.append(self.cell);self.cell=None
        if tag=='tr' and self.row is not None: self.rows.append(self.row);self.row=None

def norm(s):
    s=unicodedata.normalize('NFKC',s)
    s=re.sub(r'^(עיריית|עירית|מועצה מקומית|מועצה אזורית|עירייה|ועדה מקומית|ועדה מרחבית)\s+','',s.strip())
    return re.sub(r'[^א-תa-z0-9]','',s.lower())

def directory_links(html,name):
    parser=Rows();parser.feed(html);result=[]
    # Exact cell/line match only; ambiguous matches are not auto-activated.
    for row in parser.rows:
        if not any(norm(c[0])==norm(name) or any(norm(x)==norm(name) for x in re.split(r'[,;\n]',c[0])) for c in row): continue
        links=[urljoin(DIRECTORY,u) for c in row for u in c[1]]
        links=[u for u in links if safe_url(u) and urlsplit(u).hostname not in ('www.gov.il','gov.il')]
        if links: result.append(tuple(sorted(set(links))))
    return list(result[0]) if len(set(result))==1 else []

def discover(tenant,name,fetcher=None,sleep=time.sleep):
    from .source_monitor import fetch as F
    roots=seeds_for(tenant)
    if roots: return roots,[],'ADMIN_CATALOG'
    fetcher=fetcher or F.fetch; errors=[];matches=[]
    cfg={'user_agent':'PermitReviewAI/1.0','max_bytes':5*1024**2,'timeout_s':12}
    for i in range(1,7):
        u=f'{DIRECTORY}?chapterIndex={i}'
        r=fetcher(u,cfg,{'www.gov.il'})
        if r.status=='ok':
            links=directory_links(F.decode_html(r.body),name)
            if links: matches.append(tuple(sorted(links)))
        else: errors.append({'url':u,'status':r.status})
        sleep(0.5)
    if len(set(matches))==1: return list(matches[0]),errors,'GOV_DIRECTORY'
    return [],errors,'AMBIGUOUS_OR_NOT_FOUND'

LEASE = 1800          # seconds a worker holds an authority's onboarding job
MAX_ATTEMPTS = 1      # on demand only: a failed or interrupted job is shown as FAILED and re-run by a user, never
                      # retried or resumed automatically
ACTIVE = ('DISCOVERY_PENDING', 'DISCOVERING', 'CRAWLING')


def _now():
    return time.time()


def _set(factory, tenant, **onboarding):
    with factory() as s:
        o = s.get(Municipality, tenant)
        if o:
            old = o.settings or {}
            o.settings = {**old, 'onboarding': {**old.get('onboarding', {}), **onboarding}}
            s.commit()


def start_onboarding(factory, tenant, actor, wait=False, fetcher=None, sleep=time.sleep):
    """Queue discovery + first crawl for an authority (a user's request). The job is a durable row state
    (DISCOVERY_PENDING), not a thread: the crawler claims it with a lease; one whose lease expired (the crawler died)
    is marked FAILED, never resumed on its own. wait=True runs it inline (tests, CLI)."""
    _set(factory, tenant, state='DISCOVERY_PENDING', knowledge_verified=False, actor=actor, attempts=0,
         lease_until=None, queued_at=_now())
    if wait:
        run_onboarding(factory, tenant, fetcher=fetcher, sleep=sleep)


def claim_next(factory):
    """The next authority whose onboarding is queued; one whose lease expired (worker died mid-job) becomes FAILED."""
    with factory() as s:
        for o in s.scalars(select(Municipality)):
            ob = (o.settings or {}).get('onboarding') or {}
            if ob.get('state') not in ACTIVE:
                continue
            if (ob.get('lease_until') or 0) > _now():
                continue                                   # held by a live job, or backing off before a retry
            attempts = int(ob.get('attempts') or 0) + 1
            if attempts > MAX_ATTEMPTS:
                o.settings = {**o.settings, 'onboarding': {**ob, 'state': 'FAILED', 'lease_until': None,
                                                           'error': ob.get('error') or 'INTERRUPTED'}}
                s.commit()
                continue
            o.settings = {**o.settings, 'onboarding': {**ob, 'state': 'DISCOVERING', 'attempts': attempts,
                                                       'lease_until': _now() + LEASE,
                                                       'recovered': ob.get('state') != 'DISCOVERY_PENDING'}}
            s.commit()
            return o.id
    return None


def run_onboarding(factory, tenant, fetcher=None, sleep=time.sleep):
    from .source_monitor import service
    try:
        with factory() as s:
            o = s.get(Municipality, tenant)
            name = o.name_he
            actor = ((o.settings or {}).get('onboarding') or {}).get('actor') or 'onboarding'
        _set(factory, tenant, state='DISCOVERING', lease_until=_now() + LEASE)
        roots, errors, origin = discover(tenant, name, fetcher, sleep)
        with factory() as s:
            o = s.get(Municipality, tenant); old = o.settings or {}
            o.settings = {**old, 'official_urls': list(dict.fromkeys(old.get('official_urls', []) + roots)),
                          'onboarding': {**old.get('onboarding', {}), 'state': 'CRAWLING' if roots else 'NEEDS_OFFICIAL_DIRECTORY',
                                         'knowledge_verified': False, 'discovery_source': origin, 'errors': errors,
                                         'official_seed_count': len(roots), 'lease_until': _now() + LEASE if roots else None}}
            s.commit()
        if roots:
            cid = service.start_crawl(factory, tenant, actor, wait=True, fetcher=fetcher, sleep=sleep)
            from .models import SourceCrawl, SourceDocument
            with factory() as s:
                c = s.get(SourceCrawl, cid); o = s.get(Municipality, tenant); old = o.settings or {}
                local_hosts = {urlsplit(u).netloc.lower() for u in roots}
                local_docs = [d for d in s.scalars(select(SourceDocument).where(SourceDocument.tenant_id == tenant))
                              if urlsplit(d.url).netloc.lower() in local_hosts and d.kind == 'document' and d.sha256
                              and d.fetch_status in ('ok', 'not_modified')]
                o.settings = {**old, 'onboarding': {**old.get('onboarding', {}),
                                                    'state': 'CANDIDATES_READY' if c.status == 'done' and local_docs else 'CRAWL_INCOMPLETE',
                                                    'crawl_id': cid, 'local_documents': len(local_docs), 'summary': c.summary,
                                                    'lease_until': None}}
                s.commit()
    except Exception as e:                                    # noqa: BLE001 — recorded; a user re-runs it
        _set(factory, tenant, state='FAILED', knowledge_verified=False, error=type(e).__name__, lease_until=None)


def worker(factory, interval_s=15.0):
    """Onboarding worker inside the app (BBP_ONBOARDING_WORKER=true, only without a separate crawler process)."""
    while True:
        try:
            t = claim_next(factory)
            if t:
                run_onboarding(factory, t)
                continue
        except Exception:                                     # noqa: BLE001 — the worker never dies
            pass
        time.sleep(interval_s)
