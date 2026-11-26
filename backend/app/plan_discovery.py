"""Discover candidate plans in official XPLAN REST map service. Never legal activation.
Only verified public parcel geometry, no application files or resident identifiers leave host.
Network opt-in is server configuration; live service layer schema must be verified.
"""
from __future__ import annotations
import datetime as dt
import json, os, re
from urllib.parse import urlencode
from .source_monitor import fetch as F
from .regulatory import property_context, polygon, digest, norm
from .models import ParcelPlanDiscovery
from .config import settings
BASE='https://ags.iplan.gov.il/arcgisiplan/rest/services/PlanningPublic/Xplan/MapServer'
CFG={'user_agent':'PermitReviewAI/1.0','max_bytes':8*1024*1024,'timeout_s':15}

def query_json(path,params,fetcher):
    url=BASE+path+'?'+urlencode({**params,'f':'json'})
    r=fetcher(url,CFG,{'ags.iplan.gov.il'})
    if r.status!='ok': raise ValueError(f'XPLAN {r.status}: {r.message or r.http_status}')
    d=json.loads(r.body)
    if not isinstance(d,dict) or 'error' in d: raise ValueError('XPLAN returned API error')
    return d

def discover(geo,fetcher=None):
    fetcher=fetcher or F.fetch
    box=polygon(geo).bounds
    envelope=dict(zip(('xmin','ymin','xmax','ymax'),box));envelope['spatialReference']={'wkid':2039}
    candidates={};errors=[];checked=0
    try: root=query_json('',{},fetcher)
    except Exception as e: return {'status':'UNAVAILABLE','plans':[],'errors':[str(e)[:300]],'coverage_complete':False}
    layers=[l for l in root.get('layers',[]) if isinstance(l.get('id'),int) and not l.get('subLayerIds')]
    if len(layers)>40: errors.append('layer count limit');layers=layers[:40]
    for l in layers:
        lid=l['id']
        try:
            meta=query_json('/'+str(lid),{},fetcher)
            if meta.get('geometryType')!='esriGeometryPolygon': continue
            fields=meta.get('fields',[])
            # Recognize only explicit plan-number field names/aliases, never guess from arbitrary numeric ID.
            options=[f['name'] for f in fields if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',f.get('name','')) and (f['name'].lower() in {'pl_number','plan_number','plannumber','pl_num','plan_no'} or norm(f.get('alias')) in {'מספרתכנית','מספרתוכנית'})]
            if not options:
                errors.append(f'layer {lid}: plan-number field not recognized');continue
            field=options[0];checked+=1
            args={'where':'1=1','geometry':json.dumps(envelope,separators=(',',':')),'geometryType':'esriGeometryEnvelope','inSR':2039,'spatialRel':'esriSpatialRelIntersects','outFields':field,'returnGeometry':'false'}
            offset=0
            for _ in range(10):
                data=query_json(f'/{lid}/query',{**args,'resultOffset':offset,'resultRecordCount':500},fetcher)
                features=data.get('features')
                if not isinstance(features,list): raise ValueError('missing features')
                for f in features:
                    value=str(f.get('attributes',{}).get(field) or '').strip()
                    if value and len(value)<=120: candidates.setdefault(norm(value),{'plan':value,'layer':lid,'source':BASE+f'/{lid}','status':'CANDIDATE_ENVELOPE_INTERSECTION'})
                if not data.get('exceededTransferLimit'): break
                if not features: raise ValueError('empty paginated response')
                offset+=len(features)
            else: errors.append(f'layer {lid}: pagination limit')
        except Exception as e: errors.append(f'layer {lid}: {str(e)[:250]}')
    return {'status':'PARTIAL' if errors or not checked else 'CANDIDATES_FOUND','plans':list(candidates.values()),'layers_checked':checked,'errors':errors,'coverage_complete':False}

def refresh(s,case,fetcher=None):
    _,_,_,_,geo=property_context(s,case)
    if not geo: return {'status':'MISSING_VERIFIED_PARCEL','plans':[],'coverage_complete':False}
    if fetcher is None and os.getenv('BBP_XPLAN_ENABLED','false').lower() not in ('true','1'): return {'status':'DISABLED','plans':[],'coverage_complete':False}
    # The app process never fetches when crawling is isolated in the restricted crawler process.
    if fetcher is None and settings.crawler_separate: return {'status':'DISABLED','plans':[],'coverage_complete':False,'note':'XPLAN queries must run in the restricted crawler process'}
    result=discover(geo,fetcher);row=s.get(ParcelPlanDiscovery,case.id)
    if row is None:
        row=ParcelPlanDiscovery(case_id=case.id,tenant_id=case.tenant_id,parcel_hash=digest(geo),result=result);s.add(row)
    else:
        if row.tenant_id!=case.tenant_id: raise ValueError('scope mismatch')
        row.parcel_hash=digest(geo);row.result=result;row.checked_at=dt.datetime.now(dt.timezone.utc)
    s.commit();return result
