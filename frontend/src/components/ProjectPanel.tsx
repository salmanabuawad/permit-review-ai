import { useEffect, useState } from 'react'
import { Case, api } from '../api'
import { useApp } from '../App'

const ST: Record<string, [string, string]> = { done: ['ok', 'הושלם'], warning: ['warn', 'דורש תשומת לב'], pending: ['info', 'בעבודה'],
  open: ['', 'פתוח'], available: ['info', 'זמין'] }
const JUR_OK = ['VERIFIED', 'RESOLVED']

/** Permit360 Pro: the project's preparation workflow, regulatory package and engineering assistant. */
export default function ProjectPanel({ c }: { c: Case }) {
  const { meta, toast } = useApp()
  const [v, setV] = useState<any>(null), [purpose, setPurpose] = useState({ permit_type: c.permit_type, purpose: '' })
  const [question, setQuestion] = useState(''), [answers, setAnswers] = useState<any[]>([]), [asking, setAsking] = useState(false)
  const load = () => api.get<any>(`/api/projects/${c.id}`).then(x => { setV(x); setPurpose(p => ({ ...p, purpose: p.purpose || x.case?.declared?.purpose || '' })) })
    .catch(e => toast(e.message, true))
  useEffect(() => { setV(null); load() }, [c.id])
  useEffect(() => {                                   // knowledge initialization runs in the crawler: refresh while pending
    if (!v || !v.workflow.stages.some((x: any) => x.status === 'pending')) return
    const t = setTimeout(load, 8000)
    return () => clearTimeout(t)
  }, [v])
  if (!v) return <div className="empty">טוען…</div>
  const { package: pkg, workflow: wf, jurisdiction: jur } = v
  const savePurpose = async () => {
    try { await api.put(`/api/projects/${c.id}/purpose`, purpose); toast('נשמר'); load() } catch (e: any) { toast(e.message, true) }
  }
  const ask = async () => {
    setAsking(true)
    try { const a = await api.post<any>(`/api/projects/${c.id}/assistant`, { question }); setAnswers([a, ...answers]); setQuestion('') }
    catch (e: any) { toast(e.message, true) } finally { setAsking(false) }
  }
  return <div className="project-panel">
    {v.submission ? <div className="notice ok small" style={{ marginBottom: 10 }}>הבקשה הוגשה · מספר אישור <b className="ltr">{v.submission.confirmation_number}</b> · {v.submission.committee_name} · {v.submission.status_he}</div>
      : <div className="small" style={{ marginBottom: 10 }}><a className="button primary" href={`/apply/${c.id}`}>המשך באשף ההגשה</a></div>}
    <ol className="stages" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, listStyle: 'none', padding: 0, margin: '0 0 10px' }}>
      {wf.stages.map((s: any, i: number) => <li key={s.key} className={'chip ' + (ST[s.status]?.[0] ?? '') + (wf.current === s.key ? ' current' : '')}
        title={ST[s.status]?.[1]} style={wf.current === s.key ? { outline: '2px solid currentColor' } : undefined}>{i + 1}. {s.label_he}</li>)}
    </ol>
    {wf.next_actions?.length > 0 && <div className="notice info small" style={{ marginBottom: 10 }}><b>העוזר מציע:</b>
      <ul style={{ margin: '4px 0' }}>{wf.next_actions.map((a: string, i: number) => <li key={i}>{a}</li>)}</ul></div>}
    <div className="grid-2" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 10 }}>
      <section className="card"><h3>נכס ותחום שיפוט</h3>
        <div className="small">גוש {pkg.property.gush} חלקה {pkg.property.helka}{pkg.property.lot ? ` מגרש ${pkg.property.lot}` : ''}
          {pkg.property.parcel && <> · {Math.round(pkg.property.parcel.area_m2).toLocaleString('he-IL')} מ"ר · {pkg.property.parcel.status}</>}</div>
        <div className="small">רשות: {(pkg.property.municipalities ?? []).map((m: any) => m.name_he).join(', ') || '—'} · יישוב: {(pkg.property.localities ?? []).map((l: any) => l.name_he).join(', ') || '—'}</div>
        <div style={{ marginTop: 6 }}><span className={'chip ' + (JUR_OK.includes(jur?.status) ? 'ok' : 'warn')}>{jur?.committee_name}: {jur?.status_he}</span></div>
        <div className="small muted">מסלול {jur?.path === 'A' ? 'א — בחירת ועדה' : 'ב — זיהוי לפי גוש וחלקה'} · נתוני גבולות: <span className="ltr">{jur?.datasets}</span></div>
        {pkg.jurisdiction.current?.status && pkg.jurisdiction.current.status !== 'RESOLVED' && JUR_OK.includes(jur?.status) &&
          <div className="small muted">בדיקה חוזרת: {pkg.jurisdiction.current.status_he}</div>}
      </section>
      <section className="card"><h3>מאגר הידע של הוועדה</h3>
        {pkg.committee_kb?.committee ? <div className="small">{pkg.committee_kb.committee} · {pkg.committee_kb.district} · קוד {pkg.committee_kb.codes?.join(', ') || '—'}
          <div>מסמכים: {pkg.committee_kb.documents} ({Object.entries(pkg.committee_kb.documents_by_kind ?? {}).map(([k, n]) => `${k}: ${n}`).join(', ') || '—'})</div>
          <div>עודכן: {pkg.committee_kb.age_days != null ? `לפני ${pkg.committee_kb.age_days} ימים` : 'טרם נשלף'}</div></div> : <div className="muted small">—</div>}
        {pkg.outdated?.map((m: any, i: number) => <div key={i} className="small warn">⚠ {m.text_he}</div>)}
      </section>
    </div>
    <section className="card" style={{ marginTop: 10 }}><h3>תכניות חלות (XPLAN, על החלקה הרשומה)</h3>
      <div className="small muted">{pkg.xplan?.status_he}{pkg.xplan?.checked_at ? ` · ${new Date(pkg.xplan.checked_at).toLocaleString('he-IL')}` : ''}</div>
      {pkg.plans?.length > 0 && <table className="small"><thead><tr><th>תכנית</th><th>שם</th><th>יחס לחלקה</th><th>סטטוס</th><th>פרסום</th></tr></thead><tbody>
        {pkg.plans.map((p: any) => <tr key={p.plan}><td className="ltr">{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.plan}</a> : p.plan}</td>
          <td>{p.name ?? '—'}</td><td>{p.relation === 'COVERS' ? 'חלה על כל החלקה' : 'חלה על חלק'}</td><td>{p.status ?? '—'}</td><td>{p.published ?? '—'}</td></tr>)}
      </tbody></table>}
      {pkg.land_use?.length > 0 && <div className="small" style={{ marginTop: 6 }}>ייעודי קרקע: {pkg.land_use.join(' · ')}</div>}
    </section>
    {pkg.restrictions?.length > 0 && <section className="card" style={{ marginTop: 10 }}><h3>מגבלות ודגשים</h3>
      <ul className="small" style={{ margin: 0 }}>{pkg.restrictions.map((r: any, i: number) => <li key={i}>{r.text_he}</li>)}</ul></section>}
    <section className="card" style={{ marginTop: 10 }}><h3>זכויות בנייה</h3>
      {pkg.rights ? <pre className="small" style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(pkg.rights, null, 1)}</pre> : <div className="small">{pkg.rights_note}</div>}</section>
    <section className="card" style={{ marginTop: 10 }}><h3>דרישות לבקשה</h3>
      <ul className="small" style={{ margin: 0 }}>{pkg.requirements.map((r: any) => <li key={r.id}><b>{r.text_he}</b> — <span className="muted">{r.why_he}</span>
        {r.links?.length > 0 && <> · {r.links.map((u: string, i: number) => <a key={i} href={u} target="_blank" rel="noreferrer" style={{ marginInlineStart: 4 }}>מבא"ת {i + 1}</a>)}</>}</li>)}</ul></section>
    {pkg.missing?.length > 0 && <section className="card" style={{ marginTop: 10 }}><h3>חסר / לא הוכרע</h3>
      <ul className="small" style={{ margin: 0 }}>{pkg.missing.map((m: any, i: number) => <li key={i}>{m.text_he}</li>)}</ul></section>}
    <section className="card" style={{ marginTop: 10 }}><h3>מטרת הבקשה</h3>
      <div className="user-form" style={{ padding: 0 }}>
        <label>סוג בקשה<select value={purpose.permit_type} onChange={e => setPurpose({ ...purpose, permit_type: e.target.value })}>{Object.entries(meta?.permit_types ?? {}).map(([k, x]) => <option key={k} value={k}>{x as string}</option>)}</select></label>
        <label style={{ flex: 2 }}>תיאור<input value={purpose.purpose} onChange={e => setPurpose({ ...purpose, purpose: e.target.value })} placeholder="לדוגמה: בית מגורים חד־משפחתי בן 2 קומות עם ממ״ד ובריכה" /></label>
        <button className="primary" onClick={savePurpose} disabled={!purpose.purpose.trim()}>שמירה</button></div></section>
    <section className="card" style={{ marginTop: 10 }}><h3>עוזר הנדסי</h3>
      <div className="user-form" style={{ padding: 0 }}><label style={{ flex: 3 }}>שאלה<input value={question} onChange={e => setQuestion(e.target.value)} placeholder="מה קווי הבניין? אילו אישורים נדרשים?" onKeyDown={e => e.key === 'Enter' && question.trim() && ask()} /></label>
        <button className="primary" disabled={asking || question.trim().length < 3} onClick={ask}>{asking ? 'חושב…' : 'שאל'}</button></div>
      {answers.map((a, i) => <div key={i} className="small" style={{ marginTop: 8, borderTop: '1px solid var(--line, #eee)', paddingTop: 6 }}>
        <b>{a.question}</b><div style={{ whiteSpace: 'pre-line' }}>{a.answer ?? <span className="muted">—</span>}</div>
        <div className="muted">{a.note_he}</div>
        {a.sources?.length > 0 && <details><summary>מקורות ({a.sources.length})</summary>{a.sources.map((s: any) => <div key={s.id}><span className="mono">[{s.id}]</span> {s.source_title_he}{s.page ? `, עמ׳ ${s.page}` : ''}{s.url && /^https?:/.test(s.url) && <> · <a href={s.url} target="_blank" rel="noreferrer">מקור</a></>}</div>)}</details>}
      </div>)}
    </section>
    <p className="small muted" style={{ marginTop: 8 }}>{pkg.disclaimer_he}</p>
  </div>
}
