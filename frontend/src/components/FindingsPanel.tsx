import { useState } from 'react'
import { Case, Citation, Report } from '../api'
import RequestResults from './RequestResults'

// The findings panel shows the defects report only: confirmed defects and documented discrepancies.
// The internal record (passed checks, open checks, all rules) is not shown in the UI.

interface Props {
  c: Case; report: Report | null
  sel: string | null; setSel: (id: string) => void; onCite: (c: Citation) => void
  canDecide: boolean; locked: boolean; onDecide: (id: string, decision: string, note: string) => Promise<void>
}

export default function FindingsPanel({ c, report, setSel, onCite }: Props) {
  const [full, setFull] = useState(false)
  return (
    <div className={'fpanel' + (full ? ' full' : '')}>
      <div className="card-head">
        <span className="spacer" />
        {report && <button className="sm" onClick={() => setFull(!full)}>{full ? 'סגירת מסך מלא' : 'מסך מלא'}</button>}
      </div>
      {!report && <div className="empty">טרם הורצה בדיקה</div>}
      {report && <RequestResults c={c} report={report} onCite={onCite} onSelect={id => setSel(id)} />}
    </div>
  )
}
