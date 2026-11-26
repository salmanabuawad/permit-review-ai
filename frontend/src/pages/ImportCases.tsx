import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtDate, uploadWithProgress } from '../api'
import { useApp } from '../App'

interface Src { file: string; page: number | null; original_page: number | null; quote: string | null; method: string; confidence: number; provider: string }
interface FieldV { value: any; confidence: number; needs_review: boolean; source: Src }
interface ADoc { ref: string; name: string; doc_type: string; doc_class: string | null; origin: any; sha256: string; duplicate_of?: string | null }
interface App_ {
  key: string; application_number: string | null; status: 'new' | 'duplicate'; fields: Record<string, FieldV>
  comments: { department: string; department_he: string; item_no: string | null; text: string; source: Src }[]
  areas: { floor: string | null; status: string | null; label: string; value_m2: number; source: Src }[]
  decision: null | { outcome: string; text: string; conditions: string[]; meeting_number: string | null; meeting_date: string | null; source: Src }
  procedure: string[]; documents: ADoc[]; warnings: string[]; item_number: string | null; meeting_number: string | null; meeting_date: string | null
}
interface PDoc { ref: string; name: string; status: string; messages: string[]; classification: any; pages: number | null; applications: (string | null)[]; doc_type: string | null; size: number }
interface Preview { token: string; documents: PDoc[]; applications: App_[]; planning_items: any[]; warnings: string[]; counts: Record<string, number> }

const FIELDS: { key: string; label: string; ltr?: boolean; area?: boolean }[] = [
  { key: 'application_number', label: 'מספר בקשה', ltr: true },
  { key: 'building_file_number', label: 'תיק בניין', ltr: true },
  { key: 'address', label: 'כתובת' },
  { key: 'gush', label: 'גוש', ltr: true },
  { key: 'helka', label: 'חלקה', ltr: true },
  { key: 'zone', label: 'יעוד' },
  { key: 'plot_area_m2', label: 'שטח מגרש (מ״ר)', ltr: true },
  { key: 'application_type', label: 'סוג בקשה (כנוסחו במסמך)' },
  { key: 'applicable_plans', label: 'תוכניות חלות' },
  { key: 'description', label: 'מהות הבקשה', area: true },
  { key: 'deviations', label: 'הקלות שפורסמו', area: true },
]
const STATUS_HE: Record<string, string> = { ok: 'עובד', metadata: 'קובץ אינדקס', skipped: 'דולג', failed: 'נכשל', unassigned: 'לא שויך' }
const OUTCOME_HE: Record<string, string> = {
  approved: 'אושר', approved_with_conditions: 'אושר בתנאים / בהערות', renewed: 'חידוש אישור',
  objection_partially_accepted: 'התנגדות התקבלה בחלקה — אושר בתנאים', objection_rejected: 'התנגדות נדחתה — אושר',
  deferred: 'הדיון נדחה', rejected: 'נדחה', other: 'אחר — נדרש עיון',
}
const RESULT_HE: Record<string, string> = { created: 'נוצרה', updated: 'עודכנה', duplicate: 'כפולה — קיימת', skipped: 'דולגה', failed: 'נכשלה' }

function conf(c: number) {
  if (c >= 0.85) return { cls: 'ok', he: 'ודאות גבוהה' }
  if (c >= 0.8) return { cls: 'outline', he: 'ודאות בינונית' }
  return { cls: 'warn', he: 'נדרש אימות' }
}
const pct = (c: number) => `${Math.round(c * 100)}%`

export default function ImportCases() {
  const { meta, can, toast } = useApp()
  const [files, setFiles] = useState<File[]>([])
  const [drag, setDrag] = useState(false)
  const [stage, setStage] = useState<'select' | 'upload' | 'analyze' | 'review' | 'done'>('select')
  const [progress, setProgress] = useState(0)
  const [pv, setPv] = useState<Preview | null>(null)
  const [edits, setEdits] = useState<Record<string, Record<string, any>>>({})
  const [include, setInclude] = useState<Record<string, boolean>>({})
  const [docSel, setDocSel] = useState<Record<string, { include: boolean; doc_type: string }>>({})
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [runChecks, setRunChecks] = useState(true)
  const [result, setResult] = useState<any>(null)
  const [preview, setPreview] = useState<{ title: string; url: string; quote: string | null; meta: string } | null>(null)
  const [batches, setBatches] = useState<any[]>([])
  const [filter, setFilter] = useState<'all' | 'review' | 'new' | 'duplicate'>('all')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { if (can('case.create')) api.get<any[]>('/api/import/batches').then(setBatches).catch(() => {}) }, [stage])

  const apps = pv?.applications ?? []
  const needsReview = (a: App_) => Object.values(a.fields).some(f => f.needs_review) || a.warnings.length > 0 || !a.fields.permit_type
  const shown = useMemo(() => apps.filter(a => filter === 'all' ? true : filter === 'review' ? needsReview(a) : a.status === filter), [apps, filter])

  if (!can('case.create')) return <div className="notice">קליטת מסמכים זמינה למזכירות, לבודקים, למנהל האגף ולמנהל המערכת.</div>

  const addFiles = (list: FileList | File[]) => {
    const arr = Array.from(list)
    setFiles(f => [...f, ...arr.filter(x => !f.some(y => y.name === x.name && y.size === x.size))])
  }

  const analyze = async () => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    setStage('upload'); setProgress(0); setResult(null)
    try {
      const r = await uploadWithProgress<Preview>('/api/import/analyze', fd, p => { setProgress(p); if (p >= 100) setStage('analyze') })
      setPv(r); setEdits({}); setOpen({})
      setInclude(Object.fromEntries(r.applications.map(a => [a.key, a.status === 'new'])))
      setDocSel(Object.fromEntries(r.applications.flatMap(a => a.documents.map(d => [d.ref, { include: !d.duplicate_of, doc_type: d.doc_type || 'other' }]))))
      // the analysis found only new requests: create them and start processing at once (no second click)
      if (r.applications.length && r.applications.every(a => a.status === 'new')) {
        setStage('analyze')
        const applications = r.applications.map(a => ({
          key: a.key, include: true, fields: {},
          documents: a.documents.map(d => ({ ref: d.ref, include: !d.duplicate_of, doc_type: d.doc_type || 'other' })),
        }))
        const res = await api.post<any>('/api/import/commit', { token: r.token, applications, run_checks: runChecks })
        setResult(res); setStage('done')
        return
      }
      setStage('review')
    } catch (e: any) { toast(e.message, true); setStage('select') }
  }

  const val = (a: App_, k: string) => edits[a.key]?.[k] ?? a.fields[k]?.value ?? ''
  const setVal = (a: App_, k: string, v: any) => setEdits(e => ({ ...e, [a.key]: { ...(e[a.key] ?? {}), [k]: v } }))

  const commit = async () => {
    if (!pv) return
    setStage('analyze')
    try {
      const applications = apps.map(a => ({
        key: a.key, include: !!include[a.key], fields: edits[a.key] ?? {},
        documents: a.documents.map(d => ({ ref: d.ref, include: docSel[d.ref]?.include ?? true, doc_type: docSel[d.ref]?.doc_type })),
      }))
      const r = await api.post<any>('/api/import/commit', { token: pv.token, applications, run_checks: runChecks })
      setResult(r); setStage('done')
    } catch (e: any) { toast(e.message, true); setStage('review') }
  }

  const showSource = (s: Src | undefined, title: string) => {
    if (!s || !pv) return
    const doc = pv.documents.find(d => d.name === s.file)
    if (!doc || !s.page) { toast('אין תצוגת עמוד למקור זה (מקור: ' + s.file + ')'); return }
    setPreview({ title, url: `/api/import/${pv.token}/page/${doc.ref}/${s.page}.png`, quote: s.quote,
      meta: `${s.file} · עמוד ${s.page}${s.original_page ? ` (בפרוטוקול המקורי: עמוד ${s.original_page})` : ''} · ${s.method} · ${pct(s.confidence)}` })
  }

  const SrcLink = ({ s, title }: { s?: Src; title: string }) => s ? (
    <button className="link-btn" onClick={() => showSource(s, title)} title={s.method}>
      עמ׳ {s.page ?? '—'}{s.original_page ? ` (מקור ${s.original_page})` : ''}
    </button>) : <span className="muted">—</span>

  const selected = apps.filter(a => include[a.key])
  const c = pv?.counts ?? {}
  const steps = [['select', 'בחירת קבצים'], ['upload', 'העלאה'], ['analyze', 'סיווג וחילוץ'], ['review', 'בדיקה ואישור'], ['done', 'ייבוא הושלם']] as const
  const stepIdx = steps.findIndex(s => s[0] === stage)

  return (
    <>
      <div className="page-head">
        <div>
          <div className="small muted"><Link to="/cases">תיקי בקשות</Link> ‹ קליטת מסמכים</div>
          <h1>קליטת מסמכים</h1>
          <p>קליטת בקשות להיתר מתוך קבצים: המערכת מסווגת כל מסמך לפי תוכנו, מזהה את הבקשות, מחלצת את הנתונים עם מקור לכל ערך — והתיקים נוצרים רק לאחר אישורכם.</p>
        </div>
      </div>

      <ol className="stepper" aria-label="שלבי הקליטה">
        {steps.map(([k, label], i) => <li key={k} className={i < stepIdx || stage === 'done' ? 'done' : i === stepIdx ? 'current' : ''}>{label}</li>)}
      </ol>

      {(stage === 'select' || stage === 'upload' || (stage === 'analyze' && !pv)) && (
        <div className="card">
          <div className={'dropzone' + (drag ? ' drag' : '')} role="button" tabIndex={0}
            onClick={() => inputRef.current?.click()} onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
            onDrop={e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files) }}>
            <div className="dropzone-icon" aria-hidden="true">⇪</div>
            <strong>גררו לכאן קבצים או חבילת ZIP</strong>
            <span className="small muted">או לחצו לבחירה · PDF, ZIP, DXF/DWG, Excel, CSV/JSON (קובצי אינדקס)</span>
            <input ref={inputRef} type="file" multiple hidden accept=".zip,.pdf,.dxf,.dwg,.xlsx,.xlsm,.csv,.json,.html"
              onChange={e => { if (e.target.files) addFiles(e.target.files); e.target.value = '' }} />
          </div>
          {files.length > 0 && (
            <ul className="file-list">
              {files.map((f, i) => (
                <li key={i}><span className="ltr">{f.name}</span><span className="small muted num">{(f.size / 1024 / 1024).toFixed(2)} MB</span>
                  {stage === 'select' && <button className="ghost sm" aria-label={`הסרת ${f.name}`} onClick={() => setFiles(x => x.filter((_, j) => j !== i))}>הסרה</button>}</li>
              ))}
            </ul>
          )}
          {stage === 'upload' && <div className="progress" aria-label="התקדמות העלאה"><i style={{ width: `${progress}%` }} /><span className="num">{progress}%</span></div>}
          {stage === 'analyze' && <div className="notice info" role="status">הקבצים הועלו — מסווג מסמכים ומחלץ נתונים…</div>}
          <div className="card-head" style={{ marginTop: 14, marginBottom: 0 }}>
            <span className="small muted">קובצי index.csv / index.json משמשים להתאמת מסמכים בלבד — לא נוצרות מהם בקשות.</span>
            <span className="spacer" />
            <button className="primary" disabled={!files.length || stage !== 'select'} onClick={analyze}>ניתוח וחילוץ</button>
          </div>
        </div>
      )}

      {pv && stage !== 'done' && (
        <>
          <div className="summary-strip">
            <div><b className="num">{pv.documents.length}</b><span>מסמכים</span></div>
            <div><b className="num">{c.applications ?? 0}</b><span>בקשות זוהו</span></div>
            <div className={c.applications_new ? 's-ok' : ''}><b className="num">{c.applications_new ?? 0}</b><span>חדשות</span></div>
            <div className="s-dup"><b className="num">{c.applications_duplicate ?? 0}</b><span>קיימות במערכת</span></div>
            <div><b className="num">{c.documents_metadata ?? 0}</b><span>קובצי אינדקס</span></div>
            <div><b className="num">{c.planning_items ?? 0}</b><span>פריטים תכנוניים</span></div>
            <div className={(c.documents_failed ?? 0) + (c.documents_skipped ?? 0) + (c.documents_unassigned ?? 0) ? 's-bad' : ''}><b className="num">{(c.documents_failed ?? 0) + (c.documents_skipped ?? 0) + (c.documents_unassigned ?? 0)}</b><span>דולגו / נכשלו</span></div>
          </div>
          {pv.warnings.length > 0 && <div className="notice" style={{ marginBottom: 14 }}>{pv.warnings.map((w, i) => <div key={i}>{w}</div>)}</div>}

          <details className="card" open={pv.documents.length <= 12}>
            <summary><h3 style={{ display: 'inline' }}>מסמכים וסיווג</h3> <span className="small muted">({pv.documents.length})</span></summary>
            <div className="table-wrap" style={{ marginTop: 10 }}><table>
              <thead><tr><th>קובץ</th><th>סוג מסמך</th><th>ודאות</th><th>עמודים</th><th>מצב</th><th>בקשות</th><th>הודעות</th></tr></thead>
              <tbody>{pv.documents.map(d => (
                <tr key={d.ref}>
                  <td><span className="ltr">{d.name}</span></td>
                  <td>{d.classification?.doc_class_he ?? '—'}<div className="small muted">{(d.classification?.signals ?? []).slice(0, 2).join(' · ')}</div></td>
                  <td>{d.classification ? <span className={'chip ' + conf(d.classification.confidence).cls}>{pct(d.classification.confidence)}</span> : '—'}</td>
                  <td className="num">{d.pages ?? '—'}</td>
                  <td><span className={'chip ' + (d.status === 'ok' ? 'ok' : d.status === 'metadata' ? 'outline' : 'warn')}>{STATUS_HE[d.status] ?? d.status}</span></td>
                  <td className="small ltr">{d.applications.filter(Boolean).join(', ') || '—'}</td>
                  <td className="small">{d.messages.join(' · ')}</td>
                </tr>))}</tbody>
            </table></div>
          </details>

          <div className="card">
            <div className="card-head">
              <h3>בקשות שזוהו</h3>
              <span className="spacer" />
              <div className="seg" role="group" aria-label="סינון בקשות">
                {([['all', 'הכל'], ['review', 'נדרש אימות'], ['new', 'חדשות'], ['duplicate', 'קיימות']] as const).map(([k, l]) => (
                  <button key={k} className={filter === k ? 'active' : ''} onClick={() => setFilter(k)}>{l}</button>))}
              </div>
              <button className="sm" onClick={() => setInclude(Object.fromEntries(apps.map(a => [a.key, a.status === 'new'])))}>בחירת כל החדשות</button>
              <button className="sm" onClick={() => setInclude({})}>ניקוי בחירה</button>
            </div>

            {shown.map(a => {
              const isOpen = open[a.key]
              const ptype = val(a, 'permit_type')
              const review = needsReview(a)
              return (
                <article key={a.key} className={'app-card' + (include[a.key] ? ' selected' : '')}>
                  <header className="app-card-head">
                    <input type="checkbox" checked={!!include[a.key]} aria-label={`לכלול את בקשה ${a.application_number ?? ''} בייבוא`}
                      onChange={e => setInclude(x => ({ ...x, [a.key]: e.target.checked }))} />
                    <div className="app-title">
                      <strong>מספר בקשה <span className="ltr">{val(a, 'application_number') || '—'}</span></strong>
                      <span className="muted"> · {val(a, 'address') || 'כתובת לא זוהתה'}{a.item_number ? ` · סעיף ${a.item_number}` : ''}</span>
                    </div>
                    <span className={'chip ' + (a.status === 'new' ? 'ok' : 'outline')}>{a.status === 'new' ? 'חדשה' : 'קיימת במערכת'}</span>
                    {review && <span className="chip warn">נדרש אימות</span>}
                    {a.decision && <span className="chip outline">{OUTCOME_HE[a.decision.outcome] ?? a.decision.outcome}</span>}
                    <select value={ptype} aria-label="סוג בקשה" onChange={e => setVal(a, 'permit_type', e.target.value)}
                      style={!ptype ? { borderColor: 'var(--fail)' } : undefined}>
                      <option value="">— סוג בקשה —</option>
                      {Object.entries(meta.permit_types).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}
                    </select>
                    <button className="sm" aria-expanded={!!isOpen} onClick={() => setOpen(o => ({ ...o, [a.key]: !o[a.key] }))}>{isOpen ? 'סגירה' : 'פרטים'}</button>
                  </header>
                  <div className="small muted" style={{ marginTop: 4 }}>
                    {a.fields.permit_type ? <>סוג הבקשה זוהה: {a.fields.permit_type.source.method} · <span className={'chip ' + conf(a.fields.permit_type.confidence).cls}>{conf(a.fields.permit_type.confidence).he}</span></> : 'סוג הבקשה לא זוהה — יש לבחור'}
                    {a.procedure.length > 0 && <> · הליך: {a.procedure.join(', ')}</>}
                    {' · '}{a.documents.length === 1 ? 'מסמך אחד' : `${a.documents.length} מסמכים`}
                  </div>
                  {isOpen && (
                    <div className="app-body">
                      <div className="field-grid">
                        {FIELDS.map(f => {
                          const fv = a.fields[f.key]
                          const edited = edits[a.key]?.[f.key] !== undefined && String(edits[a.key][f.key]) !== String(fv?.value ?? '')
                          return (
                            <label key={f.key} className={'xfield' + (f.area ? ' wide' : '')}>
                              <span className="xlabel">{f.label}
                                {fv ? <span className={'chip ' + conf(fv.confidence).cls}>{edited ? 'נערך' : `${conf(fv.confidence).he} · ${pct(fv.confidence)}`}</span>
                                  : <span className="chip outline">לא נמצא במסמך</span>}
                              </span>
                              {f.area
                                ? <textarea rows={2} value={val(a, f.key)} onChange={e => setVal(a, f.key, e.target.value)} />
                                : <input dir={f.ltr ? 'ltr' : undefined} value={val(a, f.key)} onChange={e => setVal(a, f.key, e.target.value)} />}
                              <span className="xsrc">מקור: <SrcLink s={fv?.source} title={f.label} />{fv?.source?.method ? <span className="muted"> · {fv.source.method}</span> : null}</span>
                            </label>)
                        })}
                      </div>

                      {a.areas.length > 0 && (
                        <section><h4>שטחים <span className="chip warn">נדרש אימות</span></h4>
                          <div className="table-wrap"><table className="compact">
                            <thead><tr><th>קומה</th><th>מצב</th><th>שימוש</th><th>מ״ר</th></tr></thead>
                            <tbody>{a.areas.slice(0, 40).map((x, i) => <tr key={i}><td>{x.floor ?? '—'}</td><td>{x.status === 'existing' ? 'קיים' : x.status === 'proposed' ? 'מוצע' : '—'}</td><td>{x.label}</td><td className="num">{x.value_m2}</td></tr>)}</tbody>
                          </table></div>
                          {a.areas.length > 40 && <p className="small muted">ועוד {a.areas.length - 40} שורות</p>}
                          <span className="xsrc">מקור: <SrcLink s={a.areas[0].source} title="שטחים" /> · {a.areas[0].source.method}</span>
                        </section>)}

                      {a.comments.length > 0 && (
                        <section><h4>הערות הוועדה וגורמי המקצוע</h4>
                          {Object.entries(a.comments.reduce((acc: Record<string, typeof a.comments>, x) => { (acc[x.department_he] ??= []).push(x); return acc }, {})).map(([dept, list]) => (
                            <div key={dept} className="dept">
                              <div className="dept-head">{dept} <span className="small muted">({list.length})</span> <SrcLink s={list[0].source} title={`הערות ${dept}`} /></div>
                              <ol className="comments">{list.map((x, i) => <li key={i}>{x.item_no && <span className="num item-no">{x.item_no}.</span>} {x.text}</li>)}</ol>
                            </div>))}
                        </section>)}

                      {a.decision ? (
                        <section className="decision-box"><h4>החלטת הוועדה <span className="chip outline">{OUTCOME_HE[a.decision.outcome] ?? a.decision.outcome}</span></h4>
                          <p>{a.decision.text}</p>
                          {a.decision.conditions.length > 0 && <ol>{a.decision.conditions.map((x, i) => <li key={i}>{x}</li>)}</ol>}
                          <span className="xsrc">ישיבה <span className="num">{a.decision.meeting_number ?? '—'}</span> · {a.decision.meeting_date ?? '—'} · מקור: <SrcLink s={a.decision.source} title="החלטת הוועדה" /></span>
                        </section>) : <div className="notice small">לא נמצאה החלטת ועדה במסמכי הבקשה.</div>}

                      <section><h4>מסמכי הבקשה</h4>
                        <div className="table-wrap"><table className="compact">
                          <thead><tr><th></th><th>קובץ</th><th>סוג מסמך</th><th>מקור</th></tr></thead>
                          <tbody>{a.documents.map(d => (
                            <tr key={d.ref}>
                              <td><input type="checkbox" checked={docSel[d.ref]?.include ?? true} aria-label={`לצרף את ${d.name}`}
                                onChange={e => setDocSel(x => ({ ...x, [d.ref]: { ...(x[d.ref] ?? { doc_type: d.doc_type }), include: e.target.checked } }))} /></td>
                              <td><span className="ltr">{d.name}</span>{d.duplicate_of && <div className="small muted">מסמך זהה כבר קיים בתיק {d.duplicate_of}</div>}</td>
                              <td><select value={docSel[d.ref]?.doc_type ?? d.doc_type} onChange={e => setDocSel(x => ({ ...x, [d.ref]: { ...(x[d.ref] ?? { include: true }), doc_type: e.target.value } }))}>
                                {Object.entries(meta.doc_types).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></td>
                              <td className="small">{d.origin ? <>עמודים {d.origin.pages.join('–')} מתוך <span className="ltr">{d.origin.file}</span></> : 'קובץ מקורי'}</td>
                            </tr>))}</tbody>
                        </table></div>
                      </section>
                      {a.warnings.length > 0 && <div className="flags">{a.warnings.map((w, i) => <span key={i} className="chip warn">{w}</span>)}</div>}
                    </div>
                  )}
                </article>)
            })}
            {!shown.length && <div className="empty">אין בקשות להצגה</div>}
          </div>

          <div className="card sticky-actions">
            <label className="small" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input type="checkbox" checked={runChecks} onChange={e => setRunChecks(e.target.checked)} /> להריץ בדיקה לכל תיק חדש לאחר הייבוא
            </label>
            <span className="spacer" />
            <span className="small muted">בקשות קיימות לא ייווצרו שוב; מסמכים חדשים בלבד יצורפו אליהן.</span>
            <button onClick={() => { setPv(null); setStage('select') }}>ביטול</button>
            <button className="primary" disabled={!selected.length || stage === 'analyze'} onClick={commit}>
              {stage === 'analyze' ? 'מייבא…' : `ייבוא ${selected.length} בקשות`}
            </button>
          </div>
        </>
      )}

      {stage === 'done' && result && (
        <div className="card">
          <h2>ייבוא הושלם</h2>
          <div className="summary-strip">
            <div className="s-ok"><b className="num">{result.summary.created}</b><span>נוצרו</span></div>
            <div><b className="num">{result.summary.updated}</b><span>עודכנו (מסמכים חדשים)</span></div>
            <div className="s-dup"><b className="num">{result.summary.duplicate}</b><span>כפולות — לא נוצרו</span></div>
            <div><b className="num">{result.summary.skipped}</b><span>דולגו</span></div>
            <div className={result.summary.failed ? 's-bad' : ''}><b className="num">{result.summary.failed}</b><span>נכשלו</span></div>
            <div><b className="num">{result.summary.metadata_files}</b><span>קובצי אינדקס</span></div>
          </div>
          <div className="table-wrap"><table>
            <thead><tr><th>מספר בקשה</th><th>תוצאה</th><th>פרטים</th></tr></thead>
            <tbody>{result.results.map((x: any, i: number) => (
              <tr key={i}><td>{x.case_id ? <Link className="ltr" to={`/cases/${x.case_id}`}>{x.application_number}</Link> : <span className="ltr">{x.application_number ?? '—'}</span>}</td>
                <td><span className={'chip ' + (x.status === 'created' ? 'ok' : x.status === 'failed' ? 'bad' : 'outline')}>{RESULT_HE[x.status] ?? x.status}</span></td>
                <td className="small">{x.message}</td></tr>))}</tbody>
          </table></div>
          <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
            <button className="primary" onClick={() => { setFiles([]); setPv(null); setResult(null); setStage('select') }}>קליטה נוספת</button>
            <Link to="/cases" className="btn">לרשימת התיקים</Link>
          </div>
        </div>
      )}

      {batches.length > 0 && stage !== 'review' && (
        <details className="card">
          <summary><h3 style={{ display: 'inline' }}>היסטוריית קליטות</h3></summary>
          <div className="table-wrap" style={{ marginTop: 10 }}><table className="compact">
            <thead><tr><th>מועד</th><th>קבצים</th><th>מצב</th><th>נוצרו</th><th>עודכנו</th><th>כפולות</th><th>נכשלו</th></tr></thead>
            <tbody>{batches.map(b => (
              <tr key={b.id}><td>{fmtDate(b.created_at)}</td><td className="small ltr">{b.files.map((f: any) => f.name).join(', ')}</td>
                <td>{({ analyzed: 'נותח — לא יובא', committed: 'יובא', partial: 'יובא חלקית', failed: 'נכשל' } as any)[b.status] ?? b.status}</td>
                <td className="num">{b.summary.created ?? '—'}</td><td className="num">{b.summary.updated ?? '—'}</td>
                <td className="num">{b.summary.duplicate ?? '—'}</td><td className="num">{b.summary.failed ?? '—'}</td></tr>))}</tbody>
          </table></div>
        </details>
      )}

      {preview && (
        <>
          <div className="drawer-back" onClick={() => setPreview(null)} />
          <aside className="drawer drawer-wide" role="dialog" aria-label="תצוגת מקור">
            <div className="card-head"><h3>מקור: {preview.title}</h3><span className="spacer" /><button onClick={() => setPreview(null)}>סגירה</button></div>
            <p className="small muted">{preview.meta}</p>
            {preview.quote && <div className="quote">“{preview.quote}”</div>}
            <img src={preview.url} alt={`עמוד המקור — ${preview.title}`} className="page-img" />
          </aside>
        </>
      )}
    </>
  )
}
