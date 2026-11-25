import { useState } from 'react'
import { Citation, Finding, FLAG_HE, OP_HE, SEV_HE, STATUS_HE, VERIFICATION_HE, fmt } from '../api'

interface Props {
  f: Finding; selected: boolean; onSelect: () => void; onCite: (c: Citation) => void
  canDecide: boolean; locked: boolean; onDecide: (decision: string, note: string) => Promise<void>
}

export function StatusChip({ s }: { s: Finding['status'] }) {
  return <span className={'chip st-' + s}>{STATUS_HE[s]}</span>
}

export default function FindingCard({ f, selected, onSelect, onCite, canDecide, locked, onDecide }: Props) {
  const [note, setNote] = useState('')
  const [open, setOpen] = useState(false)
  const measurable = f.measured_value !== null || f.threshold !== null
  return (
    <article className={`finding ${f.status}${selected ? ' selected' : ''}`} onClick={onSelect}>
      <div className="row1">
        <StatusChip s={f.status} />
        <div className="title">{f.title_he}</div>
        <span className="chip outline" title="חומרה">{SEV_HE[f.severity] ?? f.severity}</span>
      </div>
      {f.computed_result !== f.status && (
        <div className="computed-note">תוצאה מחושבת: {STATUS_HE[f.computed_result]} — לא הוחלה אוטומטית (ראו סימונים)</div>
      )}
      {measurable && (
        <div className="meta">
          <span>נמדד/נתון: <b className="num">{fmt(f.measured_value)}</b>{f.measured_uncertainty ? <span className="num"> ±{fmt(f.measured_uncertainty)}</span> : null} {f.units}</span>
          <span>סף: <b className="num">{f.operator ? OP_HE[f.operator] : ''} {fmt(f.threshold)}</b> {f.units}</span>
          <span>ודאות: <span className="num">{Math.round(f.confidence * 100)}%</span></span>
        </div>
      )}
      <div className="expl">{f.explanation_he}</div>
      {f.fix_hint_he && (f.status === 'FAIL' || f.status === 'UNCERTAIN') && <div className="fix">הנחיית תיקון: {f.fix_hint_he}</div>}
      {f.flags.length > 0 && (
        <div className="flags">{f.flags.map(x => <span key={x} className={'chip ' + (x === 'DEMO_RULE' ? 'demo' : 'warn')}>{FLAG_HE[x] ?? x}</span>)}</div>
      )}
      <div className="cites">
        {f.citations.map((c, i) => (
          <button key={i} className="cite" onClick={e => { e.stopPropagation(); onCite(c) }}
            title={VERIFICATION_HE[c.verification] ?? c.verification}>
            מקור: {c.title_he.length > 46 ? c.title_he.slice(0, 46) + '…' : c.title_he}
            {c.section ? ` · ${c.section}` : ''}{c.page ? ` · עמ׳ ${c.page}` : ''}
          </button>
        ))}
      </div>
      <div className="small muted" style={{ marginTop: 6 }}>
        <span className="mono">{f.rule_id} v{f.rule_version}</span>
        {f.evidence?.some((ev: any) => ev.type !== 'document') && <> · <button className="ghost sm" onClick={e => { e.stopPropagation(); setOpen(!open) }}>{open ? 'הסתר ראיות' : 'ראיות מדידה'}</button></>}
      </div>
      {f.evidence?.filter((ev: any) => ev.type === 'document').map((ev: any, i: number) => (
        <div key={'d' + i} className="small evidence-doc">
          <b>ראיה:</b> {ev.file}{ev.page ? `, עמ׳ ${ev.page}` : ''} — <span className="quote">״{ev.quote}״</span>
        </div>
      ))}
      {open && f.evidence.filter((ev: any) => ev.type !== 'document').map((ev, i) => (
        <div key={i} className="small" style={{ background: 'var(--surface-2)', padding: 6, borderRadius: 6, marginTop: 4 }}>
          שיטה: <span className="mono">{ev.method}</span><br />
          ישויות מקור: <span className="mono">{(ev.source_entities || []).join(', ') || '—'}</span>
        </div>
      ))}
      {(f.status === 'FAIL' || f.status === 'UNCERTAIN') && (
        <div className="decision" onClick={e => e.stopPropagation()}>
          {f.reviewer_decision ? (
            <span className={'chip ' + (f.reviewer_decision === 'CONFIRMED' ? 'ok' : 'warn')}>
              {f.reviewer_decision === 'CONFIRMED' ? 'אושר ע"י בודק' : 'נדחה/שונה ע"י בודק'}{f.reviewer_note ? ` — ${f.reviewer_note}` : ''}
            </span>
          ) : canDecide && !locked ? (
            <>
              <input placeholder="נימוק הבודק (חובה לדחייה)" value={note} onChange={e => setNote(e.target.value)} style={{ flex: 1, minWidth: 160 }} />
              <button className="sm" onClick={() => onDecide('CONFIRMED', note || 'אושר')}>אישור ממצא</button>
              <button className="sm danger" disabled={note.trim().length < 5} onClick={() => onDecide('OVERRIDDEN', note)}>דחיית ממצא</button>
            </>
          ) : <span className="small muted">ממתין להחלטת בודק</span>}
        </div>
      )}
    </article>
  )
}
