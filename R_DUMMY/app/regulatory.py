"""Tenant-scoped verified scope registry, parcel intersection and conflict audit.
Search results and drafts are candidates, never executable legal rules. Dates use a
half-open interval. Scope dimensions are ANDed; unknown facts never imply exclusion.
"""
from __future__ import annotations
import datetime as dt
import hashlib, json, math, re
from collections import defaultdict
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from shapely.geometry import shape
from sqlalchemy import select
from .models import RegulatoryEntry, SourceSnapshot, SourceDocument, CandidatePassage, ParcelPlanDiscovery

class EntryIn(BaseModel):
    snapshot_id: int
    kind: Literal['parcel','regulation'] = 'regulation'
    title: str = Field(min_length=1,max_length=300)
    plan: str | None = None
    clause: str = Field(min_length=1,max_length=200)
    page: int = Field(ge=1)
    quote: str = Field(min_length=5,max_length=4000)
    effective_from: dt.date
    effective_until: dt.date | None = None
    scope: Literal['authority','property','plan','geometry']
    block: str | None = None
    parcel: str | None = None
    lots: list[str] = Field(default_factory=list)
    uses: list[str] = Field(default_factory=list)
    geometry: dict | None = None  # EPSG:2039 polygon, explicitly reviewed
    component: str | None = None
    attribute: str | None = None
    unit: Literal['m','m2','percent','count'] | None = None
    operator: Literal['<=','>=','=='] | None = None
    value: float | None = None
    replaces: list[str] = Field(default_factory=list)
    @model_validator(mode='after')
    def check(self):
        if self.effective_until and self.effective_until <= self.effective_from: raise ValueError('invalid effective interval')
        if self.scope=='property' and not (self.block and self.parcel): raise ValueError('property scope needs block and parcel')
        if self.scope=='plan' and not self.plan: raise ValueError('plan scope needs plan identifier')
        if self.scope=='geometry' and not self.geometry: raise ValueError('geometry scope needs geometry')
        if self.geometry is not None: polygon(self.geometry)
        if self.kind=='parcel' and (self.scope!='property' or not self.geometry or self.operator or self.replaces): raise ValueError('parcel needs property scope and geometry, no limit')
        fields=[self.component,self.attribute,self.unit,self.operator,self.value]
        if any(v is not None for v in fields) and not all(v is not None for v in fields): raise ValueError('limit requires all five fields')
        if self.value is not None and (not math.isfinite(self.value) or self.value<0): raise ValueError('invalid value')
        return self

def polygon(geo):
    g=shape(geo)
    if g.geom_type not in ('Polygon','MultiPolygon') or g.is_empty or not g.is_valid or not math.isfinite(g.area) or g.area<=0: raise ValueError('invalid parcel polygon')
    x,y,X,Y=g.bounds
    if not (0<=x<X<=400000 and 250000<=y<Y<=900000): raise ValueError('expected Israeli grid EPSG:2039')
    return g

def digest(data): return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def norm(s): return re.sub(r'[\s"״׳\']','',str(s or '')).replace('–','-').replace('־','-')
def date(s):
    try: return dt.date.fromisoformat(str(s))
    except (ValueError,TypeError): return None

def save_entry(s,tenant,actor,body:EntryIn):
    snap=s.get(SourceSnapshot,body.snapshot_id)
    doc=s.get(SourceDocument,snap.document_id) if snap else None
    if not snap or snap.tenant_id!=tenant or not doc or doc.tenant_id!=tenant: raise LookupError('source not found')
    # Match actual extracted evidence. A scanned source needs OCR/review ingestion first.
    passages=s.scalars(select(CandidatePassage).where(CandidatePassage.tenant_id==tenant,CandidatePassage.snapshot_id==snap.id,CandidatePassage.page==body.page)).all()
    if not any(norm(body.quote) in norm(p.text_he) for p in passages): raise ValueError('quote not present in extracted source page')
    data=body.model_dump(mode='json'); data['source_sha256']=snap.sha256;data['source_url']=doc.url
    for rid in body.replaces:
        old=s.get(RegulatoryEntry,rid)
        if not old or old.tenant_id!=tenant: raise LookupError('replaced entry not found')
        if any(old.data.get(k)!=data.get(k) for k in ('component','attribute','unit','operator')) or not body.operator: raise ValueError('replacement must name same limit')
    rows=s.scalars(select(RegulatoryEntry).where(RegulatoryEntry.tenant_id==tenant)).all()
    for r in rows:
        if r.data==data: return r
    row=RegulatoryEntry(tenant_id=tenant,snapshot_id=snap.id,data=data,approved_by=actor);s.add(row);s.flush();return row

def serial(row): return {'id':row.id,**row.data,'approved_by':row.approved_by,'approved_at':row.approved_at.isoformat()}

def property_context(s,case):
    d=case.declared or {};ref=date(d.get('submission_date'));lot=d.get('lot') or d.get('plot'); use=d.get('main_use')
    rows=s.scalars(select(RegulatoryEntry).where(RegulatoryEntry.tenant_id==case.tenant_id)).all()
    def in_time(r):
        a=r.data; return ref is not None and date(a['effective_from'])<=ref and (not a.get('effective_until') or ref<date(a['effective_until']))
    parcels=[r for r in rows if r.data['kind']=='parcel' and norm(r.data['block'])==norm(case.gush) and norm(r.data['parcel'])==norm(case.helka) and in_time(r)]
    geos={digest(r.data['geometry']):r.data['geometry'] for r in parcels}
    geo=next(iter(geos.values())) if len(geos)==1 else None
    return rows,ref,lot,use,geo

def resolve_case(s,case):
    rows,ref,lot,use,geo=property_context(s,case);g=polygon(geo) if geo else None
    plans={norm(p) for p in (case.applicable_plans or []) if isinstance(p,str)}
    unresolved=[]; entries=[]; limits=[]
    if not ref: unresolved.append('Missing submission date')
    if not g: unresolved.append('Missing or ambiguous verified parcel geometry')
    discovery=s.get(ParcelPlanDiscovery,case.id)
    candidate={'status':'NOT_DISCOVERED','plans':[]}
    if discovery and discovery.tenant_id==case.tenant_id and discovery.state=='done':
        src=(discovery.result or {}).get('geometry_source') or {}
        # A discovery counts for the parcel it was run on: the verified parcel, or (no verified parcel) the plan cell.
        if (geo and discovery.parcel_hash==digest(geo)) or (not geo and src.get('kind') in ('PLAN_CELL_XPLAN','PARCEL_CADASTRE')):
            candidate={k:v for k,v in discovery.result.items() if k!='geometry'}
    for row in rows:
        a=row.data
        if a['kind']=='parcel': continue
        state='APPLIES';why=[]
        if not ref: state='UNRESOLVED';why.append('date unknown')
        elif ref<date(a['effective_from']) or (a.get('effective_until') and ref>=date(a['effective_until'])): state='NOT_APPLICABLE';why.append('date outside interval')
        checks=[]
        if a.get('block'): checks.append((case.gush,norm(a['block'])==norm(case.gush),'block'))
        if a.get('parcel'): checks.append((case.helka,norm(a['parcel'])==norm(case.helka),'parcel'))
        if a.get('lots'): checks.append((lot,norm(lot) in {norm(v) for v in a['lots']},'lot'))
        if a.get('uses'): checks.append((use,norm(use) in {norm(v) for v in a['uses']},'use'))
        for fact,match,label in checks:
            if not fact and state!='NOT_APPLICABLE': state='UNRESOLVED';why.append(label+' unknown')
            elif fact and not match: state='NOT_APPLICABLE';why.append(label+' outside scope')
        if a.get('geometry') and state!='NOT_APPLICABLE':
            area=polygon(a['geometry'])
            if g is None: state='UNRESOLVED';why.append('parcel geometry unknown')
            elif not area.intersects(g): state='NOT_APPLICABLE';why.append('outside boundary')
            elif not area.covers(g): state='UNRESOLVED';why.append('partial or boundary intersection')
        if a['scope']=='plan' and norm(a['plan']) not in plans and not a.get('geometry') and state!='NOT_APPLICABLE':
            state='UNRESOLVED';why.append('plan not independently linked to lot')
        # A declared plan alone is not independent evidence of legal geographic applicability.
        if a['scope']=='plan' and not a.get('geometry') and not (a.get('block') and a.get('parcel')) and state=='APPLIES':
            state='UNRESOLVED';why.append('plan declaration only')
        e={**serial(row),'status':state,'reason':why};entries.append(e)
        if state=='UNRESOLVED': unresolved.append(row.id+': '+', '.join(why))
        if state=='APPLIES' and a.get('operator'): limits.append(e)
    conflicts=detect_conflicts(limits)
    covered={norm(e['plan']) for e in entries if e.get('plan') and e['status']=='APPLIES'}
    for p in plans | {norm(x['plan']) for x in candidate.get('plans',[]) if x.get('plan')}:
        if p not in covered: unresolved.append('Plan applicability/source not verified: '+p)
    # Look up collected source text for candidate plan identifiers. A textual hit is not a verified plan document.
    candidate_documents={}
    for p in sorted(plans | {norm(x['plan']) for x in candidate.get('plans',[]) if x.get('plan')})[:50]:
        if not p or len(p)<4: continue
        hits=s.execute(select(CandidatePassage,SourceDocument,SourceSnapshot).join(SourceDocument,CandidatePassage.document_id==SourceDocument.id).join(SourceSnapshot,CandidatePassage.snapshot_id==SourceSnapshot.id).where(CandidatePassage.tenant_id==case.tenant_id,SourceDocument.tenant_id==case.tenant_id,SourceSnapshot.tenant_id==case.tenant_id,SourceDocument.sha256==SourceSnapshot.sha256,CandidatePassage.text_he.contains(p,autoescape=True)).limit(15)).all()
        candidate_documents[p]=[{'document_id':d.id,'snapshot_id':v.id,'title':d.title,'page':x.page,'sha256':v.sha256,'status':'TEXT_MATCH_UNVERIFIED'} for x,d,v in hits]
    # Never assert completeness: XPLAN lacks historical/non-digitized plans and scope evidence can be missing.
    return {'entries':entries,'conflicts':conflicts,'discovery':candidate,'candidate_documents':candidate_documents,'unresolved':unresolved,
            'coverage_complete':False,'coverage_note':'Historical, national, district, local and transitional sources require verified coverage; candidate search is not legal certification.'}

def detect_conflicts(limits):
    groups=defaultdict(list)
    for e in limits: groups[(e['component'],e['attribute'],e['unit'])].append(e)
    out=[]
    for key,ls in groups.items():
        # Replacements are explicit, approved and limited to the exact same operand; no guessing hierarchy.
        replaced={i for e in ls for i in e.get('replaces',[]) if any(x['id']==i for x in ls)}
        active=[e for e in ls if e['id'] not in replaced]
        if not active: out.append({'key':key,'status':'UNRESOLVED_REPLACEMENT','entries':ls});continue
        lo=max((e['value'] for e in active if e['operator'] in ('>=','==')),default=-math.inf)
        hi=min((e['value'] for e in active if e['operator'] in ('<=','==')),default=math.inf)
        values={(e['operator'],e['value']) for e in active}
        if lo>hi: status='INCOMPATIBLE_LIMITS'
        elif len(values)>1 and any(len({e['value'] for e in active if e['operator']==op})>1 for op in ('<=','>=','==')): status='DIFFERENT_LIMITS_REVIEW'
        else: continue
        out.append({'key':key,'status':status,'entries':active})
    return out


def candidate_conflicts(s,tenant):
    """Conservative heuristic for new/updated sources: identical clause wording except
    numeric token(s), one extracted numeric limit, different documents. Never a legal finding.
    Compare only latest snapshot drafts; no pairwise semantic guesses or auto activation.
    """
    from .models import RuleDraft
    rows=s.execute(select(RuleDraft,SourceDocument,SourceSnapshot).join(SourceDocument,RuleDraft.document_id==SourceDocument.id).join(SourceSnapshot,RuleDraft.snapshot_id==SourceSnapshot.id).where(RuleDraft.tenant_id==tenant,SourceDocument.tenant_id==tenant,SourceSnapshot.tenant_id==tenant,SourceDocument.sha256==SourceSnapshot.sha256,RuleDraft.status.in_(['open','for_authoring']),RuleDraft.kind=='numeric_limit')).all()
    groups=defaultdict(list)
    for r,d,snap in rows:
        if len(r.values or [])!=1: continue
        v=r.values[0];op=v.get('op');unit=v.get('unit');value=v.get('value')
        if op not in ('<=','>=') or not isinstance(value,(int,float)) or not math.isfinite(value):continue
        text=re.sub(r'\d+(?:[.,]\d+)?','#',r.text_he)
        key=(norm(text),unit,op)
        groups[key].append({'draft_id':r.id,'document_id':d.id,'source':d.title or d.url,'sha256':snap.sha256,'page':r.page,'text':r.text_he,'value':value,'unit':unit,'operator':op})
    out=[]
    for k,ls in groups.items():
        if len({x['document_id'] for x in ls})>1 and len({x['value'] for x in ls})>1:
            out.append({'status':'POSSIBLE_CONFLICT_VERIFY_SCOPE','entries':ls})
    return out
