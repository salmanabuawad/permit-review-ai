import { useEffect, useState } from 'react'
import { Case, api } from '../api'
import { useApp } from '../App'

const fmt = (s?: string | null) => s ? new Date(s).toLocaleDateString('he-IL') : '—'

/** The case's permit process: steps in dependency order, who does each, due dates, and the actions open to me. */
export default function ProcessPanel({ c }: { c: Case }) {
  const { me, can, meta, toast } = useApp()
  const [tasks, setTasks] = useState<any[] | null>(null)
  const load = () => api.get<any[]>(`/api/cases/${c.id}/tasks`).then(setTasks).catch(e => toast(e.message, true))
  useEffect(() => { load() }, [c.id])
  const act = async (t: any, action: string) => {
    const note = (t.decision && action === 'done') || action === 'skip' ? prompt(t.decision ? 'נימוק / פרטי ההחלטה' : 'נימוק לדילוג') : ''
    if (note === null) return
    try { await api.post(`/api/tasks/${t.id}`, { action, note: note || '' }); load() } catch (e: any) { toast(e.message, true) }
  }
  if (!tasks) return <div className="empty">טוען…</div>
  if (!tasks.length) return <div className="empty">לתיק אין עדיין תהליך רישוי.
    {can('case.assign') && <> <button className="primary" onClick={() => api.post(`/api/cases/${c.id}/tasks/start`).then(load).catch(e => toast(e.message, true))}>פתיחת תהליך</button></>}</div>
  const mine = (t: any) => [t.role, 'sysadmin'].includes(me?.role ?? '')
  return <div style={{ overflowX: 'auto' }}><table className="small"><thead><tr><th>שלב</th><th>תפקיד</th><th>מצב</th><th>מוכן מ־</th><th>יעד</th><th>הושלם</th><th></th></tr></thead><tbody>
    {tasks.map(t => <tr key={t.id} className={t.status === 'waiting' ? 'muted' : ''}><td><b>{t.name_he}</b>{t.decision && <span className="chip outline" style={{ marginInlineStart: 4 }}>החלטה מחויבת בדין</span>}
      {t.depends_on.length > 0 && <div className="muted">אחרי: {t.depends_on.map((d: string) => tasks.find(x => x.step === d)?.name_he ?? d).join(', ')}</div>}</td>
      <td>{meta?.roles?.[t.role]?.label_he ?? t.role}</td>
      <td>{t.status_he}{t.overdue && <div className="chip bad">באיחור</div>}{t.escalated_to && <div className="chip bad">הוסלם למנהל/ת אגף</div>}</td>
      <td>{fmt(t.ready_at)}</td><td>{fmt(t.due_at)}{t.sla_days ? <span className="muted"> ({t.sla_days} ימים)</span> : ''}</td>
      <td>{fmt(t.done_at)}{t.note && <div className="muted">{t.note}</div>}</td>
      <td className="user-actions">{mine(t) && t.status === 'ready' && <button className="sm" onClick={() => act(t, 'start')}>התחלה</button>}
        {mine(t) && ['ready', 'in_progress'].includes(t.status) && <button className="sm primary" onClick={() => act(t, 'done')}>{t.decision ? 'רישום החלטה' : 'סיום'}</button>}
        {mine(t) && !t.decision && ['ready', 'in_progress'].includes(t.status) && <button className="sm" onClick={() => act(t, 'skip')}>דילוג</button>}</td></tr>)}
  </tbody></table></div>
}
