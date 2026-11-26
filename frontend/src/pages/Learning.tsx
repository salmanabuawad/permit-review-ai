import FeedbackPanel from '../components/FeedbackPanel'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../App'

// Decided cases the administrator loaded, and how the committee's decisions bear on each rule.
export default function Learning() {
  const { can, toast } = useApp()
  const [d, setD] = useState<any>(null)
  useEffect(() => { if (can('learning.manage')) api.get<any>('/api/learning').then(setD).catch(e => toast(e.message, true)) }, [])
  if (!can('learning.manage')) return <>
    <div className="page-head"><div><h1>למידה ומשוב מקצועי</h1><p>דחיות ממצאים של הבודקים, מקרי בדיקה ורגרסיה.</p></div></div>
    <FeedbackPanel />
  </>
  if (!d) return <div className="empty">טוען…</div>
  const stats = Object.entries(d.rule_stats as Record<string, any>).sort((a, b) => b[1].confirmed - a[1].confirmed)
  return (
    <>
      <div className="page-head"><div><h1>למידה מהחלטות</h1>
        <p>קולטים בקשה מלאה (קליטת מסמכים) ואז את החלטת הוועדה בלשונית "החלטת ועדה" בתיק. המערכת משווה את ההחלטה לבדיקה,
          מוסיפה את ההחלטה לבסיס הידע ומציעה טיוטות כלל לנימוקים שלא זוהו — לאישור מנהל.</p></div>
        <span className="spacer" /><Link to="/cases/import">קליטת בקשה</Link></div>
      <div className="card">
        <div className="card-head"><h3>תיקי לימוד</h3></div>
        <table><thead><tr><th>בקשה</th><th>החלטה</th><th>מצב</th><th>אומתו</th><th>לא זוהו</th><th>לא הועלו באישור</th><th>טיוטות</th></tr></thead>
          <tbody>{d.records.map((r: any) => (
            <tr key={r.id}><td><Link to={'/cases/' + r.case_id} className="ltr">{r.case_number}</Link></td><td>{r.outcome_he}</td>
              <td>{r.status === 'done' ? 'נלמד' : r.status === 'pending' ? 'ממתין לבדיקה' : 'נכשל'}</td>
              <td className="num">{r.result?.confirmed?.length ?? '—'}</td><td className="num">{r.result?.missed?.length ?? '—'}</td>
              <td className="num">{r.result?.possible_false_defects?.length ?? '—'}</td><td className="num">{r.result?.drafts_created ?? '—'}</td></tr>))}
            {!d.records.length && <tr><td colSpan={7} className="empty">טרם נקלטו החלטות</td></tr>}</tbody></table>
      </div>
      {stats.length > 0 && <div className="card" style={{ marginTop: 14 }}>
        <div className="card-head"><h3>כללים לאור החלטות הוועדה</h3></div>
        <table><thead><tr><th>כלל</th><th>אומת בהחלטת ועדה</th><th>לא הועלה בבקשה שאושרה</th></tr></thead>
          <tbody>{stats.map(([id, v]) => <tr key={id}><td className="ltr">{id}</td><td className="num">{v.confirmed}</td>
            <td className="num">{v.not_raised_in_approval}</td></tr>)}</tbody></table>
        <p className="small muted">כלל שחוזר ומסומן ממצא בבקשות שאושרו — מומלץ לבחון אותו במאגר הכללים.</p>
      </div>}
      <FeedbackPanel />
    </>
  )
}
