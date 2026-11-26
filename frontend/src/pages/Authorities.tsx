import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, setAuthority } from '../api'
import { useApp } from '../App'

const states: Record<string,string>={DISCOVERY_PENDING:'איתור מקורות',CRAWLING:'סריקת מקורות',CANDIDATES_READY:'נקלטו מועמדים לאימות',NEEDS_OFFICIAL_DIRECTORY:'מקור רשמי לא אותר / חסום',CRAWL_INCOMPLETE:'סריקה חלקית',FAILED:'שגיאה — נדרשת סריקה חוזרת'}
export default function Authorities(){
  const {me,can,toast}=useApp()
  const [data,setData]=useState<any>(null),[name,setName]=useState(''),[id,setId]=useState(''),[busy,setBusy]=useState(false)
  const [files,setFiles]=useState<File[]>([]),[q,setQ]=useState(''),[hits,setHits]=useState<any[]>([]),[results,setResults]=useState<string[]>([])
  const refresh=()=>api.get<any>('/api/authorities').then(setData).catch(e=>toast(e.message,true))
  const search=()=>api.get<any[]>('/api/knowledge/candidates?q='+encodeURIComponent(q)).then(setHits).catch(e=>toast(e.message,true))
  useEffect(()=>{refresh();const t=window.setInterval(refresh,5000);return ()=>window.clearInterval(t)},[])
  const activate=(a:string)=>{setAuthority(a);window.location.assign('/authorities')}
  const create=async()=>{setBusy(true);try{const r=await api.post<any>('/api/authorities',{id,name_he:name});activate(r.id)}catch(e:any){toast(e.message,true)}finally{setBusy(false)}}
  const upload=async()=>{setBusy(true);setResults([]);try{for(const file of files){const fd=new FormData();fd.append('file',file);try{const r=await api.upload<any>('/api/source-monitor/upload',fd);setResults(x=>[...x,`${file.name}: ${r.change_state==='unchanged'?'כבר קיים':'נקלט כידע לא מאומת'}`])}catch(e:any){setResults(x=>[...x,`${file.name}: ${e.message}`])}}setFiles([]);await search()}finally{setBusy(false)}}
  return <>
    <div className="page-head"><div><h1>רשויות ובסיס ידע</h1><p>בחירת סביבת עבודה, איתור מקורות רשמיים וקליטת מסמכים לכל רשות מורשית.</p></div></div>
    <div className="card" style={{padding:16,marginBottom:16}}><h3>הרשויות שלי</h3>{(data?.authorities??[]).map((a:any)=><div key={a.id} className="card-head" style={{flexWrap:'wrap'}}><b>{a.name_he}</b><span className="small muted">{states[a.onboarding?.state]||'סביבת עבודה קיימת'}</span><span className="spacer"/>{a.id===me?.tenant_id?<span className="chip ok">פעילה</span>:<button onClick={()=>activate(a.id)}>בחירה</button>}</div>)}
    {data?.can_create&&<form onSubmit={e=>{e.preventDefault();create()}} style={{display:'flex',gap:8,flexWrap:'wrap',marginTop:16}}><label>שם הרשות <input required maxLength={200} value={name} onChange={e=>setName(e.target.value)} placeholder="שם רשמי בעברית"/></label><label>מזהה רשות (לא חובה) <input dir="ltr" pattern="[a-z][a-z0-9-]{2,39}" value={id} onChange={e=>setId(e.target.value)} placeholder="authority-id"/></label><button className="primary" disabled={busy}>הוספת רשות ואיתור מקורות</button></form>}</div>
    <div className="card" style={{padding:16,marginBottom:16}}><h3>בסיס ידע — {me?.municipality_name}</h3><p>מסמכים שנקלטו אינם כללים מחייבים עד אימות מקור ותחולה ואישור מקצועי. הידע הקיים נשמר.</p>
    {can('source.crawl')&&<><button onClick={async()=>{try{await api.post(`/api/authorities/${me?.tenant_id}/discover`);toast('איתור מקורות הופעל');refresh()}catch(e:any){toast(e.message,true)}}}>איתור מקורות רשמיים מחדש</button>{' '}<Link to="/rules/sources">מעקב סריקות וטיוטות</Link>
    <div style={{marginTop:16}}><label>העלאת חוק, תקנה, הנחיה או תקנון <input type="file" multiple accept=".pdf,.docx,.xlsx,.txt" onChange={e=>setFiles(Array.from(e.target.files??[]))}/></label><button className="primary" disabled={busy||!files.length} onClick={upload}>{busy?'מעבד…':'קליטה לבסיס הידע'}</button></div>{results.map((r,i)=><p key={i} className="small">{r}</p>)}</>}
    </div>{can('source.crawl')&&<div className="card" style={{padding:16}}><h3>חיפוש בידע שנקלט (טרם אומת)</h3><form onSubmit={e=>{e.preventDefault();search()}}><input value={q} onChange={e=>setQ(e.target.value)} placeholder="סעיף או מונח"/><button>חיפוש</button></form>{hits.map(h=><div className="app-card" key={h.id}><b>{h.title}</b> · יחידת מקור {h.page}<p style={{whiteSpace:'pre-wrap'}}>{h.text_he}</p><span className="small muted">מועמד לאימות · {h.sha256.slice(0,12)}</span></div>)}</div>}
  </>
}
