import { useEffect, useState } from 'react'
import { api } from '../api'
import { useApp } from '../App'

const OUTCOME_HE: Record<string, string> = { OK: 'הצלחה', FALLBACK: 'גיבוי מאושר', MANUAL_REVIEW: 'הועבר לבדיקה ידנית', BLOCKED_BY_POLICY: 'נחסם במדיניות' }
const ST_COL: Record<string, string> = { FAIL: 'var(--fail)', UNCERTAIN: '#d79a00', PASS: 'var(--pass)', NA: '#a0aec0' }

export default function Dashboard() {
  const { meta, can } = useApp()
  const [d, setD] = useState<any>(null)
  const [err, setErr] = useState('')
  const [users, setUsers] = useState<Record<string, string>>({})
  useEffect(() => {
    if (!can('dashboard.read')) return
    api.get('/api/dashboard').then(setD).catch(e => setErr(e.message))
    api.get<any[]>('/api/users').then(us => setUsers(Object.fromEntries(us.map(u => [u.id, u.display_name]))))
  }, [])
  if (!can('dashboard.read')) return <div className="notice">לוח הבקרה זמין למנהלי אגף, מהנדס העיר ומנהל המערכת. החליפו משתמש בראש המסך.</div>
  if (err) return <div className="notice">{err}</div>
  if (!d) return <div className="empty">טוען…</div>
  const total = Object.values(d.cases_by_status as Record<string, number>).reduce((a, b) => a + b, 0)
  const ftotal = Object.values(d.findings_by_status as Record<string, number>).reduce((a, b) => a + b, 0) || 1
  const cost = d.ai_usage.reduce((a: number, x: any) => a + x.cost_ils, 0)
  return (
    <>
      <div className="page-head"><div><h1>לוח בקרה</h1><p>עומסים, זמני בדיקה ועלויות AI — נתוני הסביבה הנוכחית</p></div></div>
      <div className="grid k4">
        <div className="card stat"><div className="l">תיקים</div><div className="v num">{total}</div></div>
        <div className="card stat"><div className="l">חריגות SLA</div><div className="v num" style={{ color: d.sla_overdue ? 'var(--fail)' : undefined }}>{d.sla_overdue}</div></div>
        <div className="card stat"><div className="l">זמן הרצת בדיקה (ממוצע / מרבי)</div><div className="v"><span className="num">{(d.run_duration_ms.avg / 1000).toFixed(2)}</span> / <span className="num">{(d.run_duration_ms.max / 1000).toFixed(2)}</span> ש׳</div><div className="small muted">יעד מכרז: דוח ≤ 60 ש׳, תיק מלא ≤ 2 דק׳</div></div>
        <div className="card stat"><div className="l">עלות AI מצטברת</div><div className="v"><span className="num">{cost.toFixed(2)}</span> ₪</div><div className="small muted">עיבוד מקומי = 0 ₪ ישיר</div></div>
      </div>
      <div className="grid k2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>תיקים לפי סטטוס</h3>
          <table><tbody>{Object.entries(d.cases_by_status).map(([k, v]: any) => (
            <tr key={k}><td>{meta.case_statuses[k] ?? k}</td><td className="num" style={{ width: 60 }}>{v}</td>
              <td style={{ width: '50%' }}><div className="bar"><i style={{ width: `${(v / total) * 100}%`, background: 'var(--brand-2)' }} /></div></td></tr>
          ))}</tbody></table>
          <h3 style={{ marginTop: 14 }}>עומס לפי בודק</h3>
          <table><tbody>{Object.entries(d.cases_by_reviewer).map(([k, v]: any) => (
            <tr key={k}><td>{k === 'unassigned' ? 'לא שובץ' : users[k] ?? k}</td><td className="num">{v}</td></tr>
          ))}</tbody></table>
        </div>
        <div className="card">
          <h3>התפלגות ממצאים (כל ההרצות)</h3>
          <div className="bar" style={{ height: 16, marginBottom: 8 }}>
            {['FAIL', 'UNCERTAIN', 'PASS', 'NA'].map(s => <i key={s} style={{ width: `${((d.findings_by_status[s] ?? 0) / ftotal) * 100}%`, background: ST_COL[s] }} title={s} />)}
          </div>
          <div className="counts small">{['FAIL', 'UNCERTAIN', 'PASS', 'NA'].map(s => (
            <span key={s} className={'chip st-' + s}>{{ FAIL: 'לא עומד', UNCERTAIN: 'דורש בדיקה', PASS: 'עומד', NA: 'לא חל' }[s]} <span className="num">{d.findings_by_status[s] ?? 0}</span></span>))}</div>
          <h3 style={{ marginTop: 14 }}>שימוש ב־AI לפי משימה</h3>
          <table>
            <thead><tr><th>משימה</th><th>תוצאה</th><th>קריאות</th><th>עלות ₪</th><th>זמן ממוצע</th></tr></thead>
            <tbody>{d.ai_usage.map((x: any, i: number) => (
              <tr key={i}><td className="ltr">{x.task}</td><td>{OUTCOME_HE[x.outcome] ?? x.outcome}</td><td className="num">{x.calls}</td><td className="num">{x.cost_ils.toFixed(2)}</td><td className="num">{x.avg_latency_ms} מ״ש</td></tr>
            ))}</tbody>
          </table>
        </div>
      </div>
      <div className="notice" style={{ marginTop: 14 }}>{d.kpi_note_he}</div>
    </>
  )
}
