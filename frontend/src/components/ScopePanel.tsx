import { useEffect, useState } from 'react'
import { Case, api } from '../api'
import { useApp } from '../App'

const STATUS_HE: Record<string, string> = { APPLIES: 'חל', NOT_APPLICABLE: 'לא חל', UNRESOLVED: 'לא הוכרע' }
const DISCOVERY_HE: Record<string, string> = {
  NOT_DISCOVERED: 'טרם בוצע איתור', DISABLED: 'איתור ב־XPLAN כבוי', MISSING_VERIFIED_PARCEL: 'אין גבול מגרש מאומת',
  UNAVAILABLE: 'שירות XPLAN לא זמין', PARTIAL: 'איתור חלקי', CANDIDATES_FOUND: 'נמצאו תכניות מועמדות',
}

/** Internal audit: which verified regulatory entries apply to the lot, conflicts between them, and what is unproven. */
export default function ScopePanel({ c }: { c: Case }) {
  const { can, toast } = useApp()
  const [r, setR] = useState<any>(null), [busy, setBusy] = useState(false)
  const load = () => api.get<any>(`/api/cases/${c.id}/regulatory-resolution`).then(setR).catch(e => toast(e.message, true))
  useEffect(() => { setR(null); load() }, [c.id])
  const discover = async () => {
    setBusy(true)
    try { const d = await api.post<any>(`/api/cases/${c.id}/discover-plans`); toast(DISCOVERY_HE[d.status] ?? d.status); await load() }
    catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }
  if (!r) return <div className="empty">טוען…</div>
  const docs = Object.entries(r.candidate_documents ?? {}) as [string, any[]][]
  return <div className="scope-panel">
    <div className="card-head">
      <span className="chip outline">בקרה פנימית — לא חלק מהדוח</span>
      <span className="small muted">כיסוי המקורות: {r.coverage_complete ? 'אומת' : 'לא הוכח'} · ערכים מאושרים: {r.entries?.length ?? 0} · סתירות: {r.conflicts?.length ?? 0}</span>
      <span className="spacer" />
      {can('source.crawl') && <button className="sm" disabled={busy} onClick={discover}>{busy ? 'מאתר…' : 'איתור תכניות ב־XPLAN'}</button>}
    </div>
    <p className="small muted" style={{ margin: '0 0 8px' }}>{DISCOVERY_HE[r.discovery?.status] ?? r.discovery?.status}{r.discovery?.plans?.length ? ` · ${r.discovery.plans.length} תכניות מועמדות (חיתוך מעטפת — אינו הוכחת תחולה)` : ''}</p>
    {r.discovery?.plans?.length > 0 && <div className="small" style={{ marginBottom: 8 }}>{r.discovery.plans.map((p: any) => <span key={p.plan} className="chip outline ltr" style={{ marginInlineEnd: 4 }}>{p.plan}</span>)}</div>}
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
