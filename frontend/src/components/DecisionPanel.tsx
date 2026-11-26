import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, Case } from '../api'
import { useApp } from '../App'

// The committee's decision on a request and what the system learned from it. The administrator loads the decision
// (file or pasted text); the engine's review is compared with it once the review is ready. Missed reasons become rule
// drafts that wait for approval — nothing here changes a finding.

export default function DecisionPanel({ c }: { c: Case }) {
  const { can, toast } = useApp()
  const [d, setD] = useState<any>(null)
  const [file, setFile] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [outcome, setOutcome] = useState('')
  const [busy, setBusy] = useState(false)
  const load = () => api.get<any>(`/api/cases/${c.id}/decision`).then(setD).catch(e => toast(e.message, true))
  useEffect(() => { load() }, [c.id])
  useEffect(() => {                                      // a pending record is learned when the review is ready
    if (d?.record?.status !== 'pending') return
    const t = window.setTimeout(load, 10000)
    return () => window.clearTimeout(t)
  }, [d])

  const submit = async () => {
    const fd = new FormData()
    if (file) fd.append('file', file)
    else fd.append('text', text)
    if (outcome) fd.append('outcome', outcome)
    setBusy(true)
    try { await api.upload('/api/cases/' + c.id + '/decision', fd); setFile(null); setText(''); toast('ההחלטה נקלטה'); load() }
    catch (e: any) { toast(e.message, true) }
    finally { setBusy(false) }
  }

  const rec = d?.record
  const res = rec?.result ?? {}
  return (
    <div className="decision">
      {rec ? (
        <section className="card-sub">
          <h3>החלטת הוועדה: {rec.outcome_he}</h3>
          {rec.status === 'pending' && <p className="notice">ההחלטה נקלטה. ההשוואה לבדיקה תיעשה כשהבדיקה תסתיים.</p>}
          {rec.status === 'failed' && <p className="notice warn">הלמידה נכשלה: {res.error}</p>}
          {rec.reasons.length > 0 && <ol className="small">{rec.reasons.map((r: any, i: number) => (
            <li key={i}>{r.text_he}{r.topics_he.length > 0 && <span className="muted"> · {r.topics_he.join(', ')}</span>}</li>))}</ol>}
          {rec.status === 'done' && <>
            <h4>מה המערכת למדה</h4>
            <ul className="small">
              <li><b>אומת על ידי הוועדה ({res.confirmed?.length ?? 0}):</b> {res.confirmed?.map((x: any) => x.title_he).join(' · ') || '—'}</li>
              {!res.approved && <li><b>נימוקים שהבדיקה לא זיהתה ({res.missed?.length ?? 0}):</b> {res.missed?.map((x: any) => x.text_he).join(' · ') || '—'}
                {res.drafts_created > 0 && <> — נוספו {res.drafts_created} טיוטות כלל לאישור ב<Link to="/rules/sources">סריקת מקורות</Link></>}</li>}
              {res.approved && <li><b>ממצאים שהוועדה לא העלתה באישור ({res.possible_false_defects?.length ?? 0}):</b> {res.possible_false_defects?.map((x: any) => x.title_he).join(' · ') || '—'}</li>}
            </ul>
            <p className="small muted">נוסח ההחלטה נוסף לבסיס הידע של הרשות. כלל חדש נכנס לתוקף רק לאחר אישור מנהל.</p>
          </>}
        </section>
      ) : <p className="small muted">לא נקלטה החלטת ועדה לבקשה זו.</p>}

      {can('learning.manage') && (
        <section className="card-sub">
          <h3>{rec ? 'עדכון החלטת הוועדה' : 'קליטת החלטת ועדה ללמידה'}</h3>
          <label className="field">קובץ ההחלטה (PDF, DOCX, TXT)
            <input type="file" accept=".pdf,.docx,.txt" onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
          {!file && <label className="field">או נוסח ההחלטה
            <textarea rows={5} value={text} onChange={e => setText(e.target.value)} placeholder="הדביקו את נוסח החלטת הוועדה, כולל הנימוקים או התנאים" /></label>}
          <label className="field">תוצאה
            <select value={outcome} onChange={e => setOutcome(e.target.value)}>
              <option value="">זיהוי אוטומטי מהנוסח</option>
              {Object.entries(d?.outcomes ?? {}).map(([k, v]) => <option key={k} value={k}>{String(v)}</option>)}
            </select></label>
          <button className="primary" disabled={busy || (!file && !text.trim())} onClick={submit}>{busy ? 'קולט…' : 'קליטה ולמידה'}</button>
        </section>
      )}

      {d?.precedents?.length > 0 && (
        <section className="card-sub">
          <h3>החלטות קודמות בבקשות דומות</h3>
          <ul className="small">{d.precedents.map((p: any, i: number) => (
            <li key={i}><span className="ltr">{p.case_number}</span> — {p.outcome_he}
              {p.plans.length > 0 && <> · תכנית {p.plans.join(', ')}</>}{p.same_block && <> · אותו גוש</>}
              {p.topics_he.length > 0 && <span className="muted"> · {p.topics_he.join(', ')}</span>}</li>))}</ul>
          <p className="small muted">לידיעה בלבד — אינן ממצאים בבקשה זו.</p>
        </section>
      )}
    </div>
  )
}
