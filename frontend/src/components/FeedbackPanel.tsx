import { useEffect, useState } from 'react'
import { api } from '../api'
import { useApp } from '../App'

/** Professional corrections of findings: classified, with similar open findings; an approver turns one into a
 *  regression case or dismisses it. The regression run measures the current rules against all accepted cases. */
export default function FeedbackPanel() {
  const { can, toast } = useApp()
  const [d, setD] = useState<any>(null), [status, setStatus] = useState('open'), [reg, setReg] = useState<any>(null)
  const load = () => api.get<any>('/api/feedback?status=' + status).then(setD).catch(e => toast(e.message, true))
  useEffect(() => { load() }, [status])
  const decide = async (id: string, action: string) => {
    const note = prompt(action === 'accept' ? 'נימוק להוספת מקרה הבדיקה' : 'נימוק לסגירה')
    if (!note) return
    try { await api.post(`/api/feedback/${id}/decision`, { action, note }); toast('נשמר'); load() } catch (e: any) { toast(e.message, true) }
  }
  if (!d) return null
  return <div className="card" style={{ marginTop: 14 }}>
    <div className="card-head"><h3>משוב מקצועי ורגרסיה</h3>
      <select value={status} onChange={e => setStatus(e.target.value)}><option value="open">פתוחות</option><option value="accepted">התקבלו</option><option value="dismissed">נסגרו</option><option value="all">הכול</option></select>
      <span className="spacer" />
      <button className="sm" onClick={() => api.get<any>('/api/feedback/regression').then(setReg).catch(e => toast(e.message, true))}>הרצת רגרסיה</button></div>
    {reg && <div className={'notice small ' + (reg.failed.length ? 'bad' : 'info')} style={{ marginBottom: 8 }}>
      {reg.cases} מקרי בדיקה · {reg.passed} עברו · {reg.failed.length} נכשלו{reg.failed.map((x: any) => ` · ${x.rule_id}: צפוי ${x.expect}, התקבל ${x.got}`).join('')}
      {reg.missing_rule.length > 0 && ` · כללים שאינם קיימים עוד: ${reg.missing_rule.join(', ')}`}</div>}
    <p className="small muted" style={{ margin: '0 0 8px' }}>דחיית ממצא יוצרת רשומה; היא אינה משנה כלל. מאשר מקצועי יכול להפוך אותה למקרה בדיקה קבוע.</p>
    <div style={{ overflowX: 'auto' }}><table className="small"><thead><tr><th>כלל</th><th>סיבה</th><th>מקור → תיקון</th><th>נימוק</th><th>דומים פתוחים</th><th></th></tr></thead><tbody>
      {d.records.map((r: any) => <tr key={r.id}><td className="ltr">{r.rule_id} v{r.rule_version}</td><td>{d.categories[r.category] ?? r.category}</td>
        <td>{r.original.status} → {r.corrected.status ?? '—'}</td><td>{r.reason}</td><td className="num">{r.similar}</td>
        <td>{r.status === 'open' && can('rule.approve') ? <div className="user-actions">
          <button className="sm" disabled={!r.has_candidate} title={r.has_candidate ? '' : 'אין מקרה בדיקה (חריג ספציפי או ללא תוצאה מתוקנת)'} onClick={() => decide(r.id, 'accept')}>למקרה בדיקה</button>
          <button className="sm" onClick={() => decide(r.id, 'dismiss')}>סגירה</button></div> : <span className="muted">{r.status}{r.decision_note ? ` — ${r.decision_note}` : ''}</span>}</td></tr>)}
      {!d.records.length && <tr><td colSpan={6} className="empty">אין רשומות</td></tr>}
    </tbody></table></div>
  </div>
}
