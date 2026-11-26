import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

/** Management view: where cases wait, who carries the load, recurring violations, repeated returns, AI share. */
export default function ManagementPanel() {
  const [d, setD] = useState<any>(null)
  useEffect(() => { api.get<any>('/api/dashboard/management').then(setD).catch(() => setD(null)) }, [])
  if (!d) return null
  const p = d.processing
  return <div className="grid k2" style={{ marginTop: 14 }}>
    <div className="card"><h3>צווארי בקבוק בתהליך</h3>
      {d.bottlenecks.length ? <table className="small"><thead><tr><th>שלב</th><th>פתוחים</th><th>באיחור</th><th>המתנה ממוצעת</th><th>טיפול ממוצע</th></tr></thead><tbody>
        {d.bottlenecks.map((b: any) => <tr key={b.step}><td>{b.name_he}</td><td className="num">{b.open}</td><td className={'num' + (b.overdue ? ' s-bad' : '')}>{b.overdue}</td>
          <td className="num">{b.avg_wait_days ?? '—'}</td><td className="num">{b.avg_work_days ?? '—'}{b.samples ? <span className="muted"> ({b.samples})</span> : ''}</td></tr>)}
      </tbody></table> : <div className="empty small">אין עדיין תהליכים פתוחים</div>}
      <div className="small muted">{d.projection_note_he}</div></div>
    <div className="card"><h3>עומס ומשימות באיחור</h3>
      {d.workload.map((w: any) => <div key={w.who} className="small">{w.who.startsWith('role:') ? `תפקיד ${w.who.slice(5)}` : w.who}: {w.open} פתוחות{w.overdue ? ` · ${w.overdue} באיחור` : ''}</div>)}
      {d.overdue_tasks.slice(0, 8).map((t: any) => <div key={t.id} className="small"><Link to={`/cases/${t.case_id}`}>{t.case_number}</Link> · {t.name_he}{t.escalated_to && <span className="chip bad" style={{ marginInlineStart: 4 }}>הוסלם</span>}</div>)}
      {!d.workload.length && <div className="empty small">אין משימות פתוחות</div>}</div>
    <div className="card"><h3>ליקויים חוזרים</h3>
      {d.common_violations.map((v: any) => <div key={v.rule_id} className="small"><b className="num">{v.cases}</b> תיקים · {v.title_he}</div>)}
      {!d.common_violations.length && <div className="empty small">אין</div>}
      {d.repeated_returns.length > 0 && <><h4 style={{ margin: '10px 0 4px' }}>הוחזרו להשלמות יותר מפעם אחת</h4>
        {d.repeated_returns.map((r: any) => <div key={r.case_id} className="small"><Link to={`/cases/${r.case_id}`}>{r.case_number}</Link> · {r.returns} פעמים</div>)}</>}</div>
    <div className="card"><h3>עיבוד ו-AI</h3>
      <div className="small">{p.checks_latest_runs} בדיקות בהרצות האחרונות — כולן דטרמיניסטיות</div>
      <div className="small">סיכומי AI: {p.summary_model_calls} הפקות · {p.summary_cache_hits} שימוש חוזר{p.summary_reuse_pct != null ? ` (${p.summary_reuse_pct}%)` : ''}</div>
      <div className="small">ממוצע טוקנים להרצה: {p.avg_tokens_in_per_run ?? '—'}</div>
      <div className="small muted">{p.note_he}</div></div>
  </div>
}
