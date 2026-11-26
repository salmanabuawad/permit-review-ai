import { useEffect, useState } from 'react'
import { Case, api } from '../api'
import { useApp } from '../App'

const ST: Record<string, [string, string]> = { APPROVED: ['מאושר', 'ok'], DECLARED: ['מוצהר', 'warn'], OBSERVED: ['נצפה בשטח', 'outline'], UNVERIFIED: ['לא מאומת', 'bad'] }
const KIND: Record<string, string> = { permit: 'היתר', application: 'בקשה', area_table: 'טבלת שטחים בהיתר', declared: 'נתון מוצהר', decision: 'החלטת ועדה', inspection: 'פיקוח' }

/** Building360: the passports of the case's parcel and plan cell — what is known, from where, how sure, as of a date. */
export default function PropertyPanel({ c }: { c: Case }) {
  const { can, toast } = useApp()
  const [d, setD] = useState<any[] | null>(null), [asOf, setAsOf] = useState('')
  const load = () => api.get<any[]>(`/api/cases/${c.id}/properties${asOf ? '?as_of=' + asOf : ''}`).then(setD).catch(e => toast(e.message, true))
  useEffect(() => { load() }, [c.id, asOf])
  const sync = () => api.post<any>('/api/properties/sync').then(r => { toast(`עודכן: ${r.ledgers.new + r.cases.new} חדשים, ${r.ledgers.changed + r.cases.changed} שינויים`); load() }).catch(e => toast(e.message, true))
  if (!d) return <div className="empty">טוען…</div>
  return <div>
    <div className="filters-row"><label className="small">נכון לתאריך <input type="date" value={asOf} onChange={e => setAsOf(e.target.value)} /></label>
      {asOf && <button className="sm" onClick={() => setAsOf('')}>היום</button>}<span className="spacer" />
      {can('case.assign') && <button className="sm" onClick={sync}>עדכון מהמקורות</button>}</div>
    {!d.length && <div className="empty">אין עדיין דרכון לנכס בגוש {c.gush ?? '—'} — "עדכון מהמקורות" יוצר אותו מהתיקים ומצילומי המאגר</div>}
    {d.map(pp => <div key={pp.property.id} className="card" style={{ marginBottom: 10 }}>
      <div className="card-head"><b>גוש {pp.property.gush}{pp.property.helka ? ` חלקה ${pp.property.helka}` : ''}{pp.property.cell ? ` · תא שטח ${pp.property.cell}` : ''}</b>
        {pp.property.locality && <span>{pp.property.locality}</span>}{pp.property.plan && <span className="small muted ltr">{pp.property.plan}</span>}
        <span className="spacer" />{Object.entries(pp.by_status).map(([k, n]) => <span key={k} className={'chip ' + (ST[k]?.[1] ?? '')}>{ST[k]?.[0] ?? k} {n as number}</span>)}</div>
      {pp.property.note_he && <div className="small muted" style={{ marginBottom: 6 }}>{pp.property.note_he}</div>}
      <div style={{ overflowX: 'auto' }}><table className="small"><thead><tr><th>סוג</th><th>מזהה</th><th>תוכן</th><th>מעמד</th><th>בתוקף מ־</th><th>מקור</th></tr></thead><tbody>
        {pp.facts.slice(0, 200).map((f: any) => <tr key={f.id}><td>{KIND[f.kind] ?? f.kind}</td><td className="ltr">{f.key}</td>
          <td>{f.value.essence ?? f.value.title ?? (f.value.field ? `${f.value.field}: ${f.value.value}` : '') ?? ''}{f.value.primary_m2 && <span className="muted"> · עיקרי {f.value.primary_m2} מ"ר</span>}
            {f.value.table?.primary_total && <span className="muted"> · עיקרי {f.value.table.primary_total} · סה"כ {f.value.table.building_total}</span>}
            {f.value.unverified_reason && <div className="muted">{f.value.unverified_reason}</div>}</td>
          <td><span className={'chip ' + (ST[f.status]?.[1] ?? '')}>{ST[f.status]?.[0] ?? f.status}</span></td><td>{f.valid_from ?? '—'}</td>
          <td>{f.source_url ? <a href={f.source_url} target="_blank" rel="noreferrer">{f.source_type}</a> : f.source_type}</td></tr>)}
      </tbody></table></div>
    </div>)}
  </div>
}
