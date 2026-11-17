import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Case, api, fmtDate } from '../api'
import { useApp } from '../App'
import { StatusChip } from '../components/FindingCard'

export default function Cases() {
  const { meta, can, toast } = useApp()
  const nav = useNavigate()
  const [cases, setCases] = useState<Case[]>([])
  const [users, setUsers] = useState<Record<string, string>>({})
  const [showNew, setShowNew] = useState(false)
  const [q, setQ] = useState('')
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [rechecking, setRechecking] = useState(false)
  const [recheckRes, setRecheckRes] = useState<any>(null)
  const load = () => api.get<Case[]>('/api/cases').then(setCases).catch(e => toast(e.message, true))
  useEffect(() => {
    load()
    api.get<any[]>('/api/users').then(us => setUsers(Object.fromEntries(us.map(u => [u.id, u.display_name]))))
  }, [])
  const shown = cases.filter(c => !q || (c.case_number + c.title + (c.address ?? '')).includes(q))
  const canRun = can('case.run')
  const toggle = (id: string) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const allShown = shown.length > 0 && shown.every(c => sel.has(c.id))
  const toggleAll = () => setSel(s => { const n = new Set(s); shown.forEach(c => allShown ? n.delete(c.id) : n.add(c.id)); return n })
  const recheck = async () => {
    const ids = sel.size ? [...sel] : null
    const n = ids ? ids.length : cases.length
    if (!n) return
    if (!window.confirm(ids ? `להריץ בדיקה חוזרת על ${n} תיקים שנבחרו?` : `לא נבחרו תיקים — להריץ בדיקה חוזרת על כל ${n} התיקים?`)) return
    setRechecking(true); setRecheckRes(null)
    try {
      const r = await api.post<any>('/api/cases/recheck', { case_ids: ids })
      setRecheckRes(r); setSel(new Set())
      toast(`בדיקה חוזרת: ${r.done.length} הורצו` + (r.skipped.length ? `, ${r.skipped.length} דולגו` : '') + (r.failed.length ? `, ${r.failed.length} נכשלו` : ''), r.failed.length > 0)
      load()
    } catch (e: any) { toast(e.message, true) } finally { setRechecking(false) }
  }
  return (
    <>
      <div className="page-head">
        <div><h1>תיקי בקשות</h1><p>בקשות לתוספות בנייה בפיילוט: הרחבת דירה/אגף, מרפסת, מרפסת סוכה, חדרי גג (תכנית תוספת זכויות)</p></div>
        <span className="spacer" />
        <input placeholder="חיפוש תיק / כתובת" value={q} onChange={e => setQ(e.target.value)} aria-label="חיפוש" />
        {canRun && <button onClick={recheck} disabled={rechecking || !cases.length} title="הרצה מחדש של בדיקת הכללים — על התיקים שנבחרו, או על כל התיקים אם לא נבחר אף אחד">
          {rechecking ? 'מריץ בדיקה חוזרת…' : sel.size ? `בדיקה חוזרת (${sel.size})` : 'בדיקה חוזרת לכל התיקים'}</button>}
        {can('case.create') && <button onClick={() => nav('/cases/import')}>קליטת מסמכים</button>}
        {can('case.create') && <button className="primary" onClick={() => setShowNew(!showNew)}>תיק חדש</button>}
      </div>
      {showNew && <NewCase onDone={(id) => { setShowNew(false); nav('/cases/' + id) }} />}
      {recheckRes && (recheckRes.skipped.length > 0 || recheckRes.failed.length > 0) && (
        <div className="notice warn small" style={{ marginBottom: 14 }}>
          <b>בדיקה חוזרת:</b> {recheckRes.done.length} הורצו מתוך {recheckRes.requested}.
          {[...recheckRes.skipped.map((x: any) => ({ ...x, kind: 'דולג' })), ...recheckRes.failed.map((x: any) => ({ ...x, kind: 'נכשל' }))].map((x: any) => (
            <div key={x.case_id}><span className="ltr">{x.case_number}</span> — {x.kind}: {x.reason}</div>
          ))}
          <button className="sm" style={{ marginTop: 6 }} onClick={() => setRecheckRes(null)}>סגירה</button>
        </div>
      )}
      <div className="card">
        <div className="table-wrap">
          <table>
            <thead><tr>{canRun && <th style={{ width: 32 }}><input type="checkbox" aria-label="בחירת כל התיקים המוצגים" checked={allShown} onChange={toggleAll} /></th>}<th>מס׳ תיק</th><th>נושא</th><th>סוג בקשה</th><th>סטטוס</th><th>בודק</th><th>יעד SLA</th><th>תוצאות אחרונות</th></tr></thead>
            <tbody>
              {shown.map(c => {
                const cnt: Record<string, number> = {}
                Object.values(c.last_run?.summary?.counts ?? {}).forEach((r: any) => Object.entries(r).forEach(([k, v]: any) => { cnt[k] = (cnt[k] ?? 0) + v }))
                return (
                  <tr key={c.id} className={'clickable' + (sel.has(c.id) ? ' selected' : '')} onClick={() => nav('/cases/' + c.id)}>
                    {canRun && <td onClick={e => e.stopPropagation()}><input type="checkbox" aria-label={'בחירת תיק ' + c.case_number} checked={sel.has(c.id)} onChange={() => toggle(c.id)} /></td>}
                    <td><span className="ltr nowrap">{c.case_number}</span>{c.is_demo && <> <span className="chip demo">הדגמה</span></>}</td>
                    <td>{c.title}<div className="small muted">{c.address}</div></td>
                    <td className="small">{meta.permit_types[c.permit_type]}</td>
                    <td><span className="chip outline">{meta.case_statuses[c.status] ?? c.status}</span></td>
                    <td className="small">{c.assigned_to ? users[c.assigned_to] ?? c.assigned_to : <span className="muted">לא שובץ</span>}</td>
                    <td className="small">{fmtDate(c.sla_due)}</td>
                    <td><div className="counts">{(['FAIL', 'UNCERTAIN', 'PASS'] as const).map(s => cnt[s] ? <span key={s}><StatusChip s={s} /> <span className="num">{cnt[s]}</span></span> : null)}</div></td>
                  </tr>
                )
              })}
              {!shown.length && <tr><td colSpan={canRun ? 8 : 7} className="empty">אין תיקים</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}

function NewCase({ onDone }: { onDone: (id: string) => void }) {
  const { meta, toast } = useApp()
  const [f, setF] = useState<any>({ case_number: '', title: '', permit_type: 'addition_extension', track: 'regular_permit', stage: 'permit_request', gush: '', helka: '', address: '', zone: '', applicable_plans: '' })
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value })
  const submit = async () => {
    try {
      const body = { ...f, zone: f.zone || null, applicable_plans: f.applicable_plans.split(',').map((s: string) => s.trim()).filter(Boolean) }
      const c = await api.post<Case>('/api/cases', body)
      toast('התיק נוצר'); onDone(c.id)
    } catch (e: any) { toast(e.message, true) }
  }
  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <h2>פתיחת תיק</h2>
      <div className="form-grid">
        <label className="field">מספר תיק<input value={f.case_number} onChange={set('case_number')} dir="ltr" /></label>
        <label className="field">נושא<input value={f.title} onChange={set('title')} /></label>
        <label className="field">סוג בקשה<select value={f.permit_type} onChange={set('permit_type')}>{Object.entries(meta.permit_types).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field">מסלול<select value={f.track} onChange={set('track')}>{Object.entries(meta.tracks).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field">שלב<select value={f.stage} onChange={set('stage')}>{Object.entries(meta.stages).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field">אזור<select value={f.zone} onChange={set('zone')}><option value="">— לא ידוע —</option>{Object.entries(meta.zones).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field">גוש<input value={f.gush} onChange={set('gush')} dir="ltr" inputMode="numeric" /></label>
        <label className="field">חלקה<input value={f.helka} onChange={set('helka')} dir="ltr" inputMode="numeric" /></label>
        <label className="field">כתובת<input value={f.address} onChange={set('address')} /></label>
        <label className="field">תכניות חלות (מופרד בפסיק)<input value={f.applicable_plans} onChange={set('applicable_plans')} placeholder="בב/105, ..." /></label>
      </div>
      <div style={{ marginTop: 12 }}><button className="primary" disabled={!f.case_number || !f.title} onClick={submit}>יצירה</button></div>
    </div>
  )
}
