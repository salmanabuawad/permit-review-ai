import { useEffect, useState } from 'react'
import { Case, api } from '../api'

const GROUPS: [string, string, string][] = [['new_defects', 'ליקויים חדשים', 'bad'], ['corrected', 'ליקויים שתוקנו', 'ok'],
  ['newly_unresolved', 'הפכו ללא מוכרעים', 'warn'], ['newly_applicable', 'דרישות שחלות מעתה', 'warn'],
  ['unchanged_defects', 'ליקויים ללא שינוי', 'outline'], ['other_changes', 'שינויים אחרים', 'outline']]
const ST: Record<string, string> = { PASS: 'עומד', FAIL: 'לא עומד', UNCERTAIN: 'דורש בדיקה', NA: 'לא חל' }
const show = (v: any) => v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v)

/** What changed since the previous run of the case, and the exact inputs behind each change (dependency graph). */
export default function RevisionPanel({ c }: { c: Case }) {
  const [d, setD] = useState<any>(null), [err, setErr] = useState('')
  useEffect(() => { setD(null); if (c.last_run) api.get<any>(`/api/runs/${c.last_run.id}/revision`).then(setD).catch(e => setErr(e.message)) }, [c.last_run?.id])
  if (!c.last_run) return <div className="empty">אין הרצה</div>
  if (err) return <div className="notice small">{err}</div>
  if (!d) return <div className="empty">טוען…</div>
  if (d.previous == null) return <div className="empty">זו ההרצה הראשונה של התיק — אין גרסה קודמת להשוואה</div>
  const g = d.pdg ?? {}
  return <div>
    <div className="card-head"><b>גרסה {d.run} מול {d.previous}</b>
      <span className="small muted">קבצים: {d.files.added.length} נוספו · {d.files.changed.length} השתנו · {d.files.removed.length} הוסרו · {d.files.unchanged} ללא שינוי{d.ruleset_changed ? ' · מאגר הכללים השתנה' : ''}</span></div>
    {g.nodes != null && <div className="small muted" style={{ marginBottom: 8 }}>גרף תלויות: {g.unchanged_inputs} בדיקות עם קלטים זהים לגרסה הקודמת · {g.changed_inputs} עם קלט שהשתנה
      {g.parity_violations?.length > 0 ? <span className="chip bad" style={{ marginInlineStart: 6 }}>תלות חסרה: {g.parity_violations.join(', ')}</span> : ' · בדיקת עקביות תקינה'}</div>}
    {[...d.files.added.map((f: string) => ['נוסף', f]), ...d.files.changed.map((f: string) => ['השתנה', f]), ...d.files.removed.map((f: string) => ['הוסר', f])].map(([k, f]: any) =>
      <div key={k + f} className="small">{k}: <span className="ltr">{f}</span></div>)}
    {GROUPS.map(([key, label, tone]) => (d[key] ?? []).length > 0 && <div key={key} style={{ marginTop: 10 }}>
      <div><span className={'chip ' + tone}>{label} ({d[key].length})</span></div>
      {d[key].map((x: any) => <div key={x.rule_id} className="hit"><b className="ltr">{x.rule_id}</b> {x.title_he} — {ST[x.before] ?? x.before ?? '—'} ← {ST[x.after] ?? x.after ?? '—'}
        {x.changed_inputs?.length > 0 && <div className="small muted">{x.changed_inputs.map((i: any) => `${i.input}: ${show(i.before)} → ${show(i.after)}`).join(' · ')}</div>}</div>)}
    </div>)}
  </div>
}
