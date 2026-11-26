import { useEffect, useState } from 'react'
import { Case, api } from '../api'

const ST: Record<string, string> = { PASS: 'עומד', CONFIRMED_VIOLATION: 'הפרה מאומתת', DOCUMENT_INCONSISTENCY: 'מסמך חסר / לא תואם',
  DECLARATION_MISMATCH: 'אי-התאמה להצהרה', DISCRETIONARY_REVIEW_REQUIRED: 'נדרש שיקול דעת', UNRESOLVED: 'לא מוכרע',
  NOT_APPLICABLE: 'לא חל', EXECUTION_ERROR: 'שגיאת הרצה' }
const GATE: Record<string, string> = { verified_source: 'מקור מאומת', geographic_applicability: 'תחולה מרחבית', temporal_applicability: 'תחולה בזמן',
  evidence: 'ראיה', units_and_comparison: 'יחידות והשוואה', exceptions_considered: 'חריגים', reliefs_considered: 'הקלות',
  measurement_uncertainty: 'אי-ודאות מדידה', relevance: 'רלוונטיות', current_version: 'גרסה נוכחית' }

/** Internal accuracy view of the latest run: V11 check statuses, coverage and the evidence gates of each finding. */
export default function AccuracyPanel({ c }: { c: Case }) {
  const [d, setD] = useState<any>(null), [err, setErr] = useState('')
  useEffect(() => { setD(null); if (c.last_run) api.get<any>(`/api/runs/${c.last_run.id}/findings/normalised`).then(setD).catch(e => setErr(e.message)) }, [c.last_run?.id])
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
        <td>{ST[f.check_status] ?? f.check_status}{f.external_eligible && <div className="chip bad">לדוח החיצוני</div>}</td>
        <td className="num">{f.measured_value ?? '—'} / {f.operator ?? ''} {f.permitted_value ?? '—'}{f.difference != null && <> / {f.difference > 0 ? '+' : ''}{f.difference}</>} {f.units ?? ''}</td>
        <td>{f.evidence_category ?? '—'}{f.method && <div className="muted">{f.method}</div>}</td>
        <td>{Object.entries(f.gates).filter(([, v]) => v !== 'PASS').map(([g, v]) => <span key={g} className={'chip ' + (v === 'FAIL' ? 'bad' : 'outline')} style={{ marginInlineEnd: 3 }}>{GATE[g] ?? g}{v === 'NOT_EVALUATED' ? ' (לא נבדק)' : ''}</span>)}</td></tr>)}
      {!open.length && <tr><td colSpan={5} className="empty">אין ממצאים פתוחים</td></tr>}
    </tbody></table></div>
  </div>
}
