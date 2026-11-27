import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../App'

/** Architect360: the architect's private designs, checked before submission by the same engine. */
export default function Architect() {
  const { meta, toast } = useApp()
  const [rows, setRows] = useState<any[] | null>(null), [busy, setBusy] = useState<string | null>(null), [form, setForm] = useState(false)
  const [f, setF] = useState({ title: '', permit_type: 'addition_extension', gush: '', helka: '', address: '', plans: '' })
  const [a, setA] = useState(''), [b, setB] = useState(''), [cmp, setCmp] = useState<any>(null)
  const load = () => api.get<any[]>('/api/designs').then(setRows).catch(e => toast(e.message, true))
  useEffect(() => { load() }, [])
  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    try { await api.post('/api/designs', { title: f.title, permit_type: f.permit_type, gush: f.gush || null, helka: f.helka || null, address: f.address || null,
      applicable_plans: f.plans.split(/[,\n]/).map(x => x.trim()).filter(Boolean) }); setForm(false); load() } catch (er: any) { toast(er.message, true) }
  }
  const check = async (id: string) => {
    setBusy(id)
    try { await api.post(`/api/designs/${id}/check`); await load() } catch (er: any) { toast(er.message, true) } finally { setBusy(null) }
  }
  const compare = () => api.get<any>(`/api/designs/compare?a=${a}&b=${b}`).then(setCmp).catch(er => toast(er.message, true))
  if (!rows) return <div className="empty">טוען…</div>
  return <>
    <div className="page-head"><div><h1>בדיקה לפני הגשה</h1><p>התכנונים שלך — פרטיים, אינם גלויים לוועדה. אותן בדיקות שהוועדה מריצה, לפני ההגשה. הציון הוא הערכה, לא קביעת עמידה בדין.</p></div>
      <span className="spacer" /><Link className="button primary" to="/apply">בקשה חדשה (אשף הגשה)</Link><Link className="button" to="/projects/new">פרויקט חדש (זיהוי ועדה)</Link><button onClick={() => setForm(!form)}>תכנון ידני</button></div>
    {form && <form className="card user-form" onSubmit={create}>
      <label>שם התכנון<input required value={f.title} onChange={e => setF({ ...f, title: e.target.value })} /></label>
      <label>סוג<select value={f.permit_type} onChange={e => setF({ ...f, permit_type: e.target.value })}>{Object.entries(meta?.permit_types ?? {}).map(([k, v]) => <option key={k} value={k}>{v as string}</option>)}</select></label>
      <label>גוש<input dir="ltr" value={f.gush} onChange={e => setF({ ...f, gush: e.target.value })} /></label>
      <label>חלקה<input dir="ltr" value={f.helka} onChange={e => setF({ ...f, helka: e.target.value })} /></label>
      <label>כתובת<input value={f.address} onChange={e => setF({ ...f, address: e.target.value })} /></label>
      <label>תכניות חלות<input dir="ltr" value={f.plans} onChange={e => setF({ ...f, plans: e.target.value })} placeholder="633-0723718, ..." /></label>
      <button className="primary">יצירה</button></form>}
    <div className="card" style={{ padding: 0, overflowX: 'auto' }}><table><thead><tr><th>תכנון</th><th>מוכנות</th><th>חוסמים</th><th></th></tr></thead><tbody>
      {rows.map(r => <tr key={r.id}><td><b>{r.title}</b><div className="small muted ltr">{r.case_number}</div></td>
        <td>{r.readiness ? <><b className="num">{r.readiness.score}%</b> <span className="small muted">({r.readiness.passed}/{r.readiness.applicable} בדיקות עומדות · {r.readiness.open} פתוחות)</span>
          {r.readiness.ready ? <div className="chip ok">ללא חוסמים</div> : <div className="chip bad">יש לתקן לפני הגשה</div>}</> : <span className="muted">טרם נבדק</span>}</td>
        <td className="small">{(r.readiness?.blockers ?? []).slice(0, 4).map((x: any) => <div key={x.rule_id}>• {x.description}{x.measured != null && ` (${x.measured} / ${x.permitted} ${x.units ?? ''})`}{x.fix && <span className="muted"> — {x.fix}</span>}</div>)}
          {(r.readiness?.blockers ?? []).length > 4 && <div className="muted">ועוד {r.readiness.blockers.length - 4}</div>}</td>
        <td className="user-actions"><Link to={`/cases/${r.id}`}>קבצים ופרטים</Link><button className="sm primary" disabled={busy === r.id} onClick={() => check(r.id)}>{busy === r.id ? 'בודק…' : 'בדיקה'}</button></td></tr>)}
      {!rows.length && <tr><td colSpan={4} className="empty">אין תכנונים. צרו תכנון והעלו את קבצי התכנית (DWG / DXF / PDF).</td></tr>}
    </tbody></table></div>
    {rows.length > 1 && <div className="card" style={{ marginTop: 14 }}><h3>השוואת חלופות</h3>
      <div className="filters-row"><select value={a} onChange={e => setA(e.target.value)}><option value="">חלופה א</option>{rows.map(r => <option key={r.id} value={r.id}>{r.title}</option>)}</select>
        <select value={b} onChange={e => setB(e.target.value)}><option value="">חלופה ב</option>{rows.map(r => <option key={r.id} value={r.id}>{r.title}</option>)}</select>
        <button disabled={!a || !b || a === b} onClick={compare}>השוואה</button></div>
      {cmp && <div className="small">
        <div>{cmp.a.title}: {cmp.a.readiness?.score}% · {cmp.b.title}: {cmp.b.readiness?.score}%</div>
        {[['better', 'טוב יותר בחלופה ב', 'ok'], ['worse', 'גרוע יותר בחלופה ב', 'bad'], ['same_open', 'פתוח בשתיהן', 'warn']].map(([k, l, t]) => cmp[k].length > 0 &&
          <div key={k} style={{ marginTop: 6 }}><span className={'chip ' + t}>{l} ({cmp[k].length})</span>{cmp[k].map((x: any) => <div key={x.rule_id}>{x.title_he} — {x.a} / {x.b}{x.a_value != null && ` (${x.a_value} → ${x.b_value})`}</div>)}</div>)}
      </div>}</div>}
  </>
}
