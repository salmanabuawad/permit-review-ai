import { useEffect, useMemo, useState } from 'react'
import { Case, Citation, Finding, OP_HE, Report, SEV_HE, STATUS_HE, fmt } from '../api'
import DefectsReport from './DefectsReport'
import FindingCard, { StatusChip } from './FindingCard'

// The findings of a check run as a clear, filterable list: a count per result and per decision (each one a filter),
// filters by text / severity / decision / source / flags, grouping by result or by source, and one line per finding
// that opens into the full card. Filters are kept per browser so a reviewer returns to the same view.

type Status = Finding['status']
const STATUSES: Status[] = ['FAIL', 'UNCERTAIN', 'PASS', 'NA']
const SEV_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 }
const DECISIONS: Record<string, string> = { all: 'כל ההחלטות', pending: 'ממתין להחלטה', CONFIRMED: 'אושר ע"י בודק', OVERRIDDEN: 'נדחה ע"י בודק' }
const NEEDS_DECISION = (f: Finding) => f.status === 'FAIL' || f.status === 'UNCERTAIN'

interface Filters {
  statuses: Status[]; text: string; severity: string; decision: string; source: string
  conditionsOnly: boolean; unapprovedOnly: boolean; group: 'status' | 'source' | 'none'
}
const DEFAULTS: Filters = { statuses: ['FAIL', 'UNCERTAIN', 'PASS'], text: '', severity: 'all', decision: 'all', source: 'all',
  conditionsOnly: false, unapprovedOnly: false, group: 'status' }
const KEY = 'bbp_findings_filters_v1'

function load(): Filters {
  try { return { ...DEFAULTS, ...JSON.parse(window.localStorage.getItem(KEY) || '{}') } } catch { return DEFAULTS }
}

const sourceOf = (f: Finding) => f.citations[0]?.title_he?.trim() || 'ללא מקור'
const decisionOf = (f: Finding) => !NEEDS_DECISION(f) ? 'none' : (f.reviewer_decision || 'pending')

interface Props {
  c: Case; report: Report | null; kind: string; setKind: (k: string) => void; reports: { key: string; label: string }[]
  sel: string | null; setSel: (id: string) => void; onCite: (c: Citation) => void
  canDecide: boolean; locked: boolean; onDecide: (id: string, decision: string, note: string) => Promise<void>
}

export default function FindingsPanel({ c, report, kind, setKind, reports, sel, setSel, onCite, canDecide, locked, onDecide }: Props) {
  const [fl, setFl] = useState<Filters>(load)
  const [open, setOpen] = useState<string | null>(null)
  const [full, setFull] = useState(false)
  const [view, setView] = useState<'report' | 'list'>(() => { try { return (window.localStorage.getItem('bbp_findings_view') as any) || 'report' } catch { return 'report' } })
  useEffect(() => { try { window.localStorage.setItem('bbp_findings_view', view) } catch { /* private mode */ } }, [view])
  useEffect(() => { try { window.localStorage.setItem(KEY, JSON.stringify(fl)) } catch { /* private mode */ } }, [fl])
  useEffect(() => { if (sel) setOpen(sel) }, [sel])          // a finding picked on the drawing opens here
  const set = (p: Partial<Filters>) => setFl(x => ({ ...x, ...p }))
  const all = report?.findings ?? []

  const counts = useMemo(() => {
    const c: Record<string, number> = { pending: 0, CONFIRMED: 0, OVERRIDDEN: 0 }
    for (const s of STATUSES) c[s] = 0
    for (const f of all) { c[f.status]++; const d = decisionOf(f); if (d in c) c[d]++ }
    return c
  }, [all])
  const sources = useMemo(() => [...new Set(all.map(sourceOf))].sort(), [all])

  const shown = useMemo(() => {
    const q = fl.text.trim().toLowerCase()
    return all.filter(f => fl.statuses.includes(f.status)
      && (fl.severity === 'all' || f.severity === fl.severity)
      && (fl.decision === 'all' || decisionOf(f) === fl.decision)
      && (fl.source === 'all' || sourceOf(f) === fl.source)
      && (!fl.conditionsOnly || f.flags.includes('CONDITION_FOR_PERMIT'))
      && (!fl.unapprovedOnly || f.flags.includes('RULE_NOT_APPROVED'))
      && (!q || [f.title_he, f.explanation_he, f.rule_id, f.fix_hint_he, ...f.citations.map(c => c.title_he + ' ' + (c.section ?? ''))]
        .some(x => (x ?? '').toLowerCase().includes(q))))
      .sort((a, b) => STATUSES.indexOf(a.status) - STATUSES.indexOf(b.status)
        || Number(!!a.reviewer_decision) - Number(!!b.reviewer_decision)
        || (SEV_ORDER[a.severity] ?? 3) - (SEV_ORDER[b.severity] ?? 3) || a.title_he.localeCompare(b.title_he, 'he'))
  }, [all, fl])

  const groups = useMemo(() => {
    if (fl.group === 'none') return [{ key: 'all', label: '', items: shown }]
    const m = new Map<string, Finding[]>()
    for (const f of shown) {
      const k = fl.group === 'status' ? f.status : sourceOf(f)
      m.set(k, [...(m.get(k) ?? []), f])
    }
    return [...m.entries()].map(([k, items]) => ({ key: k, label: fl.group === 'status' ? STATUS_HE[k as Status] : k, items }))
  }, [shown, fl.group])

  const toggleStatus = (s: Status) => set({ statuses: fl.statuses.includes(s) ? fl.statuses.filter(x => x !== s) : [...fl.statuses, s] })
  const filtered = JSON.stringify({ ...fl, group: DEFAULTS.group }) !== JSON.stringify({ ...DEFAULTS, group: DEFAULTS.group })

  return (
    <div className={'fpanel' + (full ? ' full' : '')}>
      <div className="card-head">
        <select value={kind} onChange={e => setKind(e.target.value)} aria-label="סוג דוח">
          {reports.map(r => <option key={r.key} value={r.key}>{r.label}</option>)}
        </select>
        <div className="seg" role="tablist" aria-label="תצוגה">
          <button className={view === 'report' ? 'active' : ''} onClick={() => setView('report')}>דוח ליקויים</button>
          <button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>רשימה עם סינון</button>
        </div>
        <span className="spacer" />
        {counts.pending > 0 && <span className="chip warn">{counts.pending} ממתינים להחלטה</span>}
        {report && <button className="sm" onClick={() => setFull(!full)}>{full ? 'סגירת מסך מלא' : 'מסך מלא'}</button>}
      </div>
      {!report && <div className="empty">טרם הורצה בדיקה</div>}
      {report && view === 'report' && <DefectsReport c={c} report={report} onCite={onCite} onSelect={id => { setSel(id); setOpen(id); setView('list') }} />}
      {report && view === 'list' && <>
        <div className="fp-tiles" role="group" aria-label="סינון לפי תוצאה">
          {STATUSES.map(s => (
            <button key={s} className={`fp-tile st-${s}${fl.statuses.includes(s) ? ' on' : ''}`} aria-pressed={fl.statuses.includes(s)}
              onClick={() => toggleStatus(s)} title={fl.statuses.includes(s) ? 'לחיצה מסתירה' : 'לחיצה מציגה'}>
              <span className="n num">{counts[s]}</span><span>{STATUS_HE[s]}</span>
            </button>))}
          <span className="fp-sep" />
          {(['pending', 'CONFIRMED', 'OVERRIDDEN'] as const).map(d => (
            <button key={d} className={`fp-tile dec${fl.decision === d ? ' on' : ''}`} aria-pressed={fl.decision === d}
              onClick={() => set({ decision: fl.decision === d ? 'all' : d })}>
              <span className="n num">{counts[d]}</span><span>{DECISIONS[d]}</span>
            </button>))}
        </div>

        <div className="fp-filters">
          <input type="search" placeholder="חיפוש בכותרת, בהסבר, במקור או במזהה כלל" value={fl.text}
            onChange={e => set({ text: e.target.value })} aria-label="חיפוש ממצאים" />
          <select value={fl.severity} onChange={e => set({ severity: e.target.value })} aria-label="חומרה">
            <option value="all">כל החומרות</option>{Object.entries(SEV_HE).map(([k, v]) => <option key={k} value={k}>חומרה {v}</option>)}
          </select>
          <select value={fl.decision} onChange={e => set({ decision: e.target.value })} aria-label="החלטת בודק">
            {Object.entries(DECISIONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select value={fl.source} onChange={e => set({ source: e.target.value })} aria-label="מקור" className="fp-source">
            <option value="all">כל המקורות</option>{sources.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <label className="fp-check"><input type="checkbox" checked={fl.conditionsOnly} onChange={e => set({ conditionsOnly: e.target.checked })} /> תנאים להיתר בלבד</label>
          <label className="fp-check"><input type="checkbox" checked={fl.unapprovedOnly} onChange={e => set({ unapprovedOnly: e.target.checked })} /> כללים שטרם אושרו</label>
          <select value={fl.group} onChange={e => set({ group: e.target.value as Filters['group'] })} aria-label="קיבוץ">
            <option value="status">קיבוץ לפי תוצאה</option><option value="source">קיבוץ לפי מקור</option><option value="none">ללא קיבוץ</option>
          </select>
        </div>
        <div className="fp-count small muted">
          מוצגים <b className="num">{shown.length}</b> מתוך <span className="num">{all.length}</span> ממצאים
          {filtered && <button className="ghost sm" onClick={() => setFl({ ...DEFAULTS, group: fl.group })}>ניקוי סינון</button>}
          <span className="spacer" />{report.disclaimer_he}
        </div>

        <div className="findings-scroll">
          {shown.length === 0 && <div className="empty">אין ממצאים התואמים את הסינון</div>}
          {groups.map(g => (
            <section key={g.key} className="fp-group">
              {g.label && <h4 className="fp-group-head">{g.label} <span className="count num">{g.items.length}</span></h4>}
              {g.items.map(f => open === f.id
                ? <div key={f.id} className="fp-open">
                    <button className="ghost sm fp-close" onClick={() => setOpen(null)} aria-label="סגירת פירוט">▴ סגירה</button>
                    <FindingCard f={f} selected={sel === f.id} onSelect={() => setSel(f.id)} onCite={onCite}
                      canDecide={canDecide} locked={locked} onDecide={(d, n) => onDecide(f.id, d, n)} />
                  </div>
                : <Row key={f.id} f={f} selected={sel === f.id} onClick={() => { setOpen(f.id); setSel(f.id) }} />)}
            </section>))}
        </div>
      </>}
    </div>
  )
}

function Row({ f, selected, onClick }: { f: Finding; selected: boolean; onClick: () => void }) {
  const d = decisionOf(f)
  const measured = f.measured_value !== null || f.threshold !== null
  return (
    <button className={`fp-row ${f.status}${selected ? ' selected' : ''}`} onClick={onClick} aria-expanded={false}>
      <StatusChip s={f.status} />
      <span className="fp-title">{f.title_he}
        <span className="fp-sub">{sourceOf(f)}{f.citations[0]?.section ? ` · ${f.citations[0].section}` : ''}</span>
      </span>
      <span className="fp-val num">{measured ? `${fmt(f.measured_value)} / ${f.operator ? OP_HE[f.operator] : ''}${fmt(f.threshold)}${f.units ? ' ' + f.units : ''}` : ''}</span>
      <span className={'chip outline sev-' + f.severity}>{SEV_HE[f.severity] ?? f.severity}</span>
      <span className="fp-dec">
        {d === 'pending' && <span className="chip warn">ממתין</span>}
        {d === 'CONFIRMED' && <span className="chip ok">אושר</span>}
        {d === 'OVERRIDDEN' && <span className="chip bad">נדחה</span>}
        {f.flags.includes('CONDITION_FOR_PERMIT') && <span className="chip outline">תנאי</span>}
      </span>
    </button>
  )
}
