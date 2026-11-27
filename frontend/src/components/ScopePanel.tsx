import { useEffect, useState } from 'react'
import { Case, api } from '../api'
import { useApp } from '../App'

const STATUS_HE: Record<string, string> = { APPLIES: 'חל', NOT_APPLICABLE: 'לא חל', UNRESOLVED: 'לא הוכרע' }
const DISCOVERY_HE: Record<string, string> = {
  NOT_DISCOVERED: 'טרם בוצע איתור', QUEUED: 'ממתין לסורק', RUNNING: 'הסורק מאתר…', DISABLED: 'איתור ב־XPLAN כבוי',
  MISSING_VERIFIED_PARCEL: 'אין גבול מגרש מאומת', MISSING_GEOMETRY: 'אין גבול מגרש מאומת ואין תא שטח בתכנית המוצהרת',
  UNAVAILABLE: 'שירות XPLAN לא זמין', PARTIAL: 'איתור חלקי', CANDIDATES_FOUND: 'נמצאו תכניות מועמדות', FAILED: 'האיתור נכשל',
}
const REL_HE: Record<string, string> = { COVERS: 'מכסה', PARTIAL: 'חלקי' }

/** Internal audit: which verified regulatory entries apply to the lot, conflicts between them, and what is unproven. */
export default function ScopePanel({ c }: { c: Case }) {
  const { can, toast } = useApp()
  const [r, setR] = useState<any>(null), [job, setJob] = useState<any>(null)
  const load = () => Promise.all([api.get<any>(`/api/cases/${c.id}/regulatory-resolution`), api.get<any>(`/api/cases/${c.id}/plan-discovery`)])
    .then(([a, b]) => { setR(a); setJob(b) }).catch(e => toast(e.message, true))
  useEffect(() => { setR(null); setJob(null); load() }, [c.id])
  const pending = job?.state === 'queued' || job?.state === 'running'
  useEffect(() => {                       // the crawler runs the job; poll until it finishes
    if (!pending) return
    const t = setTimeout(() => api.get<any>(`/api/cases/${c.id}/plan-discovery`).then(j => {
      setJob(j); if (j.state === 'done' || j.state === 'failed') { toast(DISCOVERY_HE[j.status] ?? j.status, j.state === 'failed'); load() }
    }).catch(() => {}), 3000)
    return () => clearTimeout(t)
  }, [job, c.id])
  const discover = async () => {
    try { setJob(await api.post<any>(`/api/cases/${c.id}/discover-plans`)) } catch (e: any) { toast(e.message, true) }
  }
  if (!r) return <div className="empty">טוען…</div>
  const d = job?.state === 'done' ? job : r.discovery
  const docs = Object.entries(r.candidate_documents ?? {}) as [string, any[]][]
  return <div className="scope-panel">
    <div className="card-head">
      <span className="chip outline">בקרה פנימית — לא חלק מהדוח</span>
      <span className="small muted">כיסוי המקורות: {r.coverage_complete ? 'אומת' : 'לא הוכח'} · ערכים מאושרים: {r.entries?.length ?? 0} · סתירות: {r.conflicts?.length ?? 0}</span>
      <span className="spacer" />
      {can('source.crawl') && c.kind !== 'design' && <button className="sm" disabled={pending} onClick={discover}>{pending ? DISCOVERY_HE[job.status] : 'איתור תכניות ב־XPLAN'}</button>}
    </div>
    <p className="small muted" style={{ margin: '0 0 8px' }}>
      XPLAN: {pending ? DISCOVERY_HE[job.status] : (DISCOVERY_HE[d?.status] ?? d?.status)}
      {d?.checked_at && !pending ? ` · ${new Date(d.checked_at).toLocaleString('he-IL')}` : ''}
      {job?.state === 'failed' && job.error ? ` · ${job.error}` : ''}
      {d?.geometry_source?.note_he ? ` · לפי ${d.geometry_source.note_he}` : ''}
    </p>
    {d?.declared_plans?.length > 0 && <table className="small" style={{ marginBottom: 8 }}><thead><tr><th>תכנית מוצהרת</th><th>ב־XPLAN</th><th>סטטוס</th><th>פרסום ברשומות</th><th>סוג</th></tr></thead><tbody>
      {d.declared_plans.map((p: any) => <tr key={p.plan}><td className="ltr">{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.plan}</a> : p.plan}</td>
        <td>{p.found ? 'נמצאה' : 'לא נמצאה'}</td><td>{p.status ?? '—'}{p.stage ? ` (${p.stage})` : ''}</td><td>{p.published ?? '—'}</td><td>{p.subtype ?? '—'}</td></tr>)}
    </tbody></table>}
    {d?.plans?.length > 0 && <details style={{ marginBottom: 8 }}><summary className="small" style={{ cursor: 'pointer' }}>
      תכניות שהקו הכחול שלהן חותך את {d.geometry_source?.kind === 'PLAN_CELL_XPLAN' ? 'תא השטח' : 'המגרש'} ({d.plans.length}) — מועמדות, אינן הוכחת תחולה; XPLAN מציג תכניות מקוונות בלבד</summary>
      <table className="small"><thead><tr><th>תכנית</th><th>שם</th><th>יחס</th><th>סטטוס</th><th>פרסום</th></tr></thead><tbody>
        {d.plans.map((p: any) => <tr key={p.plan}><td className="ltr">{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.plan}</a> : p.plan}</td>
          <td>{p.name ?? '—'}</td><td>{REL_HE[p.relation] ?? p.relation}</td><td>{p.status ?? '—'}</td><td>{p.published ?? '—'}</td></tr>)}
      </tbody></table></details>}
    {d?.land_use?.length > 0 && <div className="small" style={{ marginBottom: 8 }}>ייעודי קרקע: {d.land_use.map((u: any, i: number) =>
      <span key={i} className="chip outline" style={{ marginInlineEnd: 4 }}>{u.designation} · תא {u.cell} · <span className="ltr">{u.plan}</span></span>)}</div>}
    {r.conflicts?.length > 0 && <div className="notice bad small" style={{ marginBottom: 8 }}><b>סתירות בין ערכים מאושרים</b>
      {r.conflicts.map((x: any, i: number) => <div key={i}><b>{(x.key ?? []).join(' / ')}</b> — {x.status === 'INCOMPATIBLE_LIMITS' ? 'מגבלות סותרות' : x.status === 'UNRESOLVED_REPLACEMENT' ? 'החלפה לא מוכרעת' : 'ערכים שונים — נדרשת בדיקה'}: {(x.entries ?? []).map((e: any) => `${e.title} ${e.clause} (${e.operator} ${e.value} ${e.unit})`).join(' · ')}</div>)}</div>}
    {r.entries?.length > 0 && <table><thead><tr><th>מקור</th><th>סעיף</th><th>ערך</th><th>תחולה</th><th>נימוק</th></tr></thead><tbody>
      {r.entries.map((e: any) => <tr key={e.id}><td>{e.title}</td><td>{e.clause}</td><td className="num">{e.operator ? `${e.component}.${e.attribute} ${e.operator} ${e.value} ${e.unit}` : '—'}</td><td>{STATUS_HE[e.status] ?? e.status}</td><td className="small">{(e.reason ?? []).join(', ')}</td></tr>)}
    </tbody></table>}
    {docs.length > 0 && <details style={{ marginTop: 8 }}><summary className="small" style={{ cursor: 'pointer' }}>מסמכים שנקלטו המזכירים את התכניות ({docs.reduce((n, [, l]) => n + l.length, 0)}) — התאמת טקסט בלבד</summary>
      {docs.map(([p, l]) => <div key={p} className="small"><b className="ltr">{p}</b>: {l.length ? l.map(d => `${d.title ?? d.document_id} (יח׳ ${d.page})`).join(' · ') : 'אין'}</div>)}</details>}
    {r.unresolved?.length > 0 && <details style={{ marginTop: 8 }} open={!r.entries?.length}><summary className="small" style={{ cursor: 'pointer' }}>לא הוכרע ({r.unresolved.length})</summary>
      <ul className="small" style={{ margin: '4px 0' }}>{r.unresolved.map((u: string, i: number) => <li key={i}>{u}</li>)}</ul></details>}
  </div>
}
