import { useEffect, useState } from 'react'
import { Case, api } from '../api'
import { useApp } from '../App'

const ST: Record<string, string> = { PASS: 'עומד', CONFIRMED_VIOLATION: 'הפרה מאומתת', DOCUMENT_INCONSISTENCY: 'מסמך חסר / לא תואם',
  DECLARATION_MISMATCH: 'אי-התאמה להצהרה', DISCRETIONARY_REVIEW_REQUIRED: 'נדרש שיקול דעת', UNRESOLVED: 'לא מוכרע',
  NOT_APPLICABLE: 'לא חל', EXECUTION_ERROR: 'שגיאת הרצה' }
const GATE: Record<string, string> = { verified_source: 'מקור מאומת', geographic_applicability: 'תחולה מרחבית', temporal_applicability: 'תחולה בזמן',
  evidence: 'ראיה', units_and_comparison: 'יחידות והשוואה', exceptions_considered: 'חריגים', reliefs_considered: 'הקלות',
  measurement_uncertainty: 'אי-ודאות מדידה', relevance: 'רלוונטיות', current_version: 'גרסה נוכחית' }

/** Internal accuracy view of the latest run: V11 check statuses, coverage and the evidence gates of each finding. */
const CAT: Record<string, string> = { algorithm_defect: 'פגם באלגוריתם / מדידה', extraction_error: 'שגיאת חילוץ', interpretation_error: 'שגיאת פרשנות',
  missing_knowledge: 'ידע חסר', application_exception: 'חריג ספציפי לבקשה', prompt_deficiency: 'ליקוי בהנחיה למודל', unclassified: 'לא סווג' }

function Decide({ f, done }: { f: any; done: () => void }) {
  const { toast } = useApp()
  const [note, setNote] = useState(''), [cat, setCat] = useState('algorithm_defect'), [fix, setFix] = useState('PASS'), [busy, setBusy] = useState(false)
  const send = async (decision: string) => {
    setBusy(true)
    try {
      const r = await api.post<any>(`/api/findings/${f.finding_id}/decision`, decision === 'CONFIRMED' ? { decision, note: note || 'אושר' }
        : { decision, note, category: cat, corrected_status: fix })
      toast(r.feedback_id ? 'הממצא נדחה; נוצרה רשומת משוב' : 'הממצא אושר'); done()
    } catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }
  return <div className="user-actions" style={{ marginTop: 4 }}>
    <input placeholder="נימוק (חובה לדחייה)" value={note} onChange={e => setNote(e.target.value)} style={{ minWidth: 140 }} />
    <button className="sm" disabled={busy} onClick={() => send('CONFIRMED')}>אישור</button>
    <select value={cat} onChange={e => setCat(e.target.value)} aria-label="סיבת הדחייה">{Object.entries(CAT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
    <select value={fix} onChange={e => setFix(e.target.value)} aria-label="התוצאה הנכונה"><option value="PASS">נכון: עומד</option><option value="NA">נכון: לא חל</option><option value="UNCERTAIN">נכון: דורש בדיקה</option><option value="FAIL">נכון: לא עומד</option></select>
    <button className="sm danger" disabled={busy || note.trim().length < 5} onClick={() => send('OVERRIDDEN')}>דחייה</button>
  </div>
}

export default function AccuracyPanel({ c }: { c: Case }) {
  const { can } = useApp()
  const [d, setD] = useState<any>(null), [err, setErr] = useState(''), [tick, setTick] = useState(0)
  useEffect(() => { setD(null); if (c.last_run) api.get<any>(`/api/runs/${c.last_run.id}/findings/normalised`).then(setD).catch(e => setErr(e.message)) }, [c.last_run?.id, tick])
  if (!c.last_run) return <div className="empty">אין הרצה</div>
  if (err) return <div className="notice small">{err}</div>
  if (!d) return <div className="empty">טוען…</div>
  const open = d.findings.filter((f: any) => !['PASS', 'NOT_APPLICABLE'].includes(f.check_status))
  return <div>
    <div className="card-head"><span className="chip outline">בקרה פנימית — לא חלק מהדוח</span>
      <span className="small muted">{d.coverage.applicable} בדיקות חלות מתוך {d.coverage.checks} · הוכרעו {d.coverage.decided} · מדידה עצמאית: {d.coverage.independent_measurement.measured}/{d.coverage.independent_measurement.numeric_checks} בדיקות מספריות</span></div>
    <div className="summary-strip">{Object.entries(d.coverage.by_status).map(([k, n]) => <div key={k}><b className="num">{n as number}</b><span>{ST[k] ?? k}</span></div>)}</div>
    <div style={{ overflowX: 'auto' }}><table className="small"><thead><tr><th>ממצא</th><th>מצב</th><th>נמדד / מותר / הפרש</th><th>ראיה</th><th>שערים שלא עברו</th></tr></thead><tbody>
      {open.map((f: any) => <tr key={f.finding_id}><td><b>{f.rule_id}</b> <span className="muted ltr">v{f.rule_version}</span><div>{f.description}</div></td>
        <td>{ST[f.check_status] ?? f.check_status}{f.external_eligible && <div className="chip bad">לדוח החיצוני</div>}
          {f.professional_validation !== 'PENDING' ? <div className="chip outline">{f.professional_validation === 'CONFIRMED' ? 'אושר ע״י בודק' : 'נדחה ע״י בודק'}</div>
            : can('finding.decide') && !c.last_run?.locked && <Decide f={f} done={() => setTick(t => t + 1)} />}</td>
        <td className="num">{f.measured_value ?? '—'} / {f.operator ?? ''} {f.permitted_value ?? '—'}{f.difference != null && <> / {f.difference > 0 ? '+' : ''}{f.difference}</>} {f.units ?? ''}</td>
        <td>{f.evidence_category ?? '—'}{f.method && <div className="muted">{f.method}</div>}</td>
        <td>{Object.entries(f.gates).filter(([, v]) => v !== 'PASS').map(([g, v]) => <span key={g} className={'chip ' + (v === 'FAIL' ? 'bad' : 'outline')} style={{ marginInlineEnd: 3 }}>{GATE[g] ?? g}{v === 'NOT_EVALUATED' ? ' (לא נבדק)' : ''}</span>)}</td></tr>)}
      {!open.length && <tr><td colSpan={5} className="empty">אין ממצאים פתוחים</td></tr>}
    </tbody></table></div>
  </div>
}
