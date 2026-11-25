import { Case, Citation, Finding, OP_HE, Report, STATUS_HE, fmt } from '../api'

// The check results as a professional defects report (the layout reviewers asked for): a verdict, the request data,
// a numbered table of defects with the required correction, one section per defect, then what must be added, the
// conditions for the permit, the checks left to the reviewer, a lettered list of actions and the sources.
// Everything comes from the rule engine's findings — nothing here is decided by this page.

type Cat = 'defect' | 'missing' | 'condition' | 'review' | 'pass' | 'na'

// The system's answer is the computed result: a FAIL on a rule that is not yet professionally approved is shown
// with status UNCERTAIN (not applied as a rejection) but it is still the answer the documents give.
export function categorize(f: Finding): Cat {
  const r = f.computed_result ?? f.status
  const cond = f.flags.includes('CONDITION_FOR_PERMIT') || /^תנאי/.test(f.title_he)
  if (r === 'PASS') return 'pass'
  if (r === 'NA') return 'na'
  if (r === 'FAIL') return cond ? 'condition' : 'defect'
  if (f.flags.includes('INCOMPLETE')) return 'missing'
  if (cond) return 'condition'
  return 'review'
}
const condState = (f: Finding) => (f.computed_result === 'FAIL' ? 'לא התקיים' : f.computed_result === 'PASS' ? 'התקיים' : 'לא נבדק')
const docEvidence = (f: Finding) => (f.evidence ?? []).filter((e: any) => e.type === 'document')

const DECLARED: [string, string, string?][] = [
  ['main_area_m2', 'שטח עיקרי מבוקש', 'מ״ר'], ['service_area_m2', 'שטח שירות מבוקש', 'מ״ר'], ['units', 'יחידות דיור'],
  ['floors', 'מספר קומות מבוקש'], ['work_type', 'סוג העבודה'], ['main_use', 'שימוש עיקרי'],
  ['plans_declared', 'תכניות נוספות (לפי הטופס)'], ['info_file_number', 'תיק מידע להיתר'],
  ['submission_date', 'מועד הגשה'], ['trees_within_4m', 'עבודה בטווח 4 מ׳ מעץ בוגר'],
]
const WORK_HE: Record<string, string> = { new_building: 'בנייה חדשה' }
const day = (iso: string) => new Date(iso).toLocaleDateString('he-IL')
const num = (n: number) => String(n).padStart(2, '0')
// "תכנית 633-0723718 — זיקים: …" → "תכנית 633-0723718": the full title is in the source drawer, one click away
const shortTitle = (t: string) => t.split(' — ')[0].trim()
const cite = (c?: Citation) => c ? `${shortTitle(c.title_he)}${c.section ? ` · ${c.section}` : ''}${c.page ? ` · עמ׳ ${c.page}` : ''}` : '—'
// the engine appends the rule's review state to the explanation; the report states it once, in the closing note
const plain = (s: string) => s.split(' | ').filter(x => !x.startsWith('הכלל טרם אושר')).join(' | ')
const action = (f: Finding) => f.fix_hint_he || `להשלים: ${f.title_he}`

function value(v: any, unit?: string): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'כן' : 'לא'
  if (Array.isArray(v)) return v.join(', ') || '—'
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) return day(v)
  if (typeof v === 'number') return `${v.toLocaleString('he-IL', { maximumFractionDigits: 2 })}${unit ? ' ' + unit : ''}`
  return WORK_HE[v] ?? String(v)
}

function gap(f: Finding): string | null {
  if (f.measured_value === null || f.threshold === null) return null
  const d = Math.abs(f.measured_value - f.threshold)
  return `${fmt(d)}${f.units ? ' ' + f.units : ''}`
}

function verdict(groups: Record<Cat, Finding[]>): { text: string; status: string; tone: string } {
  const d = groups.defect.length, m = groups.missing.length, c = groups.condition.length, r = groups.review.length
  const open = [
    m ? `${m} נתונים או מסמכים חסרים המונעים הכרעה` : null,
    c ? `${c} תנאים למתן היתר שטרם הוצגה עמידה בהם` : null,
    r ? `${r} נושאים להכרעת הבודק` : null,
  ].filter(Boolean)
  const text = (d ? `בבדיקה נמצאו ${d} אי־התאמות לדרישות.` : 'בבדיקה לא נמצאו אי־התאמות לדרישות בכללים שנבדקו.')
    + (open.length ? ` נותרו פתוחים: ${open.join('; ')}.` : '')
  if (d) return { text, status: 'דרוש תיקון והשלמת מסמכים קודם לקבלת הבקשה כעומדת בדרישות.', tone: 'bad' }
  if (m) return { text, status: 'דרושה השלמת נתונים ומסמכים קודם להכרעה בעמידת הבקשה בדרישות.', tone: 'warn' }
  if (c || r) return { text, status: 'ניתן להמשיך להכרעת הבודק ולבדיקת התנאים למתן היתר.', tone: 'warn' }
  return { text, status: 'לא נמצאו ליקויים בכללים שנבדקו.', tone: 'ok' }
}

function Evidence({ f }: { f: Finding }) {
  const ev = docEvidence(f)
  if (!ev.length) return null
  return <div className="dr-evidence">{ev.map((e: any, i: number) => (
    <div key={i}>ראיה: {e.file}{e.page ? `, עמ׳ ${e.page}` : ''} — <span className="quote">״{e.quote}״</span></div>))}</div>
}

interface Props { c: Case; report: Report; onCite: (c: Citation) => void; onSelect: (id: string) => void }

export default function DefectsReport({ c, report, onCite, onSelect }: Props) {
  const groups = { defect: [], missing: [], condition: [], review: [], pass: [], na: [] } as Record<Cat, Finding[]>
  for (const f of report.findings) groups[categorize(f)].push(f)
  const sevOrder: Record<string, number> = { high: 0, medium: 1, low: 2 }
  for (const k of Object.keys(groups) as Cat[]) groups[k].sort((a, b) => (sevOrder[a.severity] ?? 3) - (sevOrder[b.severity] ?? 3))
  const v = verdict(groups)
  const d = c.declared ?? {}
  const actions = [...groups.defect, ...groups.missing, ...groups.condition].map(action)
  const uniqueActions = [...new Set(actions)]
  const sources = [...new Map(report.findings.flatMap(f => f.citations).map(x => [x.title_he, x])).values()]
  let sec = 3

  const Ref = ({ f }: { f: Finding }) => f.citations[0]
    ? <button className="cite" onClick={() => onCite(f.citations[0])}>{cite(f.citations[0])}</button> : <span>—</span>

  return (
    <div className="defects">
      <div className="dr-actions no-print">
        <button className="sm" onClick={() => window.print()}>הדפסה / שמירה כ־PDF</button>
      </div>
      <header className="dr-head">
        <div className="dr-kicker">בדיקת בקשה להיתר | {c.address || [c.gush && `גוש ${c.gush}`, c.helka && `חלקה ${c.helka}`].filter(Boolean).join(', ')}</div>
        <h2>דוח ליקויים מקצועי — בדיקה מפורטת</h2>
        <div className="dr-meta">
          בקשה להיתר <span className="ltr">{c.case_number}</span>
          {c.gush && <> | גוש {c.gush}</>}{c.helka && <>, חלקה {c.helka}</>}
          {d.submission_date && <> | מועד הגשה: {day(d.submission_date)}</>}
          {' '}| מועד הבדיקה: {day(report.run.at)} | גרסת בדיקה {report.run.version}
        </div>
      </header>

      <h3>1. הכרעת הבדיקה</h3>
      <p>{v.text}</p>
      <p className={'dr-status ' + v.tone}><b>סטטוס מומלץ:</b> {v.status}</p>
      {report.run.ai_summary && <details className="dr-ai"><summary>סיכום טיוטה (מודל שפה מקומי)</summary><p style={{ whiteSpace: 'pre-line' }}>{report.run.ai_summary}</p></details>}
      <p className="small muted">{report.disclaimer_he}</p>

      <h3>2. פרטי הבקשה ונתוני השרטוט</h3>
      <table className="dr-table">
        <thead><tr><th>נתון</th><th>ערך</th><th>מקור</th></tr></thead>
        <tbody>
          <tr><td>תיאור הבקשה</td><td>{c.title}</td><td>טופס הבקשה</td></tr>
          {(c.gush || c.helka) && <tr><td>גוש / חלקה</td><td className="num">{c.gush ?? '—'} / {c.helka ?? '—'}</td><td>טופס הבקשה</td></tr>}
          {c.applicable_plans?.length > 0 && <tr><td>תכניות חלות</td><td>{c.applicable_plans.join(', ')}</td><td>נתוני התיק</td></tr>}
          {DECLARED.filter(([k]) => d[k] !== undefined && d[k] !== null && d[k] !== '').map(([k, label, unit]) => (
            <tr key={k}><td>{label}</td><td className="num">{value(d[k], unit)}</td><td>טופס הבקשה (רישוי זמין)</td></tr>))}
        </tbody>
      </table>

      <h3>3. טבלת ממצאים מסכמת</h3>
      {groups.defect.length === 0
        ? <p className="dr-none">לא נמצאו אי־התאמות לדרישות בכללים שנבדקו. הנושאים הפתוחים מפורטים בסעיפים הבאים.</p>
        : <table className="dr-table">
            <thead><tr><th>מס׳</th><th>נושא</th><th>ממצא</th><th>דרישת תיקון</th></tr></thead>
            <tbody>{groups.defect.map((f, i) => (
              <tr key={f.id} onClick={() => onSelect(f.id)} className="dr-click">
                <td className="num">{num(i + 1)}</td><td>{f.title_he}</td>
                <td>{f.measured_value !== null ? `${fmt(f.measured_value)} ${f.units ?? ''}; נדרש ${f.operator ? OP_HE[f.operator] : ''} ${fmt(f.threshold)} ${f.units ?? ''}` : plain(f.explanation_he)}<Evidence f={f} /></td>
                <td>{action(f)}</td></tr>))}</tbody>
          </table>}

      {groups.defect.map((f, i) => {
        sec += 1
        const g = gap(f)
        return (
          <section key={f.id} className="dr-finding">
            <h3>{sec}. ממצא {num(i + 1)} — {f.title_he}</h3>
            <p>{plain(f.explanation_he)}</p>
            {(f.measured_value !== null || f.threshold !== null) && (
              <table className="dr-table dr-params">
                <thead><tr><th>פרמטר</th><th>ערך</th></tr></thead>
                <tbody>
                  <tr><td>ערך בבקשה / נמדד</td><td className="num">{fmt(f.measured_value)} {f.units}{f.measured_uncertainty ? ` ±${fmt(f.measured_uncertainty)}` : ''}</td></tr>
                  <tr><td>דרישה</td><td className="num">{f.operator ? OP_HE[f.operator] : ''} {fmt(f.threshold)} {f.units}</td></tr>
                  {g && <tr><td>פער מחושב</td><td className="num">{g}</td></tr>}
                </tbody>
              </table>)}
            <Evidence f={f} />
            <p><b>הוראה רלוונטית:</b> <Ref f={f} /></p>
            <p><b>דרישת תיקון:</b> {action(f)}</p>
          </section>)
      })}

      {groups.missing.length > 0 && <>
        <h3>{++sec}. נתונים ומסמכים חסרים</h3>
        <p className="small muted">ללא נתונים אלה לא ניתן לקבוע עמידה בדרישה — אין בכך קביעה שהבקשה חורגת.</p>
        <table className="dr-table">
          <thead><tr><th>נושא</th><th>מה חסר</th><th>הפעולה הנדרשת</th><th>מקור הדרישה</th></tr></thead>
          <tbody>{groups.missing.map(f => (
            <tr key={f.id} onClick={() => onSelect(f.id)} className="dr-click"><td>{f.title_he}</td><td>{plain(f.explanation_he)}</td><td>{action(f)}</td><td><Ref f={f} /></td></tr>))}</tbody>
        </table>
      </>}

      {groups.condition.length > 0 && <>
        <h3>{++sec}. תנאים למתן היתר</h3>
        <table className="dr-table">
          <thead><tr><th>תנאי</th><th>מצב</th><th>פירוט וראיה</th><th>מקור</th></tr></thead>
          <tbody>{groups.condition.map(f => (
            <tr key={f.id} onClick={() => onSelect(f.id)} className="dr-click"><td>{f.title_he}</td>
              <td><span className={'chip ' + (f.computed_result === 'FAIL' ? 'bad' : 'warn')}>{condState(f)}</span></td>
              <td>{plain(f.explanation_he)}<Evidence f={f} /></td><td><Ref f={f} /></td></tr>))}</tbody>
        </table>
      </>}

      {groups.review.length > 0 && <>
        <h3>{++sec}. בדיקות משלימות להכרעת הבודק</h3>
        <table className="dr-table">
          <thead><tr><th>נושא</th><th>מה לבדוק</th><th>מקור</th></tr></thead>
          <tbody>{groups.review.map(f => (
            <tr key={f.id} onClick={() => onSelect(f.id)} className="dr-click"><td>{f.title_he}</td><td>{plain(f.explanation_he)}</td><td><Ref f={f} /></td></tr>))}</tbody>
        </table>
      </>}

      <h3>{++sec}. החלטה מסכמת ודרישות לביצוע</h3>
      {uniqueActions.length === 0 ? <p>אין דרישות לביצוע מכללים שנבדקו.</p>
        : <ol className="dr-letters">{uniqueActions.map((a, i) => <li key={i}>{a}</li>)}</ol>}
      <p className={'dr-status ' + v.tone}><b>סטטוס מומלץ:</b> {v.status}</p>

      {groups.pass.length > 0 && <details className="dr-pass"><summary>{++sec}. נבדקו ונמצאו תקינים ({groups.pass.length})</summary>
        <table className="dr-table"><thead><tr><th>נושא</th><th>הנימוק והראיה</th></tr></thead>
          <tbody>{groups.pass.map(f => <tr key={f.id} onClick={() => onSelect(f.id)} className="dr-click"><td>{f.title_he}</td>
            <td>{plain(f.explanation_he)}<Evidence f={f} /></td></tr>)}</tbody></table></details>}

      <h3>{++sec}. מקורות</h3>
      <p className="small">מסמכי הבקשה {c.case_number}: {report.run.inputs.map((x: any) => x.file).join('; ')}.</p>
      <ul className="small dr-sources">{sources.map(s => (
        <li key={s.title_he}><button className="cite" onClick={() => onCite(s)}>{s.title_he}</button>{s.url ? <> — <a className="ltr" href={s.url} target="_blank" rel="noreferrer">{s.url}</a></> : null}</li>))}</ul>
      <p className="small muted">הערה מקצועית: הבדיקה מבוססת על המסמכים והגיליונות שהוגשו ועל כללים שטרם אושרו כולם מקצועית. אין זו חוות דעת חתומה, בדיקת ביצוע בשטח או החלטה של רשות הרישוי. סטטוס ממצא: {Object.entries(STATUS_HE).map(([k, l]) => `${l} ${report.findings.filter(f => f.status === k).length}`).join(' · ')}.</p>
    </div>
  )
}
