import { useEffect, useState } from 'react'
import { Case, api } from '../api'
import { useApp } from '../App'

type Obs = { item: string; unit: string; approved: string; observed: string; tolerance: string }
const empty = (): Obs => ({ item: '', unit: 'מ׳', approved: '', observed: '', tolerance: '0' })
const num = (v: string) => v.trim() === '' ? null : Number(v)

/** Construction360: inspections of the case at milestones; approved vs observed with tolerance; photos. */
export default function InspectionPanel({ c }: { c: Case }) {
  const { can, toast } = useApp()
  const [d, setD] = useState<any>(null), [ms, setMs] = useState('start'), [when, setWhen] = useState('')
  const [open, setOpen] = useState<number | null>(null), [obs, setObs] = useState<Obs[]>([empty()]), [notes, setNotes] = useState('')
  const load = () => api.get<any>(`/api/cases/${c.id}/inspections`).then(setD).catch(e => toast(e.message, true))
  useEffect(() => { load() }, [c.id])
  const schedule = () => api.post(`/api/cases/${c.id}/inspections`, { milestone: ms, scheduled_for: when || null }).then(load).catch(e => toast(e.message, true))
  const record = async (id: number) => {
    try {
      await api.post(`/api/inspections/${id}/result`, { notes, observations: obs.filter(o => o.item.trim()).map(o => ({ item: o.item, unit: o.unit || null,
        approved: num(o.approved), observed: num(o.observed), tolerance: num(o.tolerance) })) })
      setOpen(null); setObs([empty()]); setNotes(''); load()
    } catch (e: any) { toast(e.message, true) }
  }
  const photo = (id: number, file: File) => {
    const send = (lat?: number, lon?: number) => {
      const fd = new FormData(); fd.append('file', file)
      if (lat != null) { fd.append('lat', String(lat)); fd.append('lon', String(lon)) }
      api.upload(`/api/inspections/${id}/photos`, fd).then(load).catch(e => toast(e.message, true))
    }
    if (navigator.geolocation) navigator.geolocation.getCurrentPosition(p => send(p.coords.latitude, p.coords.longitude), () => send(), { timeout: 5000 })
    else send()
  }
  if (!d) return <div className="empty">טוען…</div>
  const set = (k: number, f: keyof Obs, v: string) => setObs(o => o.map((x, i) => i === k ? { ...x, [f]: v } : x))
  return <div>
    {can('inspection.manage') && <div className="filters-row"><select value={ms} onChange={e => setMs(e.target.value)}>{Object.entries(d.milestones).map(([k, v]) => <option key={k} value={k}>{v as string}</option>)}</select>
      <input type="date" value={when} onChange={e => setWhen(e.target.value)} /><button className="primary" onClick={schedule}>תזמון פיקוח</button></div>}
    {d.inspections.map((i: any) => <div key={i.id} className="card" style={{ marginBottom: 8 }}>
      <div className="card-head"><b>{i.milestone_he}</b><span className="small muted">{i.scheduled_for ?? ''}</span>
        <span className={'chip ' + (i.result === 'pass' ? 'ok' : i.result === 'deviations' ? 'bad' : 'outline')}>{i.status === 'done' ? (i.result === 'pass' ? 'תקין' : 'נמצאו חריגות') : 'מתוכנן'}</span>
        <span className="spacer" />{can('inspection.manage') && i.status === 'scheduled' && <button className="sm" onClick={() => setOpen(open === i.id ? null : i.id)}>רישום תוצאות</button>}
        {can('inspection.manage') && <label className="sm btn">תמונה<input type="file" accept="image/jpeg,image/png" hidden onChange={e => e.target.files?.[0] && photo(i.id, e.target.files[0])} /></label>}</div>
      {i.observations.length > 0 && <table className="small"><thead><tr><th>פריט</th><th>מאושר</th><th>נצפה</th><th>הפרש</th></tr></thead><tbody>
        {i.observations.map((o: any, k: number) => <tr key={k}><td>{o.item}</td><td className="num">{o.approved ?? '—'} {o.unit ?? ''}</td><td className="num">{o.observed ?? '—'} {o.unit ?? ''}</td>
          <td className={o.deviation?.beyond_tolerance ? 'num s-bad' : 'num'}>{o.deviation ? `${o.deviation.difference > 0 ? '+' : ''}${o.deviation.difference}` : '—'}{o.deviation?.beyond_tolerance && ' (חריגה)'}</td></tr>)}</tbody></table>}
      {i.notes && <div className="small muted">{i.notes}</div>}
      {i.photos.length > 0 && <div className="small muted">{i.photos.length} תמונות{i.photos.some((x: any) => x.lat != null) ? ' (עם מיקום)' : ''}</div>}
      {open === i.id && <div style={{ marginTop: 8 }}>
        {obs.map((o, k) => <div key={k} className="user-form"><input placeholder="פריט (למשל: גובה בניין)" value={o.item} onChange={e => set(k, 'item', e.target.value)} />
          <input placeholder="יחידה" value={o.unit} onChange={e => set(k, 'unit', e.target.value)} style={{ width: 60 }} />
          <input placeholder="מאושר" inputMode="decimal" value={o.approved} onChange={e => set(k, 'approved', e.target.value)} style={{ width: 80 }} />
          <input placeholder="נצפה" inputMode="decimal" value={o.observed} onChange={e => set(k, 'observed', e.target.value)} style={{ width: 80 }} />
          <input placeholder="סטייה מותרת" inputMode="decimal" value={o.tolerance} onChange={e => set(k, 'tolerance', e.target.value)} style={{ width: 90 }} /></div>)}
        <div className="user-actions"><button className="sm" onClick={() => setObs([...obs, empty()])}>פריט נוסף</button>
          <input placeholder="הערות" value={notes} onChange={e => setNotes(e.target.value)} style={{ flex: 1 }} /><button className="sm primary" onClick={() => record(i.id)}>שמירה</button></div>
      </div>}
    </div>)}
    {!d.inspections.length && <div className="empty">אין פיקוחים</div>}
  </div>
}
