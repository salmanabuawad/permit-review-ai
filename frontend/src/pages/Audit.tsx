import { useEffect, useState } from 'react'
import { api, fmtDate } from '../api'
import { useApp } from '../App'

const ACTION_HE: Record<string, string> = {
  'case.create': 'יצירת תיק', 'case.update': 'עדכון נתוני תיק', 'file.upload': 'העלאת קובץ', 'file.download': 'הורדת קובץ',
  'check.run': 'הרצת בדיקה', 'finding.confirmed': 'אישור ממצא', 'finding.overridden': 'דחיית ממצא', 'case.lock': 'נעילת גרסה',
  'case.assign': 'שיבוץ בודק', 'case.status': 'שינוי סטטוס', 'rule.approved': 'אישור כלל', 'rule.revoked': 'ביטול אישור כלל',
  'ai.policy.update': 'עדכון מדיניות AI', 'report.export': 'ייצוא דוח', 'case.export': 'ייצוא תיק',
}

export default function Audit() {
  const { can } = useApp()
  const [d, setD] = useState<any>(null)
  useEffect(() => { if (can('audit.read')) api.get('/api/audit').then(setD) }, [])
  if (!can('audit.read')) return <div className="notice">יומן הביקורת זמין למנהל מערכת, מהנדס העיר ומנהל אגף.</div>
  if (!d) return <div className="empty">טוען…</div>
  return (
    <>
      <div className="page-head">
        <div><h1>יומן ביקורת</h1><p>רישום רציף ומשורשר בגיבוב (SHA-256) — כל שינוי ברשומה קודמת מתגלה.</p></div>
        <span className="spacer" />
        {d.chain_ok ? <span className="chip ok">שרשרת תקינה</span> : <span className="chip bad">שרשרת פגומה — רשומה {d.first_bad_id}</span>}
      </div>
      <div className="card"><div className="table-wrap"><table>
        <thead><tr><th>#</th><th>מועד</th><th>משתמש</th><th>פעולה</th><th>ישות</th><th>פרטים</th><th>Hash</th></tr></thead>
        <tbody>{d.events.map((e: any) => (
          <tr key={e.id}>
            <td className="num">{e.id}</td><td className="small">{fmtDate(e.at)}</td><td className="mono">{e.actor}</td>
            <td>{ACTION_HE[e.action] ?? e.action}</td><td className="small"><span className="mono">{e.entity}</span></td>
            <td className="small" style={{ maxWidth: 420 }}><code dir="ltr" style={{ display: 'block', whiteSpace: 'pre-wrap', wordBreak: 'break-word', textAlign: 'left' }}>{JSON.stringify(e.detail).slice(0, 220)}</code></td>
            <td className="mono">{e.hash}</td>
          </tr>))}</tbody>
      </table></div></div>
    </>
  )
}
