import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
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
      <div className="dashboard-hero">
        <div className="hero-copy"><span className="hero-kicker">מרכז הבקרה · מינהל ההנדסה</span><h1>תמונת מצב רישוי ובקרה</h1><p>מידע תפעולי, ביצועי בדיקות AI, עומסי טיפול ועלויות — במבט אחד.</p><div className="hero-actions"><Link className="hero-btn" to="/cases">צפייה בתיקי הבקשות <span aria-hidden="true">←</span></Link><Link className="hero-link" to="/rules">מאגר הכללים והנהלים</Link></div></div>
        <div className="hero-visual" aria-hidden="true"><div className="hero-visual-ring"><span>AI</span><i /></div><div className="hero-visual-note">בדיקה · שקיפות · בקרה</div></div>
      </div>
      <div className="section-heading"><div><h2>מדדים מרכזיים</h2><p>נתוני הסביבה הנוכחית</p></div><span className="status-dot-label"><i/> נתונים חיים מהמערכת</span></div>
      <div className="grid k4">
        <div className="card stat stat-blue"><div className="stat-decoration">▤</div><div className="l">תיקים במערכת</div><div className="v num">{total}</div></div>
        <div className="card stat stat-red"><div className="stat-decoration">◷</div><div className="l">חריגות בזמני טיפול</div><div className="v num" style={{ color: d.sla_overdue ? 'var(--fail)' : undefined }}>{d.sla_overdue}</div></div>
        <div className="card stat stat-teal"><div className="stat-decoration">◉</div><div className="l">זמן בדיקה ממוצע / מרבי</div><div className="v"><span className="num">{(d.run_duration_ms.avg / 1000).toFixed(2)}</span> / <span className="num">{(d.run_duration_ms.max / 1000).toFixed(2)}</span> ש׳</div><div className="small muted">יעד מכרז: דוח ≤ 60 ש׳, תיק מלא ≤ 2 דק׳</div></div>
        <div className="card stat stat-violet"><div className="stat-decoration">₪</div><div className="l">עלות AI מצטברת</div><div className="v"><span className="num">{cost.toFixed(2)}</span> ₪</div><div className="small muted">עיבוד מקומי = 0 ₪ ישיר</div></div>
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
      <div className="grid k2" style={{ marginTop: 14 }}>
        <div className="card">
          <div className="card-head"><h3>זמן ממוצע בכל שלב</h3><span className="spacer" />
            <span className="small muted">חדשים ב־7 ימים: <span className="num">{d.stages.new_last_7_days}</span> · ממתינים לגורם חוץ: <span className="num">{d.stages.waiting_external}</span></span></div>
          <table>
            <thead><tr><th>שלב</th><th>ממוצע (שעות)</th><th>מדידות</th></tr></thead>
            <tbody>{Object.entries(d.stages.avg_hours_by_stage).map(([k, v]: any) => (
              <tr key={k}><td>{meta.case_statuses[k] ?? k}</td><td className="num">{v}</td><td className="num">{d.stages.samples_by_stage[k]}</td></tr>
            ))}</tbody>
          </table>
          <h3 style={{ marginTop: 14 }}>תיקים תקועים (ללא שינוי ≥ <span className="num">{d.stages.stuck_threshold_days}</span> ימים)</h3>
          {d.stages.stuck.length === 0 ? <p className="small muted">אין</p> : (
            <table><tbody>{d.stages.stuck.map((x: any) => (
              <tr key={x.case_id}><td><span className="ltr nowrap">{x.case_number}</span></td><td>{meta.case_statuses[x.status] ?? x.status}</td><td className="num">{x.days_in_status} ימים</td></tr>
            ))}</tbody></table>)}
          <p className="small muted">הזמנים משוחזרים מיומן הביקורת. סף "תקוע" הוא הנחת תכנון שתיקבע באפיון.</p>
        </div>
        <div className="card">
          <h3>עלות AI לפי חודש</h3>
          <table>
            <thead><tr><th>חודש</th><th>קריאות</th><th>עלות ₪</th></tr></thead>
            <tbody>{d.cost_per_month.map((x: any) => (
              <tr key={x.month}><td className="num">{x.month}</td><td className="num">{x.calls}</td><td className="num">{x.cost_ils.toFixed(2)}</td></tr>
            ))}</tbody>
          </table>
          <h3 style={{ marginTop: 14 }}>עלות AI לפי משתמש</h3>
          <table><tbody>{Object.entries(d.cost_per_user).map(([k, v]: any) => (
            <tr key={k}><td>{users[k] ?? k}</td><td className="num">{v.toFixed(2)} ₪</td></tr>
          ))}</tbody></table>
          <p className="small muted">עלות לתיק זמינה ב־API (cost_per_case). תקרת צריכת ענן ומודלים לפי ההסכם: 300,000 ₪ לשנה (סע׳ 13.5).</p>
        </div>
      </div>
      <div className="notice" style={{ marginTop: 14 }}>{d.kpi_note_he}</div>
    </>
  )
}
