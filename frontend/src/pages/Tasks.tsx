import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../App'

/** My open process tasks and the authority's overdue ones. */
export default function Tasks() {
  const { toast } = useApp()
  const [scope, setScope] = useState('mine'), [rows, setRows] = useState<any[] | null>(null)
  useEffect(() => { setRows(null); api.get<any[]>('/api/tasks?scope=' + scope).then(setRows).catch(e => toast(e.message, true)) }, [scope])
  return <>
    <div className="page-head"><div><h1>משימות</h1><p>שלבי התהליך הפתוחים של התפקיד שלך או המשויכים אליך, ומשימות באיחור.</p></div>
      <span className="spacer" /><select value={scope} onChange={e => setScope(e.target.value)}><option value="mine">שלי</option><option value="overdue">באיחור (כל הרשות)</option></select></div>
    <div className="card" style={{ padding: 0, overflowX: 'auto' }}><table><thead><tr><th>תיק</th><th>שלב</th><th>מצב</th><th>יעד</th></tr></thead><tbody>
      {(rows ?? []).map(t => <tr key={t.id}><td><Link to={`/cases/${t.case_id}`}>{t.case_number}</Link><div className="small muted">{t.case_title}</div></td>
        <td>{t.name_he}{t.decision && <span className="chip outline" style={{ marginInlineStart: 4 }}>החלטה</span>}</td>
        <td>{t.status_he}{t.overdue && <span className="chip bad" style={{ marginInlineStart: 4 }}>באיחור</span>}{t.escalated_to && <span className="chip bad" style={{ marginInlineStart: 4 }}>הוסלם</span>}</td>
        <td>{t.due_at ? new Date(t.due_at).toLocaleDateString('he-IL') : '—'}</td></tr>)}
      {rows && !rows.length && <tr><td colSpan={4} className="empty">אין משימות</td></tr>}
    </tbody></table></div>
  </>
}
