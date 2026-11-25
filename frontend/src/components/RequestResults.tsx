import { Case, Citation, Finding, Report, openBlob } from '../api'

// The check results of a request as a reviewer's defects report: CONFIRMED DEFECTS and DOCUMENTED DISCREPANCIES first
// (what goes to the applicant — the external report), then, folded, the internal record: requirements of a later
// licensing stage, checks not completed, and the checks that passed. The status is set by the server (flag STATUS_*,
// EXTERNAL = in the defects report); a finding with sub-items (e.g. one per building) shows each item.

type St = 'CONFIRMED_DEFECT' | 'DOCUMENTED_DISCREPANCY' | 'FUTURE_STAGE' | 'UNRESOLVED' | 'NOT_CHECKED' | 'PASS' | 'NOT_APPLICABLE'

export const statusOf = (f: Finding): St =>
  (f.flags.find(x => x.startsWith('STATUS_'))?.slice(7) as St) ?? (f.status === 'PASS' ? 'PASS' : f.status === 'NA' ? 'NOT_APPLICABLE' : 'UNRESOLVED')
export const issueOf = (f: Finding) => f.flags.find(x => x.startsWith('ISSUE_'))?.slice(6) ?? ''
const ISSUE_HE: Record<string, string> = { MISSING: 'חסר', CONFLICT: 'סתירה', INVALID: 'לא תקין' }
const DECISION_HE: Record<string, string> = {
  RETURN_FOR_CORRECTIONS: 'החזרה לתיקון ולהשלמה', REJECT_RECOMMENDATION: 'המלצה לדחייה',
  NO_DEFECTS_IDENTIFIED: 'לא נמצאו ליקויים בבדיקות שהושלמו', INSUFFICIENT_EVIDENCE_FOR_FINAL_DECISION: 'אין די ראיות להמלצה סופית',
}

const topic = (f: Finding) => f.title_he.replace(/^תנאי להיתר[^:]*:\s*/, '').replace(/^הבקשה כוללת\s*/, '').replace(/\s*\(.*?\)\s*$/, '')
const plain = (s: string) => s.split(' | ').filter(x => !x.startsWith('הכלל טרם אושר')).join(' | ')
const docEvidence = (f: Finding) => (f.evidence ?? []).filter((e: any) => e.type === 'document' || e.type === 'measurement')
const itemsOf = (f: Finding) => (f.evidence ?? []).filter((e: any) => e.type === 'item')

interface Line { key: string; f: Finding; title: string; found: string; diff?: string; where?: string; correction?: string; ev: any[] }

function lines(f: Finding, want: St[]): Line[] {
  const all = itemsOf(f)
  const subs = all.filter((it: any) => want.includes(it.review) && !it.internal)
  if (all.length) return subs.map((it: any, i: number) => ({
    key: `${f.id}-${i}`, f, title: it.title_he, found: it.found_he, diff: it.diff, where: it.where_he,
    correction: it.correction_he, ev: (it.evidence ?? []).filter((e: any) => e.type === 'document' || e.type === 'measurement')}))
  return [{ key: f.id, f, title: topic(f), found: plain(f.explanation_he), correction: f.fix_hint_he ?? undefined, ev: docEvidence(f) }]
}

interface Props { c: Case; report: Report; onCite: (c: Citation) => void; onSelect: (id: string) => void }

export default function RequestResults({ c, report, onCite, onSelect }: Props) {
  const ext = report.findings.filter(f => f.flags.includes('EXTERNAL'))
  const defects: Line[] = [], discrepancies: Line[] = []
  for (const f of ext) {
    if (itemsOf(f).length) {
      defects.push(...lines(f, ['CONFIRMED_DEFECT']))
      discrepancies.push(...lines(f, ['DOCUMENTED_DISCREPANCY']))
    } else (statusOf(f) === 'CONFIRMED_DEFECT' ? defects : discrepancies).push(...lines(f, []))
  }
  const by = (s: St) => report.findings.filter(f => statusOf(f) === s && !f.flags.includes('EXTERNAL'))
  const future = by('FUTURE_STAGE'), open = [...by('UNRESOLVED'), ...by('NOT_CHECKED')], ok = by('PASS')
  const internal = report.findings.filter(f => f.flags.includes('INTERNAL') && ['CONFIRMED_DEFECT', 'DOCUMENTED_DISCREPANCY'].includes(statusOf(f)))
  const rv = report.run.review
  const runId = c.last_run?.id
  let n = 0

  const Item = ({ l, tone }: { l: Line; tone: string }) => {
    const cite = l.f.citations[0]
    n += 1
    return (
      <li className={`rr-item ${tone}`} onClick={() => onSelect(l.f.id)}>
        <div className="rr-num num">{String(n).padStart(2, '0')}</div>
        <div className="rr-body">
          <div className="rr-topic">{l.title}{issueOf(l.f) && <span className="rr-tag">{ISSUE_HE[issueOf(l.f)] ?? ''}</span>}</div>
          <div className="rr-found">{l.found}</div>
          {l.diff && <div className="rr-req"><b>פער:</b> {l.diff}</div>}
          {l.where && <div className="rr-req"><b>היכן:</b> {l.where}</div>}
          <div className="rr-req"><b>תיקון נדרש:</b> {l.correction || 'לתקן או להבהיר בהתאם לממצא'}</div>
          {(l.ev.length > 0 || cite) && (
            <div className="rr-ev">
              {l.ev.slice(0, 2).map((e: any, i: number) => <div key={i}>אסמכתה: {e.file}{e.page ? `, עמ׳/גיליון ${e.page}` : ''}{e.quote ? ` — ״${e.quote.length > 140 ? e.quote.slice(0, 140) + '…' : e.quote}״` : ''}</div>)}
              {cite && <button className="cite" onClick={e => { e.stopPropagation(); onCite(cite) }}>
                מקור הדרישה: {cite.title_he.split(' — ')[0]}{cite.section ? ` · ${cite.section}` : ''}</button>}
            </div>)}
        </div>
      </li>)
  }

  const Folded = ({ id, title, lead, list }: { id: string; title: string; lead: string; list: Finding[] }) => list.length ? (
    <details id={id} className="rr-sec internal">
      <summary><h3>{title} <span className="count num">{list.length}</span></h3><span className="rr-lead">{lead}</span></summary>
      <ul className="rr-ok">{list.map(f => <li key={f.id} onClick={() => onSelect(f.id)}>{topic(f)}
        <span className="small muted"> — {plain(f.explanation_he).slice(0, 160)}</span></li>)}</ul>
    </details>) : null

  return (
    <div className="rr">
      <div className="rr-top">
        <div>
          <div className="rr-kicker">בקשה <span className="ltr">{c.case_number}</span>{c.gush ? ` · גוש ${c.gush}` : ''}{c.helka ? ` חלקה ${c.helka}` : ''} · בדיקה {report.run.version}, {new Date(report.run.at).toLocaleDateString('he-IL')}{rv ? ` · שלב: ${rv.stage_he}` : ''}</div>
          <h2 className="rr-title">דוח ליקויים – בקשה להיתר מס׳ <span className="ltr">{c.case_number}</span></h2>
        </div>
        {runId && <div className="row no-print">
          <button className="sm" onClick={() => openBlob(`/api/runs/${runId}/defects.pdf`)}>דוח ליקויים PDF</button>
          <button className="sm" onClick={() => openBlob(`/api/runs/${runId}/defects.docx`, `defects_${c.case_number}.docx`)}>Word</button>
        </div>}
      </div>

      <div className="rr-cards">
        <a href="#rr-defects" className={`rr-card invalid${defects.length ? '' : ' zero'}`}><span className="n num">{defects.length}</span><span>ליקויים</span></a>
        <a href="#rr-disc" className={`rr-card disc${discrepancies.length ? '' : ' zero'}`}><span className="n num">{discrepancies.length}</span><span>פערים לבירור</span></a>
        <a href="#rr-future" className="rr-card open"><span className="n num">{future.length}</span><span>שלב רישוי מאוחר</span></a>
        <a href="#rr-open" className="rr-card open"><span className="n num">{open.length}</span><span>לא הושלמו</span></a>
        <a href="#rr-OK" className="rr-card ok"><span className="n num">{ok.length}</span><span>תקין</span></a>
      </div>
      {rv && <p className={'rr-verdict' + (rv.decision === 'NO_DEFECTS_IDENTIFIED' ? ' good' : ' bad')}>
        המלצה: {DECISION_HE[rv.decision] ?? rv.decision}{rv.decision_why ? ` — ${rv.decision_why}` : ''}
        <span className="small muted"> · הושלמו {rv.coverage.completed} מתוך {rv.coverage.applicable} בדיקות</span></p>}

      {defects.length > 0 && <section id="rr-defects" className="rr-sec invalid">
        <h3>ליקויים <span className="count num">{defects.length}</span></h3>
        <p className="rr-lead">ממצאים שאומתו בראיות ומחייבים תיקון</p>
        <ol className="rr-list">{defects.map(l => <Item key={l.key} l={l} tone="defect" />)}</ol>
      </section>}
      {discrepancies.length > 0 && <section id="rr-disc" className="rr-sec disc">
        <h3>פערים מתועדים לבירור <span className="count num">{discrepancies.length}</span></h3>
        <p className="rr-lead">פערים בין מקורות שנוגעים ישירות לבקשה — אינם מיוחסים אוטומטית לעורך הבקשה</p>
        <ol className="rr-list">{discrepancies.map(l => <Item key={l.key} l={l} tone="discrepancy" />)}</ol>
      </section>}
      {!defects.length && !discrepancies.length && <p className="rr-verdict good">לא נמצאו ליקויים בבדיקות שהושלמו.</p>}

      <h3 className="rr-internal-title">רשומה פנימית — לא נכללת בדוח הליקויים</h3>
      <Folded id="rr-future" title="דרישות לשלב רישוי מאוחר" lead="תנאים לבקרת תכן או למתן ההיתר — אינם ליקוי בשלב הנוכחי" list={future} />
      <Folded id="rr-open" title="בדיקות שלא הושלמו" lead="אין די נתונים בבקשה או שהבדיקה אינה ממומשת עדיין" list={open} />
      <Folded id="rr-internal" title="ממצאים פנימיים" lead="סטטוס רשמי במאגר ונתונים שאינם ראיה עצמאית" list={internal} />
      <Folded id="rr-OK" title="תקין" lead="בדיקות שעברו" list={ok} />
      <p className="small muted rr-note">ההמלצה היא של מערכת הבדיקה ואינה החלטת רשות הרישוי. לחיצה על פריט מציגה את פירוטו המלא.</p>
    </div>
  )
}
