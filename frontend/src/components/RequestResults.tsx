import { Case, Citation, Finding, Report } from '../api'

// The check results of a request in the reviewer's three words: what is MISSING, what CONFLICTS, what is INVALID.
// Each item: the topic, one sentence of what was found, what is required, and the evidence (file, page, quote).
// The category is set by the server (flag ISSUE_*); OK and undecided items are kept out of the way.

type Issue = 'MISSING' | 'CONFLICT' | 'INVALID' | 'OPEN' | 'OK' | 'NA'

export const issueOf = (f: Finding): Issue =>
  (f.flags.find(x => x.startsWith('ISSUE_'))?.slice(6) as Issue) ?? (f.status === 'PASS' ? 'OK' : f.status === 'NA' ? 'NA' : 'OPEN')

const SECTIONS: { key: Issue; title: string; lead: string; tone: string }[] = [
  { key: 'MISSING', title: 'חסר', lead: 'מסמכים, אישורים או נתונים שלא הוגשו, ותנאים שטרם התקיימו', tone: 'missing' },
  { key: 'CONFLICT', title: 'סתירה', lead: 'מסמכים שאינם מתאימים זה לזה או לבקשה', tone: 'conflict' },
  { key: 'INVALID', title: 'לא תקין', lead: 'ערכים החורגים מהמותר, מסמכים שפג תוקפם או שאינם מהגורם הנדרש', tone: 'invalid' },
]

const topic = (f: Finding) => f.title_he.replace(/^תנאי להיתר[^:]*:\s*/, '').replace(/^הבקשה כוללת\s*/, '').replace(/\s*\(.*?\)\s*$/, '')
const plain = (s: string) => s.split(' | ').filter(x => !x.startsWith('הכלל טרם אושר')).join(' | ')
const docEvidence = (f: Finding) => (f.evidence ?? []).filter((e: any) => e.type === 'document')

function required(f: Finding, issue: Issue): string {
  if (f.fix_hint_he) return f.fix_hint_he
  if (issue === 'MISSING') return `להגיש: ${topic(f)}`
  if (issue === 'CONFLICT') return 'ליישב את הסתירה ולהגיש מסמכים מתואמים'
  return 'לתקן את הבקשה בהתאם לדרישה'
}

interface Props { c: Case; report: Report; onCite: (c: Citation) => void; onSelect: (id: string) => void }

export default function RequestResults({ c, report, onCite, onSelect }: Props) {
  const by: Record<Issue, Finding[]> = { MISSING: [], CONFLICT: [], INVALID: [], OPEN: [], OK: [], NA: [] }
  for (const f of report.findings) by[issueOf(f)].push(f)
  const problems = by.MISSING.length + by.CONFLICT.length + by.INVALID.length
  const verdict = problems === 0
    ? (by.OPEN.length ? `לא נמצאו חוסרים, סתירות או אי־תקינות; ${by.OPEN.length} נושאים טרם הוכרעו.` : 'הבקשה שלמה ותקינה בכל הכללים שנבדקו.')
    : `הבקשה אינה ניתנת לאישור במצבה הנוכחי: ${[by.MISSING.length && `${by.MISSING.length} חסרים`, by.CONFLICT.length && `${by.CONFLICT.length} סתירות`,
        by.INVALID.length && `${by.INVALID.length} פריטים לא תקינים`].filter(Boolean).join(', ')}.`
  const order = [...by.MISSING, ...by.CONFLICT, ...by.INVALID, ...by.OPEN]
  const numOf = (f: Finding) => order.indexOf(f) + 1   // one running number across the sections

  const Item = ({ f, issue }: { f: Finding; issue: Issue }) => {
    const ev = docEvidence(f)
    const cite = f.citations[0]
    return (
      <li className="rr-item" onClick={() => onSelect(f.id)}>
        <div className="rr-num num">{numOf(f)}</div>
        <div className="rr-body">
          <div className="rr-topic">{topic(f)}</div>
          <div className="rr-found">{plain(f.explanation_he)}</div>
          {issue !== 'OPEN' && <div className="rr-req"><b>נדרש:</b> {required(f, issue)}</div>}
          {(ev.length > 0 || cite) && (
            <div className="rr-ev">
              {ev.slice(0, 2).map((e: any, i: number) => <div key={i}>ראיה: {e.file}{e.page ? `, עמ׳ ${e.page}` : ''} — ״{e.quote.length > 110 ? e.quote.slice(0, 110) + '…' : e.quote}״</div>)}
              {cite && <button className="cite" onClick={e => { e.stopPropagation(); onCite(cite) }}>
                מקור הדרישה: {cite.title_he.split(' — ')[0]}{cite.section ? ` · ${cite.section}` : ''}</button>}
            </div>)}
        </div>
      </li>)
  }

  return (
    <div className="rr">
      <div className="rr-top">
        <div>
          <div className="rr-kicker">בקשה <span className="ltr">{c.case_number}</span>{c.gush ? ` · גוש ${c.gush}` : ''}{c.helka ? ` חלקה ${c.helka}` : ''} · בדיקה {report.run.version}, {new Date(report.run.at).toLocaleDateString('he-IL')}</div>
          <h2 className="rr-title">תוצאות בדיקת הבקשה</h2>
        </div>
        <button className="sm no-print" onClick={() => window.print()}>הדפסה / PDF</button>
      </div>

      <div className="rr-cards">
        {SECTIONS.map(s => (
          <a key={s.key} href={`#rr-${s.key}`} className={`rr-card ${s.tone}${by[s.key].length ? '' : ' zero'}`}>
            <span className="n num">{by[s.key].length}</span><span>{s.title}</span></a>))}
        <a href="#rr-OK" className="rr-card ok"><span className="n num">{by.OK.length}</span><span>תקין</span></a>
        {by.OPEN.length > 0 && <a href="#rr-OPEN" className="rr-card open"><span className="n num">{by.OPEN.length}</span><span>טרם הוכרע</span></a>}
      </div>
      <p className={'rr-verdict' + (problems ? ' bad' : ' good')}>{verdict}</p>

      {SECTIONS.filter(s => by[s.key].length).map(s => (
        <section key={s.key} id={`rr-${s.key}`} className={`rr-sec ${s.tone}`}>
          <h3>{s.title} <span className="count num">{by[s.key].length}</span></h3>
          <p className="rr-lead">{s.lead}</p>
          <ol className="rr-list">{by[s.key].map(f => <Item key={f.id} f={f} issue={s.key} />)}</ol>
        </section>))}

      {by.OPEN.length > 0 && (
        <details id="rr-OPEN" className="rr-sec open">
          <summary><h3>טרם הוכרע <span className="count num">{by.OPEN.length}</span></h3>
            <span className="rr-lead">המערכת לא מצאה במסמכים תשובה חד־משמעית — בעיקר נתונים שמופיעים רק בשרטוט</span></summary>
          <ol className="rr-list">{by.OPEN.map(f => <Item key={f.id} f={f} issue="OPEN" />)}</ol>
        </details>)}

      <details id="rr-OK" className="rr-sec ok">
        <summary><h3>תקין <span className="count num">{by.OK.length}</span></h3></summary>
        <ul className="rr-ok">{by.OK.map(f => <li key={f.id} onClick={() => onSelect(f.id)}>✓ {topic(f)}
          {docEvidence(f)[0] && <span className="small muted"> — {docEvidence(f)[0].file}</span>}</li>)}</ul>
      </details>
      <p className="small muted rr-note">המלצה בלבד; ההחלטה בסמכות הבודק המוסמך. כל פריט מבוסס על כלל ואסמכתה — לחיצה על פריט מציגה את פירוטו המלא.</p>
    </div>
  )
}
