import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api'
import { useApp } from '../App'

const STATUS_CLASS: Record<string, string> = { RESOLVED: 'ok', VERIFIED: 'ok', AMBIGUOUS: 'warn', UNLINKED: 'warn', UNRESOLVED: 'bad', MISMATCH: 'bad' }

/** Permit360 Pro: start a project from the committee (path A) or from block / parcel (path B). */
export default function ProjectNew() {
  const { meta, toast } = useApp()
  const nav = useNavigate()
  const [path, setPath] = useState<'A' | 'B'>('B')
  const [q, setQ] = useState(''), [dir, setDir] = useState<any[]>([]), [committee, setCommittee] = useState<any>(null)
  const [f, setF] = useState({ gush: '', helka: '', lot: '', title: '', permit_type: 'new_building' })
  const [res, setRes] = useState<any>(null), [busy, setBusy] = useState(false), [pick, setPick] = useState<string>('')
  useEffect(() => {
    const t = setTimeout(() => api.get<any[]>(`/api/committees/directory?q=${encodeURIComponent(q)}`).then(setDir).catch(e => toast(e.message, true)), 250)
    return () => clearTimeout(t)
  }, [q])
  const reset = () => { setRes(null); setPick('') }
  const check = async () => {
    setBusy(true); reset()
    try {
      setRes(path === 'A' ? await api.post('/api/projects/verify', { gush: f.gush, helka: f.helka, lot: f.lot || null, committee_id: committee?.id })
        : await api.post('/api/projects/discover', { gush: f.gush, helka: f.helka, lot: f.lot || null }))
    } catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }
  const create = async (manual = false) => {
    setBusy(true)
    try {
      const committee_id = path === 'A' ? committee?.id : (pick || undefined)
      const c = await api.post<any>('/api/projects', { path, gush: f.gush, helka: f.helka, lot: f.lot || null, committee_id, title: f.title,
        permit_type: f.permit_type, manual, confirm: true })
      toast('הפרויקט נפתח'); nav(`/cases/${c.id}`)
    } catch (e: any) {
      if (e instanceof ApiError && e.detail?.result) setRes(e.detail.result)
      toast(e.message, true)
    } finally { setBusy(false) }
  }
  const st = res?.status
  const ambiguous = st === 'AMBIGUOUS', linkedCands = (res?.candidates ?? []).filter((c: any) => c.committee_id)
  const canCreate = (path === 'A' && (st === 'VERIFIED' || (st === 'AMBIGUOUS' && res?.selected_share > 0))) || (path === 'B' && (st === 'RESOLVED' || (ambiguous && pick)))
  const canManual = st === 'UNRESOLVED' || st === 'UNLINKED'
  return <>
    <div className="page-head"><div><h1>פרויקט חדש</h1><p>זיהוי הנכס והוועדה מגבולות רשמיים: קדסטר (מפ"י) ומרחבי התכנון (מינהל התכנון). הוועדה לא נקבעת לפי שם יישוב או מספר תכנית.</p></div></div>
    <div className="card">
      <div className="tabs" role="tablist" style={{ marginBottom: 10 }}>
        <button className={path === 'B' ? 'active' : ''} onClick={() => { setPath('B'); reset() }}>לפי גוש וחלקה — זיהוי ועדה אוטומטי</button>
        <button className={path === 'A' ? 'active' : ''} onClick={() => { setPath('A'); reset() }}>בחירת ועדה מהמאגר הארצי</button>
      </div>
      {path === 'A' && <div style={{ marginBottom: 10 }}>
        <label className="small">חיפוש ועדה (שם, יישוב או קוד מרחב תכנון)<input value={q} onChange={e => setQ(e.target.value)} placeholder="חוף אשקלון / זיקים / 633" /></label>
        {committee ? <div className="small" style={{ marginTop: 6 }}><span className="chip ok">{committee.name_he}</span> {committee.district} · קוד {committee.codes?.join(', ') || '—'} <button className="sm" onClick={() => { setCommittee(null); reset() }}>החלפה</button></div>
          : <div className="committee-pick" style={{ maxHeight: 220, overflowY: 'auto', marginTop: 6 }}>{dir.map(c =>
            <div key={c.id} className="row-pick" style={{ padding: '4px 0', cursor: 'pointer', borderBottom: '1px solid var(--line, #eee)' }} onClick={() => { setCommittee(c); reset() }}>
              <b>{c.name_he}</b> <span className="small muted">{c.district} · {c.codes?.length ? `קוד ${c.codes.join(', ')}` : 'ללא קוד'} · {c.settlements.slice(0, 5).join(', ')}{c.settlements_total > 5 ? '…' : ''}</span></div>)}
            {!dir.length && <div className="muted small">לא נמצאו ועדות</div>}</div>}
      </div>}
      <div className="user-form" style={{ padding: 0 }}>
        <label>גוש<input dir="ltr" inputMode="numeric" value={f.gush} onChange={e => { setF({ ...f, gush: e.target.value.trim() }); reset() }} /></label>
        <label>חלקה<input dir="ltr" inputMode="numeric" value={f.helka} onChange={e => { setF({ ...f, helka: e.target.value.trim() }); reset() }} /></label>
        <label>מגרש (רשות)<input dir="ltr" value={f.lot} onChange={e => setF({ ...f, lot: e.target.value.trim() })} /></label>
        <button className="primary" disabled={busy || !f.gush || !f.helka || (path === 'A' && !committee)} onClick={check}>{busy ? 'בודק…' : path === 'A' ? 'אימות החלקה מול הוועדה' : 'איתור הוועדה'}</button>
      </div>
    </div>
    {res && <div className="card" style={{ marginTop: 12 }}>
      <div className="card-head"><span className={'chip ' + (STATUS_CLASS[st] ?? 'warn')}>{res.status_he}</span>{res.cached && <span className="small muted">מהמטמון</span>}
        <span className="spacer" /><span className="small muted ltr">{res.datasets}</span></div>
      {res.parcel && <p className="small">חלקה {res.gush}/{res.helka} · {res.parcel.status} · שטח {Math.round(res.parcel.area_m2).toLocaleString('he-IL')} מ"ר · מקור: {res.parcel.source}</p>}
      {res.candidates?.length > 0 && <table className="small"><thead><tr>{ambiguous && path === 'B' && <th></th>}<th>מרחב תכנון</th><th>קוד</th><th>סוג</th><th>ועדה</th><th>חלק מהחלקה</th></tr></thead><tbody>
        {res.candidates.map((c: any) => <tr key={c.area_id}>
          {ambiguous && path === 'B' && <td>{c.committee_id && <input type="radio" name="pick" checked={pick === c.committee_id} onChange={() => setPick(c.committee_id)} />}</td>}
          <td>{c.name_he}</td><td className="ltr">{c.code}</td><td>{c.area_type_he}</td><td>{c.committee_name ?? <span className="muted">לא מקושרת</span>}</td><td className="num">{(c.share * 100).toFixed(1)}%</td></tr>)}
      </tbody></table>}
      {(res.municipalities?.length > 0 || res.localities?.length > 0) && <p className="small">רשות: {(res.municipalities ?? []).map((m: any) => m.name_he).join(', ') || '—'} · יישוב: {(res.localities ?? []).map((l: any) => l.name_he).join(', ') || '—'}</p>}
      {ambiguous && <div className="notice warn small">החלקה חוצה יותר ממרחב תכנון אחד. המערכת אינה מנחשת — {path === 'B' ? 'בחר/י את הוועדה האחראית מבין המועמדות; הפרויקט יסומן "לא אומת".' : 'הוועדה שבחרת היא אחת מהן; הפרויקט יסומן "לא אומת".'}</div>}
      {st === 'MISMATCH' && <div className="notice bad small">החלקה אינה במרחב התכנון של {res.selected_committee_name}. {linkedCands.length > 0 && <>לפי הגבולות: <b>{linkedCands.map((c: any) => c.committee_name).join(', ')}</b>.</>}</div>}
      {canManual && <div className="notice warn small">אין נתון גבולות רשמי שמכריע. ניתן לפתוח פרויקט עם בחירה ידנית של הוועדה — אימות התחום יסומן "לא הוכרע".</div>}
      {(canCreate || (canManual && (path === 'A' ? committee : pick || linkedCands.length === 0))) && <div className="user-form" style={{ padding: 0, marginTop: 8 }}>
        <label>שם הפרויקט<input value={f.title} onChange={e => setF({ ...f, title: e.target.value })} placeholder={`גוש ${f.gush} חלקה ${f.helka}`} /></label>
        <label>סוג בקשה<select value={f.permit_type} onChange={e => setF({ ...f, permit_type: e.target.value })}>{Object.entries(meta?.permit_types ?? {}).map(([k, v]) => <option key={k} value={k}>{v as string}</option>)}</select></label>
        {canManual && path === 'B' && <label>ועדה (בחירה ידנית)<input value={q} onChange={e => setQ(e.target.value)} placeholder="חיפוש ועדה" />
          <select value={pick} onChange={e => setPick(e.target.value)}><option value="">בחר/י…</option>{dir.map(c => <option key={c.id} value={c.id}>{c.name_he}</option>)}</select></label>}
        {canCreate ? <button className="primary" disabled={busy} onClick={() => create(false)}>אישור ופתיחת הפרויקט</button>
          : <button disabled={busy || (path === 'B' && !pick)} onClick={() => create(true)}>פתיחה עם בחירה ידנית (לא מאומת)</button>}
      </div>}
    </div>}
  </>
}
