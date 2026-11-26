import AIRegistry from '../components/AIRegistry'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useApp } from '../App'

const MODE_HE: Record<string, string> = { LOCAL: 'מקומי', CLOUD: 'ענן', HYBRID: 'היברידי' }
const LOC_HE: Record<string, string> = { ON_PREM: 'שרת מקומי', IL_REGION: 'ענן — אזור ישראל', APPROVED_CLOUD: 'ענן מאושר' }
const TASK_HE: Record<string, string> = { OCR: 'OCR', Layout: 'ניתוח פריסה', Vision: 'ראייה ממוחשבת', Parsing: 'פענוח', Retrieval: 'אחזור', Classification: 'סיווג מסמכים', ReportDraft: 'ניסוח טיוטת דוח', Extraction: 'חילוץ נתונים' }
const OUTCOME_HE: Record<string, [string, string]> = { OK: ['הצליח', 'ok'], FALLBACK: ['גיבוי', 'warn'], MANUAL_REVIEW: ['בדיקה ידנית', 'bad'], BLOCKED_BY_POLICY: ['נחסם', 'bad'] }

export default function AISettings() {
  const { can, toast } = useApp()
  const [d, setD] = useState<any>(null)
  const [edit, setEdit] = useState<any>(null)
  const [llm, setLlm] = useState<any>(null)
  const [model, setModel] = useState<Record<string, string>>({})
  const [test, setTest] = useState<any>(null)
  const [testing, setTesting] = useState('')
  const load = () => api.get('/api/ai').then(setD)
  const loadLlm = () => { setLlm(null); api.get('/api/ai/llm').then(setLlm).catch(e => setLlm({ connected: false, error: e.message, models: [] })) }
  useEffect(() => { load(); loadLlm() }, [])
  if (!d) return <div className="empty">טוען…</div>
  const admin = can('ai.configure')
  const setProvider = async (pid: string, body: any, msg: string) => {
    try { await api.put(`/api/ai/providers/${pid}`, body); toast(msg); load() } catch (e: any) { toast(e.message, true) }
  }
  const runTest = async (task: string) => {
    setTesting(task); setTest(null)
    try { setTest(await api.post('/api/ai/test', { task })) } catch (e: any) { toast(e.message, true) } finally { setTesting('') }
  }
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
        <div className="card-head"><h3>מודל השפה — מחשב ה-AI</h3><span className="spacer" /><button className="sm" onClick={loadLlm}>רענון</button></div>
        {!llm ? <p className="small muted">בודק חיבור…</p> : <>
          <dl className="kv">
            <dt>מצב</dt><dd>{llm.connected ? <span className="chip ok">מחובר</span> : <span className="chip bad">לא זמין</span>}
              {llm.error && <span className="small muted"> {llm.error}</span>}</dd>
            <dt>חיבור</dt><dd className="small">{llm.via_relay ? 'מחשב ה-AI מושך עבודות מהשרת (LLM relay)' : 'שרת מודל מקומי'} <span className="mono muted ltr">{llm.base_url}</span></dd>
            {llm.relay && <><dt>פעילות</dt><dd className="small num">פנייה אחרונה לפני {llm.relay.agent_last_seen_s ?? '—'} שנ׳ · הושלמו {llm.relay.served} · נכשלו {llm.relay.failed} · בתור {llm.relay.queued}</dd></>}
            <dt>מודלים זמינים</dt><dd className="small mono ltr">{llm.models?.length ? llm.models.join(' · ') : '—'}</dd>
          </dl>
          <p className="small muted">כשמחשב ה-AI כבוי, המשימות עוברות מיד לספק הבא במדיניות (מסווג מילות מפתח / חילוץ כללים / תבנית). ביבוא מרובה מסמכים המודל אינו בשימוש, כדי שהבקשה תסתיים בזמן.</p>
          {admin && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="sm" disabled={!!testing} onClick={() => runTest('Classification')}>{testing === 'Classification' ? 'בודק…' : 'בדיקת סיווג'}</button>
            <button className="sm" disabled={!!testing} onClick={() => runTest('ReportDraft')}>{testing === 'ReportDraft' ? 'בודק…' : 'בדיקת טיוטת דוח'}</button>
          </div>}
          {test && <div className="notice info small" style={{ marginTop: 10 }}>
            <b>{TASK_HE[test.task]}</b>: <span className={'chip ' + (OUTCOME_HE[test.outcome]?.[1] ?? '')}>{OUTCOME_HE[test.outcome]?.[0] ?? test.outcome}</span>{' '}
            ספק <span className="mono">{test.provider ?? '—'}</span> {test.model && <span className="mono">({test.model})</span>} · <span className="num">{(test.latency_ms / 1000).toFixed(1)} שנ׳</span>
            <div style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>{test.output?.text ?? JSON.stringify(test.output)}</div>
            {test.trail?.filter((t: any) => !t.used).map((t: any, i: number) => <div key={i} className="muted">{t.provider}: {t.skipped ?? t.error}</div>)}
          </div>}
        </>}
      </div>
      <div className="card">
        <h3>ספקים</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>ספק</th><th>סוג</th><th>מיקום עיבוד</th><th>משימות</th><th>גרסת מודל (נעוצה)</th><th>מצב</th>{admin && <th></th>}</tr></thead>
          <tbody>{Object.entries(d.providers).map(([id, p]: any) => (
            <tr key={id}>
              <td><b>{p.label_he}</b><div className="mono small muted">{id}</div></td>
              <td>{p.kind === 'LOCAL' ? 'מקומי' : 'ענן'}</td>
              <td className="small">{LOC_HE[p.location] ?? p.location}</td>
              <td className="small">{p.tasks.map((t: string) => TASK_HE[t] ?? t).join(', ')}</td>
              <td className="mono">{admin && id === 'local_ollama' ? (
                <span style={{ display: 'flex', gap: 4 }}>
                  {llm?.models?.length ? (
                    <select dir="ltr" value={model[id] ?? p.model_version} onChange={e => setModel({ ...model, [id]: e.target.value })}>
                      {[...new Set([p.model_version, ...llm.models])].map((m: string) => <option key={m} value={m}>{m}</option>)}</select>
                  ) : <input dir="ltr" value={model[id] ?? p.model_version} onChange={e => setModel({ ...model, [id]: e.target.value })} />}
                  {model[id] && model[id] !== p.model_version && <button className="sm primary" onClick={() =>
                    setProvider(id, { model_version: model[id] }, `המודל הוחלף ל־${model[id]}`).then(() => setModel({ ...model, [id]: '' }))}>שמירה</button>}
                </span>) : p.model_version}
                {d.provider_settings?.[id] && <div className="small muted">הוגדר במסך זה</div>}</td>
              <td>{!p.approved ? <span className="chip bad">לא אושר</span> : p.enabled === false ? <span className="chip warn">מושבת</span> : <span className="chip ok">פעיל</span>}</td>
              {admin && <td>{p.approved && <button className="sm" onClick={() => setProvider(id, { enabled: p.enabled === false },
                p.enabled === false ? 'הספק הופעל' : 'הספק הושבת')}>{p.enabled === false ? 'הפעלה' : 'השבתה'}</button>}</td>}
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
      <AIRegistry />
    </>
  )
}
