import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, api } from '../api'
import { useApp } from '../App'

const STEPS = ['הנכס', 'הוועדה', 'הבקשה', 'מידע תכנוני', 'מסמכים', 'הגשה']
const DOCS = ['application_form', 'survey_map', 'architectural_plan', 'sections_elevations', 'area_table', 'ownership_docs',
  'consents', 'permit_info', 'existing_building_photos', 'professional_license', 'other']

/** Request wizard: property → the committee found from official boundaries → request → planning information →
 *  documents → submission with a confirmation number. Each step is saved, so the wizard can be resumed. */
export default function ApplyWizard() {
  const { meta, toast } = useApp()
  const nav = useNavigate()
  const { id } = useParams()
  const [step, setStep] = useState(0)
  const [busy, setBusy] = useState(false)
  const [f, setF] = useState({ gush: '', helka: '', lot: '', title: '' })
  const [found, setFound] = useState<any>(null), [pick, setPick] = useState(''), [q, setQ] = useState(''), [dir, setDir] = useState<any[]>([])
  const [v, setV] = useState<any>(null)
  const [req, setReq] = useState({ permit_type: 'new_building', purpose: '', main_use: '' })
  const [docType, setDocType] = useState('application_form'), [file, setFile] = useState<File | null>(null)
  const [declared, setDeclared] = useState(false)

  const load = async (pid: string, jump = false) => {
    const x = await api.get<any>(`/api/projects/${pid}`)
    setV(x)
    const d = x.case?.declared ?? {}
    setReq(r => ({ permit_type: x.case.permit_type || r.permit_type, purpose: r.purpose || d.purpose || '', main_use: r.main_use || d.main_use || '' }))
    if (jump) {
      const done = (k: string) => x.checklist?.find((c: any) => c.key === k)?.done
      setStep(x.submission ? 6 : !done('purpose') ? 2 : !done('documents') ? 4 : 5)
    }
    return x
  }
  useEffect(() => { if (id) load(id, true).catch(e => toast(e.message, true)) }, [id])
  useEffect(() => {                         // the planning package fills in while the crawler works: refresh
    if (!id || step !== 3 || !v?.workflow?.stages?.some((s: any) => s.status === 'pending')) return
    const t = setTimeout(() => load(id), 8000)
    return () => clearTimeout(t)
  }, [v, step, id])
  useEffect(() => {
    if (step !== 1 || !found || found.status === 'RESOLVED' || found.status === 'AMBIGUOUS') return
    const t = setTimeout(() => api.get<any[]>(`/api/committees/directory?q=${encodeURIComponent(q)}`).then(setDir).catch(() => setDir([])), 250)
    return () => clearTimeout(t)
  }, [q, step, found])

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    try { await fn() } catch (e: any) { toast(e instanceof ApiError || e instanceof Error ? e.message : 'שגיאה', true) } finally { setBusy(false) }
  }
  const discover = () => run(async () => {
    setPick('')
    setFound(await api.post('/api/projects/discover', { gush: f.gush, helka: f.helka, lot: f.lot || null }))
    setStep(1)
  })
  const st = found?.status
  const cands = (found?.candidates ?? []).filter((c: any) => c.committee_id)
  const manual = st && st !== 'RESOLVED' && st !== 'AMBIGUOUS'
  const confirmCommittee = () => run(async () => {
    try {
      const c = await api.post<any>('/api/projects', { path: 'B', gush: f.gush, helka: f.helka, lot: f.lot || null, title: f.title,
        committee_id: st === 'RESOLVED' ? undefined : pick, permit_type: req.permit_type, manual: !!manual, confirm: true })
      nav(`/apply/${c.id}`, { replace: true })
      await load(c.id)
      setStep(2)
    } catch (e: any) {
      if (e instanceof ApiError && e.detail?.result) setFound(e.detail.result)
      throw e
    }
  })
  const saveRequest = () => run(async () => {
    await api.put(`/api/projects/${id}/purpose`, { permit_type: req.permit_type, purpose: req.purpose, main_use: req.main_use || null })
    await load(id!)
    setStep(3)
  })
  const upload = () => run(async () => {
    const fd = new FormData()
    fd.append('file', file!); fd.append('doc_type', docType)
    await api.upload(`/api/cases/${id}/files`, fd)
    setFile(null)
    const el = document.getElementById('wiz-file') as HTMLInputElement | null
    if (el) el.value = ''
    await load(id!)
    toast('המסמך נקלט')
  })
  const submit = () => run(async () => {
    await api.post(`/api/projects/${id}/submit`, { declaration: declared })
    await load(id!)
    setStep(6)
  })

  const pkg = v?.package, files = (v?.case?.files ?? []).filter((x: any) => x.lifecycle === 'ACTIVE')
  const committeeName = v?.jurisdiction?.committee_name
  const sub = v?.submission
  const canGo = (i: number) => i === 0 ? !id : i === 1 ? !!found && !id : !!id && !sub && (i <= 3 || v?.checklist?.find((c: any) => c.key === 'purpose')?.done)

  return <div className="wizard">
    <div className="page-head"><div><h1>בקשה להיתר — אשף הגשה</h1>
      <p>מזינים גוש וחלקה, המערכת מזהה את הוועדה המוסמכת מתוך הגבולות הרשמיים, ומלווה עד ההגשה ומספר האישור.</p></div></div>

    {step < 6 && <ol className="wiz-steps" aria-label="שלבי האשף">
      {STEPS.map((s, i) => <li key={s} className={i === step ? 'on' : i < step ? 'done' : ''}>
        <button type="button" disabled={busy || i === step || !canGo(i)} onClick={() => setStep(i)}><span className="n">{i + 1}</span>{s}</button></li>)}
    </ol>}

    {step === 0 && <section className="card wiz-card">
      <h2>איפה הנכס?</h2>
      <p className="small muted">לפי נסח הטאבו או תשריט המגרש. הוועדה לא נקבעת לפי שם יישוב — רק לפי גבולות מרחבי התכנון הרשמיים.</p>
      <div className="user-form" style={{ padding: 0 }}>
        <label>גוש<input dir="ltr" inputMode="numeric" value={f.gush} onChange={e => setF({ ...f, gush: e.target.value.trim() })} autoFocus /></label>
        <label>חלקה<input dir="ltr" inputMode="numeric" value={f.helka} onChange={e => setF({ ...f, helka: e.target.value.trim() })} /></label>
        <label>מגרש (רשות)<input dir="ltr" value={f.lot} onChange={e => setF({ ...f, lot: e.target.value.trim() })} /></label>
      </div>
      <div className="wiz-nav"><button className="primary" disabled={busy || !f.gush || !f.helka} onClick={discover}>{busy ? 'מאתר…' : 'איתור הוועדה ←'}</button></div>
    </section>}

    {step === 1 && found && <section className="card wiz-card">
      <h2>הוועדה המוסמכת</h2>
      {found.parcel && <p className="small">גוש {found.gush} חלקה {found.helka} · שטח {Math.round(found.parcel.area_m2).toLocaleString('he-IL')} מ"ר
        {(found.localities ?? []).length > 0 && <> · {found.localities.map((l: any) => l.name_he).join(', ')}</>}</p>}
      {st === 'RESOLVED' && <div className="wiz-committee"><span className="chip ok">זוהתה מהגבולות הרשמיים</span>
        <b>{found.candidates?.[0]?.committee_name ?? found.committee_name}</b>
        <span className="small muted">מרחב תכנון {found.candidates?.[0]?.name_he} · קוד <span className="ltr">{found.candidates?.[0]?.code}</span></span></div>}
      {st === 'AMBIGUOUS' && <>
        <div className="notice warn small">החלקה חוצה יותר ממרחב תכנון אחד. המערכת אינה מנחשת — בחרו את הוועדה האחראית (הבקשה תסומן "לא אומת").</div>
        {cands.map((c: any) => <label key={c.area_id} className="wiz-radio"><input type="radio" name="pick" checked={pick === c.committee_id} onChange={() => setPick(c.committee_id)} />
          <b>{c.committee_name}</b> <span className="small muted">{(c.share * 100).toFixed(1)}% מהחלקה</span></label>)}
      </>}
      {manual && <>
        <div className="notice warn small">{found.status_he || 'לא ניתן לזהות את הוועדה מנתונים רשמיים'}. אפשר לבחור את הוועדה ידנית — הבקשה תסומן "לא הוכרע".</div>
        <label className="f small">חיפוש ועדה<input value={q} onChange={e => setQ(e.target.value)} placeholder="שם הוועדה או היישוב" /></label>
        <select value={pick} onChange={e => setPick(e.target.value)} style={{ width: '100%' }}><option value="">בחירה…</option>
          {dir.map(c => <option key={c.id} value={c.id}>{c.name_he} — {c.district}</option>)}</select>
      </>}
      <label className="f small" style={{ marginTop: 10 }}>שם לבקשה (רשות)<input value={f.title} onChange={e => setF({ ...f, title: e.target.value })} placeholder={`גוש ${f.gush} חלקה ${f.helka}`} /></label>
      <div className="wiz-nav"><button onClick={() => setStep(0)} disabled={busy}>→ חזרה</button>
        <button className="primary" disabled={busy || (st !== 'RESOLVED' && !pick)} onClick={confirmCommittee}>{busy ? 'פותח…' : 'אישור הוועדה והמשך ←'}</button></div>
    </section>}

    {step === 2 && v && <section className="card wiz-card">
      <h2>מה מבקשים?</h2>
      <p className="small muted">ועדה: <b>{committeeName}</b> · {v.jurisdiction?.status_he}</p>
      <label className="f">סוג הבקשה<select value={req.permit_type} onChange={e => setReq({ ...req, permit_type: e.target.value })}>
        {Object.entries(meta?.permit_types ?? {}).map(([k, x]) => <option key={k} value={k}>{x as string}</option>)}</select></label>
      <label className="f">תיאור הבקשה<textarea rows={3} maxLength={1000} value={req.purpose} onChange={e => setReq({ ...req, purpose: e.target.value })}
        placeholder="לדוגמה: בית מגורים חד־משפחתי בן 2 קומות עם ממ״ד" /></label>
      <label className="f">שימוש עיקרי (רשות)<input value={req.main_use} onChange={e => setReq({ ...req, main_use: e.target.value })} placeholder="מגורים / מסחר / תעשייה…" /></label>
      <div className="wiz-nav"><span />
        <button className="primary" disabled={busy || !req.purpose.trim()} onClick={saveRequest}>שמירה והמשך ←</button></div>
    </section>}

    {step === 3 && pkg && <section className="card wiz-card">
      <h2>מה חל על המגרש</h2>
      {v.workflow?.stages?.some((s: any) => s.status === 'pending') && <div className="notice info small">המערכת אוספת מידע תכנוני לחלקה — הדף מתעדכן לבד.</div>}
      <h3>תכניות חלות</h3>
      {pkg.plans?.length ? <ul className="small">{pkg.plans.slice(0, 10).map((p: any) => <li key={p.plan}><span className="ltr">{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.plan}</a> : p.plan}</span> {p.name ?? ''}
        <span className="muted"> · {p.relation === 'COVERS' ? 'חלה על כל החלקה' : 'חלה על חלק'}{p.status ? ` · ${p.status}` : ''}</span></li>)}</ul>
        : <p className="small muted">{pkg.xplan?.status_he || 'טרם נמצאו תכניות'}</p>}
      {pkg.land_use?.length > 0 && <p className="small">ייעודי קרקע: {pkg.land_use.join(' · ')}</p>}
      {pkg.restrictions?.length > 0 && <><h3>מגבלות ודגשים</h3><ul className="small">{pkg.restrictions.map((r: any, i: number) => <li key={i}>{r.text_he}</li>)}</ul></>}
      {pkg.requirements?.length > 0 && <><h3>מה נדרש להגיש</h3><ul className="small">{pkg.requirements.map((r: any) => <li key={r.id}><b>{r.text_he}</b> <span className="muted">— {r.why_he}</span></li>)}</ul></>}
      {pkg.missing?.length > 0 && <><h3>עדיין חסר</h3><ul className="small">{pkg.missing.map((m: any, i: number) => <li key={i}>{m.text_he}</li>)}</ul></>}
      <p className="small muted">{pkg.disclaimer_he}</p>
      <div className="wiz-nav"><button onClick={() => setStep(2)}>→ חזרה</button><button className="primary" onClick={() => setStep(4)}>המשך למסמכים ←</button></div>
    </section>}

    {step === 4 && v && <section className="card wiz-card">
      <h2>מסמכי הבקשה</h2>
      <p className="small muted">PDF, DWG, DXF או XLSX. אפשר להוסיף כמה קבצים לכל סוג.</p>
      <div className="user-form" style={{ padding: 0 }}>
        <label>סוג המסמך<select value={docType} onChange={e => setDocType(e.target.value)}>
          {DOCS.filter(k => meta?.doc_types?.[k]).map(k => <option key={k} value={k}>{meta.doc_types[k]}</option>)}</select></label>
        <label>קובץ<input id="wiz-file" type="file" accept=".pdf,.dwg,.dxf,.xlsx,.dwfx" onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
        <button className="primary" disabled={busy || !file} onClick={upload}>{busy ? 'מעלה…' : 'העלאה'}</button>
      </div>
      {files.length > 0 ? <table className="small" style={{ marginTop: 10 }}><thead><tr><th>קובץ</th><th>סוג</th><th>מצב</th></tr></thead><tbody>
        {files.map((x: any) => <tr key={x.id}><td className="ltr">{x.filename}</td><td>{meta?.doc_types?.[x.doc_type] ?? x.doc_type}</td><td>{x.ingest_status === 'OK' ? 'נקלט' : x.ingest_status}</td></tr>)}
      </tbody></table> : <p className="small muted" style={{ marginTop: 10 }}>טרם הועלו מסמכים.</p>}
      <div className="wiz-nav"><button onClick={() => setStep(3)}>→ חזרה</button><button className="primary" disabled={!files.length} onClick={() => setStep(5)}>המשך להגשה ←</button></div>
    </section>}

    {step === 5 && v && <section className="card wiz-card">
      <h2>סיכום והגשה</h2>
      <dl className="wiz-summary">
        <dt>נכס</dt><dd>גוש {v.case.gush} חלקה {v.case.helka}{v.case.declared?.lot ? ` מגרש ${v.case.declared.lot}` : ''}</dd>
        <dt>ועדה</dt><dd>{committeeName} <span className="small muted">({v.jurisdiction?.status_he})</span></dd>
        <dt>סוג</dt><dd>{meta?.permit_types?.[v.case.permit_type] ?? v.case.permit_type}</dd>
        <dt>תיאור</dt><dd>{v.case.declared?.purpose}</dd>
        <dt>מסמכים</dt><dd>{files.length}</dd>
      </dl>
      <ul className="wiz-check">{(v.checklist ?? []).map((c: any) => <li key={c.key} className={c.done ? 'ok' : 'bad'}>{c.done ? '✓' : '✗'} {c.text_he}</li>)}</ul>
      {!v.committee_connected && <div className="notice warn small">הוועדה {committeeName} עדיין אינה עובדת ב-Permit360. הבקשה תישמר עם מספר אישור, ויש להגישה גם במערכת רישוי זמין.</div>}
      <label className="wiz-radio"><input type="checkbox" checked={declared} onChange={e => setDeclared(e.target.checked)} />
        אני מצהיר/ה שהפרטים והמסמכים נכונים, ושאני מוסמך/ת להגיש את הבקשה בשם בעלי הזכויות בנכס.</label>
      <div className="wiz-nav"><button onClick={() => setStep(4)} disabled={busy}>→ חזרה</button>
        <button className="primary" disabled={busy || !declared || !(v.checklist ?? []).every((c: any) => c.done)} onClick={submit}>{busy ? 'מגיש…' : 'הגשת הבקשה'}</button></div>
    </section>}

    {step === 6 && sub && <section className="card wiz-card wiz-done">
      <div className="wiz-ok" aria-hidden>✓</div>
      <h2>הבקשה הוגשה</h2>
      <div className="small muted">מספר אישור</div>
      <div className="wiz-number ltr">{sub.confirmation_number}</div>
      <p>{sub.committee_name} · {new Date(sub.submitted_at).toLocaleString('he-IL')}</p>
      <p><span className={'chip ' + (sub.connected ? 'ok' : 'warn')}>{sub.status_he}</span></p>
      <p className="small">{sub.note_he}</p>
      <p className="small muted">אישור נשלח גם לכתובת הדוא״ל הרשומה בחשבון.</p>
      <div className="wiz-nav" style={{ justifyContent: 'center' }}>
        <button onClick={() => window.print()}>הדפסה</button>
        <Link className="button" to={`/cases/${id}`}>לפרויקט</Link>
        <a className="button primary" href="/apply">בקשה חדשה</a>
      </div>
    </section>}
  </div>
}
