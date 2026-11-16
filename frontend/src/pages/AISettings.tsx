import { useEffect, useState } from 'react'
import { api } from '../api'
import { useApp } from '../App'

const MODE_HE: Record<string, string> = { LOCAL: 'מקומי', CLOUD: 'ענן', HYBRID: 'היברידי' }
const LOC_HE: Record<string, string> = { ON_PREM: 'שרת מקומי', IL_REGION: 'ענן — אזור ישראל', APPROVED_CLOUD: 'ענן מאושר' }
const TASK_HE: Record<string, string> = { OCR: 'OCR', Layout: 'ניתוח פריסה', Vision: 'ראייה ממוחשבת', Parsing: 'פענוח', Retrieval: 'אחזור', Classification: 'סיווג מסמכים', ReportDraft: 'ניסוח טיוטת דוח' }

export default function AISettings() {
  const { can, toast } = useApp()
  const [d, setD] = useState<any>(null)
  const [edit, setEdit] = useState<any>(null)
  const load = () => api.get('/api/ai').then(setD)
  useEffect(() => { load() }, [])
  if (!d) return <div className="empty">טוען…</div>
  const save = async () => {
    try { await api.put('/api/ai/policy', edit); toast('המדיניות עודכנה ונרשמה ביומן'); setEdit(null); load() }
    catch (e: any) { toast(e.message, true) }
  }
  return (
    <>
      <div className="page-head"><div><h1>הגדרות AI</h1><p>בחירת ספק לכל משימה וסוג מידע — מקומי, ענן או היברידי. מודלים אינם מכריעים חוקיות; הם מספקים ראיות למנוע הכללים.</p></div></div>
      <div className="notice info small" style={{ marginBottom: 14 }}>
        אכיפה בקוד: ספק שלא אושר לא ייקרא; גיבוי (fallback) לא יעקוף מגבלת מיקום נתונים או סודיות; כשל כל הספקים ← העברה לבדיקה ידנית.
        ברירת מחדל למסמכי תיק ומידע אישי: עיבוד מקומי בלבד.
      </div>
      <div className="card">
        <h3>ספקים</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>ספק</th><th>סוג</th><th>מיקום עיבוד</th><th>משימות</th><th>גרסת מודל (נעוצה)</th><th>מצב</th></tr></thead>
          <tbody>{Object.entries(d.providers).map(([id, p]: any) => (
            <tr key={id}>
              <td><b>{p.label_he}</b><div className="mono small muted">{id}</div></td>
              <td>{p.kind === 'LOCAL' ? 'מקומי' : 'ענן'}</td>
              <td className="small">{LOC_HE[p.location] ?? p.location}</td>
              <td className="small">{p.tasks.map((t: string) => TASK_HE[t] ?? t).join(', ')}</td>
              <td className="mono">{p.model_version}</td>
              <td>{!p.approved ? <span className="chip bad">לא אושר</span> : p.enabled === false ? <span className="chip warn">מושבת</span> : <span className="chip ok">פעיל</span>}</td>
            </tr>))}</tbody>
        </table></div>
      </div>
      <div className="card">
        <h3>מדיניות לפי משימה וסוג מידע</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>משימה</th><th>סוג מידע</th><th>מצב</th><th>סדר ספקים ובדיקת תאימות</th><th></th></tr></thead>
          <tbody>{d.policies.map((p: any) => (
            <tr key={p.task + p.data_class}>
              <td>{TASK_HE[p.task] ?? p.task}</td>
              <td className="small">{d.data_classes[p.data_class]?.label_he ?? p.data_class}</td>
              <td><span className="chip outline">{MODE_HE[p.mode]}</span></td>
              <td className="small">{p.providers.map((pid: string, i: number) => (
                <div key={pid}><span className="num">{i + 1}.</span> <span className="mono">{pid}</span> — {p.provider_checks[pid] ? <span style={{ color: 'var(--unc)' }}>ידולג: {p.provider_checks[pid]}</span> : <span style={{ color: 'var(--pass)' }}>מותר</span>}</div>))}</td>
              <td>{can('ai.configure') && <button className="sm" onClick={() => setEdit({ task: p.task, data_class: p.data_class, mode: p.mode, providers: p.providers })}>עריכה</button>}</td>
            </tr>))}</tbody>
        </table></div>
        {!can('ai.configure') && <p className="small muted">עריכת מדיניות — מנהל מערכת בלבד.</p>}
      </div>
      {edit && (
        <div className="card">
          <h3>עריכת מדיניות: {TASK_HE[edit.task]} / {d.data_classes[edit.data_class]?.label_he}</h3>
          <div className="form-grid">
            <label className="field">מצב<select value={edit.mode} onChange={e => setEdit({ ...edit, mode: e.target.value })}>
              {Object.entries(MODE_HE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label className="field">סדר ספקים (מופרד בפסיק)<input dir="ltr" value={edit.providers.join(', ')} onChange={e => setEdit({ ...edit, providers: e.target.value.split(',').map((s: string) => s.trim()).filter(Boolean) })} /></label>
          </div>
          <div style={{ marginTop: 10, display: 'flex', gap: 8 }}><button className="primary" onClick={save}>שמירה</button><button onClick={() => setEdit(null)}>ביטול</button></div>
        </div>
      )}
    </>
  )
}
