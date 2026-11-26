import { useEffect, useState } from 'react'
import { api } from '../api'

const EXEC_HE: Record<string, string> = { deterministic: 'חישוב דטרמיניסטי (ללא מודל)', rules_then_model: 'כללים ואז מודל מקומי',
  model: 'מודל מקומי', escalate_only: 'רק מודל מאומת / בעל מקצוע' }
const OUT_HE: Record<string, string> = { DETERMINISTIC: 'דטרמיניסטי', MODEL: 'מודל בשימוש', UNRESOLVED: 'לא מוכרע — אין מודל מאומת', ESCALATE: 'הסלמה' }

/** Model registry (provenance, licence, status), prompt versions and the task routing table. Read-only. */
export default function AIRegistry() {
  const [d, setD] = useState<any>(null)
  useEffect(() => { api.get<any>('/api/ai/registry').then(setD).catch(() => setD(null)) }, [])
  if (!d) return null
  return <div className="card" style={{ marginTop: 14 }}>
    <div className="card-head"><h3>מרשם מודלים וניתוב משימות</h3>
      <span className="small muted">מותקן ≠ מאומת: מודל מאומת למשימה רק לאחר מבחן הבנצ׳מרק העברי</span></div>
    <div className="small muted" style={{ marginBottom: 6 }}>מחשב ה-AI: {d.hardware?.ai_pc?.gpu} · {d.hardware?.ai_pc?.vram_gb} GB · שרת: {d.hardware?.app_server?.cpu}</div>
    <div style={{ overflowX: 'auto' }}><table className="small"><thead><tr><th>מודל</th><th>מקום</th><th>כימות</th><th>רישיון</th><th>מצב</th><th>בשימוש ל־</th><th>מאומת ל־</th></tr></thead><tbody>
      {d.models.map((m: any) => <tr key={m.file}><td className="ltr" title={m.source + ' · ' + m.sha256}>{m.file}</td><td>{m.host === 'ai_pc' ? 'מחשב AI' : 'שרת'}</td><td>{m.quantization}</td>
        <td className={m.license === 'unverified' ? 'muted' : ''}>{m.license}</td><td>{m.status === 'IN_USE' ? <span className="chip ok">בשימוש</span> : <span className="chip outline">מועמד</span>}</td>
        <td className="ltr">{(m.in_use_for ?? []).join(', ')}</td><td>{(m.validated_for ?? []).length ? m.validated_for.join(', ') : <span className="muted">—</span>}</td></tr>)}
    </tbody></table></div>
    <h4 style={{ margin: '12px 0 4px' }}>גרסאות הנחיה (prompt)</h4>
    <div className="small">{d.prompts.map((p: any) => <span key={p.id} className="chip outline ltr" style={{ marginInlineEnd: 6 }}>{p.id}@{p.version}</span>)}</div>
    <h4 style={{ margin: '12px 0 4px' }}>ניתוב משימות</h4>
    <div style={{ overflowX: 'auto' }}><table className="small"><thead><tr><th>משימה</th><th>מבצע</th><th>תוצאה כיום</th><th>נימוק</th></tr></thead><tbody>
      {d.routes.map((r: any) => <tr key={r.task}><td className="ltr">{r.task}</td><td>{EXEC_HE[r.executor] ?? r.executor}</td><td>{OUT_HE[r.outcome] ?? r.outcome}</td><td className="muted">{r.reason}</td></tr>)}
    </tbody></table></div>
    <div className="small muted" style={{ marginTop: 6 }}>הסלמה למודל חזק יותר רק בטריגר אובייקטיבי ({d.triggers.join(', ')}) — לעולם לא לפי ביטחון שהמודל מדווח על עצמו.</div>
  </div>
}
