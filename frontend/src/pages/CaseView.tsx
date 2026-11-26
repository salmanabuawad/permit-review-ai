import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Case, Citation, Report, api, fmt, fmtDate, openBlob } from '../api'
import { useApp } from '../App'
import CadViewer from '../components/CadViewer'
import SheetViewer from '../components/SheetViewer'
import { StatusChip } from '../components/FindingCard'
import FindingsPanel from '../components/FindingsPanel'
import SourceDrawer from '../components/SourceDrawer'
import DecisionPanel from '../components/DecisionPanel'
import ScopePanel from '../components/ScopePanel'
import AccuracyPanel from '../components/AccuracyPanel'
import RevisionPanel from '../components/RevisionPanel'
import ProcessPanel from '../components/ProcessPanel'
import PropertyPanel from '../components/PropertyPanel'
import InspectionPanel from '../components/InspectionPanel'

const LIFECYCLE_HE: Record<string, string> = { ACTIVE: 'פעיל', ARCHIVED: 'בארכיון', DELETED: 'נמחק' }
const INGEST_HE: Record<string, string> = {
  OK: 'נקלט', NEEDS_OCR: 'נדרש OCR', NEEDS_CONVERSION: 'נדרשת המרה (DWG)', NEEDS_UNITS: 'חסרות יחידות',
  NO_AREA_TABLE: 'לא זוהתה טבלת שטחים', ERROR: 'שגיאה', QUARANTINED: 'בהסגר', PENDING: 'ממתין', PENDING_CONVERSION: 'ממתין להמרה (DWFX)',
}

export default function CaseView() {
  const { id } = useParams()
  const { meta, can, toast } = useApp()
  const [c, setC] = useState<Case | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const kind = 'reviewer'                       // one report view: the full reviewer report
  const [geo, setGeo] = useState<any>(null)
  const [geoLoading, setGeoLoading] = useState(true)
  const [sel, setSel] = useState<string | null>(null)
  const [cite, setCite] = useState<Citation | null>(null)
  const [tab, setTab] = useState<'findings' | 'files' | 'data' | 'extracted' | 'history' | 'decision' | 'scope' | 'accuracy' | 'revision' | 'process' | 'property' | 'inspection'>('findings')
  const [busy, setBusy] = useState(false)
  const [runs, setRuns] = useState<any[]>([])

  // The drawing geometry can be large (a 31 MB school plan: ~40k entities, 11.7 MB, 16 s), so it loads on its own
  // and only when the files change; the case, runs and report never wait for it.
  const loadGeo = useCallback(async () => {
    setGeoLoading(true)
    try { setGeo(await api.get(`/api/cases/${id}/geometry`)) } finally { setGeoLoading(false) }
  }, [id])
  useEffect(() => { loadGeo().catch(e => toast(e.message, true)) }, [loadGeo, toast])

  const load = useCallback(async () => {
    const [cc, rs] = await Promise.all([api.get<Case>(`/api/cases/${id}`), api.get<any[]>(`/api/cases/${id}/runs`)])
    setC(cc)
    setRuns(rs)
    if (cc.last_run) setReport(await api.get<Report>(`/api/runs/${cc.last_run.id}/report/${kind}`))
    else setReport(null)
  }, [id, kind])
  useEffect(() => { load().catch(e => toast(e.message, true)) }, [load, toast])
  const processing = !!c?.processing && !c.processing.ready
  useEffect(() => {                                   // while the request is still processing, refresh every 15 s
    if (!processing) return
    const t = window.setInterval(() => { load().catch(() => undefined) }, 15000)
    return () => window.clearInterval(t)
  }, [processing, load])
  const reloadFiles = useCallback(async () => { await load(); loadGeo().catch(e => toast(e.message, true)) }, [load, loadGeo, toast])

  const run = async () => {
    setBusy(true)
    try {
      const r = await api.post<any>(`/api/cases/${id}/run`)
      toast(`בדיקה גרסה ${r.version} הושלמה תוך ${r.duration_ms} מ״ש`)
      await load()
    } catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }
  const workflow = async (status: string, extra: any = {}) => {
    try { await api.post(`/api/cases/${id}/workflow`, { status, ...extra }); toast('עודכן'); await load() }
    catch (e: any) { toast(e.message, true) }
  }
  const decide = async (fid: string, decision: string, note: string) => {
    try { await api.post(`/api/findings/${fid}/decision`, { decision, note }); await load() }
    catch (e: any) { toast(e.message, true) }
  }

  const findings = useMemo(() => (report?.findings ?? []).filter(f => f.status !== 'NA'), [report])
  const counts = useMemo(() => {
    const o: Record<string, number> = { PASS: 0, FAIL: 0, UNCERTAIN: 0, NA: 0 }
    report?.findings.forEach(f => { o[f.status]++ })
    return o
  }, [report])

  const sheetFile = (c?.files ?? []).filter(f => f.lifecycle === 'ACTIVE' && f.ingest_status === 'OK' &&
    (f.kind === 'dwfx' || (f.kind === 'pdf' && f.doc_type === 'architectural_plan')))
    .sort((a, b) => (a.doc_type === 'architectural_plan' ? 0 : 1) - (b.doc_type === 'architectural_plan' ? 0 : 1)
      || (a.kind === 'dwfx' ? 0 : 1) - (b.kind === 'dwfx' ? 0 : 1))[0]
  if (!c || !meta) return <div className="empty">טוען תיק…</div>
  const locked = c.locked_version !== null
  const hasFiles = (c.files?.length ?? 0) > 0
  const pending = (report?.findings ?? []).filter(f => (f.status === 'FAIL' || f.status === 'UNCERTAIN') && !f.reviewer_decision).length
  const steps = [
    { label: 'קליטת קבצים', done: hasFiles },
    { label: 'בדיקת שלמות ותנאי סף', done: !!c.last_run },
    { label: 'דוח זכויות', done: !!c.last_run },
    { label: 'דוח בודק והחלטות', done: !!c.last_run && pending === 0 },
    { label: 'אישור ונעילת גרסה', done: locked },
  ]
  const current = steps.findIndex(s => !s.done)

  return (
    <>
      <div className="page-head">
        <div>
          <div className="small muted"><Link to="/cases">תיקי בקשות</Link> ‹ <span className="ltr">{c.case_number}</span></div>
          <h1>{c.title}</h1>
          <p>
            {meta.permit_types[c.permit_type]} · {meta.tracks[c.track]} · גוש <span className="ltr">{c.gush ?? '—'}</span> חלקה <span className="ltr">{c.helka ?? '—'}</span>
            {' · '}{c.address ?? ''}
          </p>
        </div>
        <span className="spacer" />
        {c.is_demo && <span className="chip demo">הדגמה</span>}
        <span className="chip outline">{meta.case_statuses[c.status] ?? c.status}</span>
        {can('case.run') && <button className="primary" onClick={run} disabled={busy || locked || !hasFiles}>{busy ? 'מריץ…' : c.last_run ? 'בדיקה חוזרת' : 'הרצת בדיקה'}</button>}
      </div>

      <ol className="stepper compact" aria-label="שלבי הטיפול בתיק">
        {steps.map((s, i) => <li key={i} className={s.done ? 'done' : i === current ? 'current' : ''}>{s.label}</li>)}
      </ol>

      {c.last_run && report && (
        <div className="card case-results" style={{ marginBottom: 14 }}>
          <div className="card-head">
            <h3>תוצאות בדיקה — גרסה <span className="num">{report.run.version}</span></h3>
            <span className="small muted">{fmtDate(report.run.at)} · <span className="num">{report.run.duration_ms}</span> מ״ש · ruleset <span className="mono">{report.run.ruleset_hash.slice(0, 10)}</span></span>
            <span className="spacer" />
            <div className="counts">
              {(['FAIL', 'UNCERTAIN', 'PASS', 'NA'] as const).map(s => <span key={s}><StatusChip s={s} /> <span className="num">{counts[s]}</span></span>)}
            </div>
            <div className="actions no-print">
              <span className="small muted">ייצוא:</span>
              <button className="sm" onClick={() => openBlob(`/api/runs/${c.last_run!.id}/defects.pdf`).catch(e => toast(e.message, true))}>
                PDF — דוח ליקויים
              </button>
              {can('case.run') && !locked && <button className="sm" onClick={() => workflow('RETURNED_FOR_COMPLETION', { note: 'החזרה להשלמות' })}>החזרה להשלמות</button>}
              {can('case.run') && !locked && c.status !== 'WAITING_EXTERNAL' && <button className="sm" onClick={() => workflow('WAITING_EXTERNAL', { note: 'הועבר לגורם חוץ' })}>ממתין לגורם חוץ</button>}
              {can('case.run') && !locked && c.status === 'WAITING_EXTERNAL' && <button className="sm" onClick={() => workflow('IN_REVIEW', { note: 'חזר מגורם חוץ' })}>חזרה לבדיקה</button>}
              {can('case.lock') && !locked && <button className="sm primary" disabled={pending > 0} title={pending ? `${pending} ממצאים ממתינים להחלטה` : ''} onClick={() => workflow('LOCK')}>אישור ונעילת גרסה</button>}
              {locked && <span className="chip ok">נעול — גרסה {c.locked_version}</span>}
            </div>
          </div>
          {report.run.ai_summary && <details className="ai-sum"><summary>סיכום אוטומטי וקטעי ידע</summary><div className="notice info small">
            <div style={{ whiteSpace: 'pre-line' }}>{report.run.ai_summary}</div>
            {(report.run.kb_passages ?? []).length > 0 && <div style={{ marginTop: 6 }}>
              <b>קטעי ידע שנמסרו לסיכום</b> (מהתכניות והנחיות הוועדה של התיק; לעיון — אינם ממצאים):
              {[...(report.run.kb_passages ?? [])].sort((a, b) => Number(b.cited) - Number(a.cited)).map(k => (
                <div key={k.id}><span className="mono">[{k.id}]</span> {k.section} — {k.source_title_he}{k.page ? `, עמ׳ ${k.page}` : ''}
                  {k.cited && <span className="chip ok" style={{ marginInlineStart: 4 }}>צוטט בסיכום</span>}
                  {k.url && <> · <a href={k.url} target="_blank" rel="noreferrer">מקור</a></>}</div>))}
            </div>}</div></details>}
        </div>
      )}

      <div className="workspace">
        <section className="card" aria-label="תשריט">
          <div className="card-head"><h3>תצוגת תשריט ושכבות</h3><span className="spacer" /><span className="small muted">לחיצה על סימון אדום/צהוב מציגה את הממצא</span></div>
          {!geoLoading && !(geo?.features?.length) && sheetFile
            ? <SheetViewer file={sheetFile} />
            : <CadViewer geo={geo} loading={geoLoading} findings={report?.findings ?? []} selected={sel} onSelect={id => { setSel(id); setTab('findings') }} />}
          {report && <Measurements m={report.measurements} />}
        </section>

        <section className="card" aria-label="ממצאים ונתונים">
          <div className="tabs" role="tablist">
            <button className={tab === 'findings' ? 'active' : ''} onClick={() => setTab('findings')}>ממצאים <span className="count num">{findings.length}</span></button>
            <button className={tab === 'files' ? 'active' : ''} onClick={() => setTab('files')}>קבצים <span className="count num">{c.files?.length ?? 0}</span></button>
            <button className={tab === 'data' ? 'active' : ''} onClick={() => setTab('data')}>נתוני התיק</button>
            <button className={tab === 'extracted' ? 'active' : ''} onClick={() => setTab('extracted')}>נתונים מחולצים</button>
            <button className={tab === 'history' ? 'active' : ''} onClick={() => setTab('history')}>גרסאות</button>
            <button className={tab === 'decision' ? 'active' : ''} onClick={() => setTab('decision')}>החלטת ועדה</button>
            <button className={tab === 'scope' ? 'active' : ''} onClick={() => setTab('scope')}>תחולה</button>
            <button className={tab === 'accuracy' ? 'active' : ''} onClick={() => setTab('accuracy')}>בקרת דיוק</button>
            <button className={tab === 'revision' ? 'active' : ''} onClick={() => setTab('revision')}>השוואה לגרסה קודמת</button>
            {c.kind !== 'design' && <button className={tab === 'process' ? 'active' : ''} onClick={() => setTab('process')}>תהליך</button>}
            <button className={tab === 'property' ? 'active' : ''} onClick={() => setTab('property')}>נכס</button>
            {c.kind !== 'design' && <button className={tab === 'inspection' ? 'active' : ''} onClick={() => setTab('inspection')}>פיקוח</button>}
          </div>

          {tab === 'findings' && (
            <FindingsPanel c={c} report={report} sel={sel} setSel={setSel}
              onCite={setCite} canDecide={can('finding.decide')} locked={locked} onDecide={decide} />
          )}
          {tab === 'files' && <Files c={c} onChange={reloadFiles} locked={locked} />}
          {tab === 'data' && <CaseData c={c} onChange={load} locked={locked} />}
          {tab === 'extracted' && <Extracted caseId={c.id} />}
          {tab === 'decision' && <DecisionPanel c={c} />}
          {tab === 'scope' && <ScopePanel c={c} />}
          {tab === 'accuracy' && <AccuracyPanel c={c} />}
          {tab === 'revision' && <RevisionPanel c={c} />}
          {tab === 'process' && <ProcessPanel c={c} />}
          {tab === 'property' && <PropertyPanel c={c} />}
          {tab === 'inspection' && <InspectionPanel c={c} />}
          {tab === 'history' && (
            <table>
              <thead><tr><th>גרסה</th><th>מועד</th><th>תוצאות</th><th>Ruleset</th></tr></thead>
              <tbody>{runs.slice().reverse().map(r => (
                <tr key={r.id}><td className="num">{r.version}{r.locked ? ' 🔒' : ''}</td><td>{fmtDate(r.at)}</td>
                  <td className="small">{Object.entries(r.counts ?? {}).map(([rep, cs]: any) => `${rep}: ${Object.entries(cs).map(([k, v]) => `${k} ${v}`).join(', ')}`).join(' | ')}</td>
                  <td className="mono">{r.ruleset_hash.slice(0, 10)}</td></tr>
              ))}</tbody>
            </table>
          )}
        </section>
      </div>
      <SourceDrawer cite={cite} onClose={() => setCite(null)} />
    </>
  )
}

const M_HE: Record<string, string> = {
  plot_area_m2: 'שטח מגרש', existing_footprint_m2: 'תכסית קיימת', proposed_addition_area_m2: 'שטח תוספת מוצעת',
  balcony_area_m2: 'שטח מרפסת', sukkah_area_m2: 'שטח סוכה', roof_room_area_m2: 'שטח חדר גג',
  roof_room_front_setback_m: 'נסיגת חדר גג מחזית שפת הגג', proposed_to_plot_boundary_m: 'מרחק תוספת מגבול מגרש',
  sukkah_to_plot_boundary_m: 'מרחק סוכה מגבול מגרש', proposed_outside_building_line_m2: 'שטח תוספת מחוץ לקו בניין',
  balcony_outside_building_line_m2: 'שטח מרפסת מחוץ לקו בניין',
}

function Measurements({ m }: { m: Record<string, any> }) {
  const rows = Object.values(m).filter((x: any) => x.value !== null)
  if (!rows.length) return null
  return (
    <div style={{ marginTop: 12 }}>
      <h3>מדידות דטרמיניסטיות</h3>
      <div className="table-wrap"><table>
        <thead><tr><th>מדידה</th><th>ערך</th><th>יחידות</th><th>שיטה</th></tr></thead>
        <tbody>{rows.map((x: any) => (
          <tr key={x.key}><td>{M_HE[x.key] ?? x.key}</td><td className="num"><b>{fmt(x.value)}</b></td>
            <td>{x.units === 'm2' ? 'מ״ר' : 'מ׳'}</td><td className="small mono">{x.method}</td></tr>
        ))}</tbody>
      </table></div>
    </div>
  )
}

function Files({ c, onChange, locked }: { c: Case; onChange: () => Promise<void>; locked: boolean }) {
  const { meta, can, toast } = useApp()
  const [docType, setDocType] = useState('architectural_plan')
  const [units, setUnits] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const lifecycle = async (fileId: string, state: string) => {
    const msg = state === 'DELETED'
      ? 'מחיקה מבוקרת: הקובץ יימחק לצמיתות מהשרת (הרישום וה־hash נשמרים ביומן). נימוק:'
      : state === 'ARCHIVED' ? 'העברה לארכיון (הקובץ לא ייכלל בבדיקות). נימוק:' : 'שחזור מהארכיון. נימוק:'
    const note = window.prompt(msg)
    if (!note || note.trim().length < 3) return
    try { await api.post(`/api/files/${fileId}/lifecycle`, { state, note }); toast('עודכן — יש להריץ בדיקה מחדש'); await onChange() }
    catch (e: any) { toast(e.message, true) }
  }
  const upload = async () => {
    if (!file) return
    const fd = new FormData()
    fd.append('file', file); fd.append('doc_type', docType)
    if (units) fd.append('declared_units_m', units)
    setBusy(true)
    try { await api.upload(`/api/cases/${c.id}/files`, fd); toast('הקובץ נקלט'); setFile(null); await onChange() }
    catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }
  const classify = async () => {
    setBusy(true)
    try {
      const r = await api.post<any>(`/api/cases/${c.id}/classify-documents`)
      toast(`סיווג ${r.documents} מסמכים ב-AI מקומי התחיל; הדוח יתעדכן בסיומו`)
      await onChange()
    } catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }
  return (
    <>
      {can('case.run') && !locked && (
        <div className="row" style={{ marginBottom: 8 }}>
          <button className="sm" disabled={busy} onClick={classify}>{busy ? 'מסווג…' : 'סיווג מסמכים (AI מקומי)'}</button>
        </div>
      )}
      {can('case.upload') && !locked && (
        <div className="card" style={{ background: 'var(--surface-2)', boxShadow: 'none' }}>
          <h3>העלאת קובץ (PDF / DXF / DWG / Excel)</h3>
          <div className="form-grid">
            <label className="field">קובץ<input type="file" accept=".pdf,.dxf,.dwg,.xlsx,.xlsm" onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
            <label className="field">סוג מסמך<select value={docType} onChange={e => setDocType(e.target.value)}>
              {Object.entries(meta.doc_types).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label className="field">יחידות שרטוט (מ׳ ליחידה, רק אם חסר בקובץ)<input value={units} onChange={e => setUnits(e.target.value)} placeholder="למשל 0.001" inputMode="decimal" /></label>
          </div>
          <div style={{ marginTop: 10 }}><button className="primary" disabled={!file || busy} onClick={upload}>{busy ? 'קולט…' : 'העלאה וקליטה'}</button>
            <span className="small muted" style={{ marginInlineStart: 10 }}>הקבצים נשמרים מקומית; SHA-256, זיהוי כפילויות וגרסאות. סריקת וירוסים: ClamAV אם מותקן.</span></div>
        </div>
      )}
      <div className="table-wrap" style={{ marginTop: 10 }}>
        <table>
          <thead><tr><th>קובץ</th><th>סוג</th><th>קליטה</th><th>פרטים</th><th>מצב</th></tr></thead>
          <tbody>
            {(c.files ?? []).map(f => (
              <tr key={f.id} style={f.lifecycle !== 'ACTIVE' ? { opacity: 0.55 } : undefined}>
                <td><span className="ltr">{f.filename}</span><div className="small muted">גרסה <span className="num">{f.version}</span> · <span className="mono">{f.sha256.slice(0, 12)}</span></div></td>
                <td>{meta.doc_types[f.doc_type] ?? f.doc_type}
                  {f.suggested_doc_type && f.suggested_doc_type !== f.doc_type && <div className="small" style={{ color: 'var(--unc)' }}>סיווג AI מציע: {meta.doc_types[f.suggested_doc_type]}</div>}</td>
                <td><span className={'chip ' + (f.ingest_status === 'OK' ? 'ok' : 'warn')}>{INGEST_HE[f.ingest_status] ?? f.ingest_status}</span>
                  <div className="small muted">AV: {f.av_status === 'NOT_SCANNED' ? 'לא נסרק' : f.av_status}</div></td>
                <td className="small">
                  {f.kind === 'dxf' && <>יחידות: <span className="ltr">{f.ingest_report.units}</span> · ישויות <span className="num">{f.ingest_report.entity_count}</span>
                    {f.ingest_report.unmapped_layers?.length ? <> · שכבות לא ממופות: <span className="ltr">{f.ingest_report.unmapped_layers.join(', ')}</span></> : null}</>}
                  {(f.kind === 'pdf' || f.kind === 'dwfx') && f.ingest_report.page_count != null && <>{f.kind === 'dwfx' ? 'גיליונות' : 'עמודים'} <span className="num">{f.ingest_report.page_count}</span>{f.kind === 'pdf' && <> · חתימה: {f.signature_status === 'NO_SIGNATURE_FIELD' ? 'אין שדה חתימה' : 'שדה חתימה קיים (לא אומת)'}</>}</>}
                  {f.kind === 'xlsx' && <>שורות <span className="num">{f.ingest_report.row_count}</span> · מוצע עיקרי <span className="num">{f.ingest_report.totals_m2?.proposed_main_m2}</span> מ״ר</>}
                  {(f.ingest_report.warnings ?? []).map((w: string, i: number) => <div key={i} style={{ color: 'var(--unc)' }}>{w}</div>)}
                </td>
                <td className="small">
                  <span className={'chip ' + (f.lifecycle === 'ACTIVE' ? 'ok' : f.lifecycle === 'ARCHIVED' ? 'outline' : 'bad')}>{LIFECYCLE_HE[f.lifecycle] ?? f.lifecycle}</span>
                  {!locked && f.lifecycle !== 'DELETED' && (
                    <div style={{ display: 'flex', gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
                      {can('case.upload') && f.lifecycle === 'ACTIVE' && <button className="sm" onClick={() => lifecycle(f.id, 'ARCHIVED')}>לארכיון</button>}
                      {can('case.upload') && f.lifecycle === 'ARCHIVED' && <button className="sm" onClick={() => lifecycle(f.id, 'ACTIVE')}>שחזור</button>}
                      {can('file.delete') && <button className="sm danger" onClick={() => lifecycle(f.id, 'DELETED')}>מחיקה</button>}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function CaseData({ c, onChange, locked }: { c: Case; onChange: () => Promise<void>; locked: boolean }) {
  const { meta, can, toast } = useApp()
  const [zone, setZone] = useState(c.zone ?? '')
  const [plans, setPlans] = useState(c.applicable_plans.join(', '))
  const [declared, setDeclared] = useState(JSON.stringify(c.declared, null, 2))
  const save = async () => {
    let d
    try { d = JSON.parse(declared) } catch { toast('JSON לא תקין בנתונים המוצהרים', true); return }
    try {
      await api.patch(`/api/cases/${c.id}`, { zone: zone || null, applicable_plans: plans.split(',').map(s => s.trim()).filter(Boolean), declared: d })
      toast('נשמר — יש להריץ בדיקה מחדש'); await onChange()
    } catch (e: any) { toast(e.message, true) }
  }
  const editable = can('case.upload') && !locked
  return (
    <>
      <div className="notice small" style={{ marginBottom: 10 }}>
        תכניות חלות ואזור ייעוד מוזנים כרגע ידנית. בשלב ב׳ יגיעו מ־GIS עירוני (ממשק מתוכנן, אינו מחובר).
      </div>
      <div className="form-grid">
        <label className="field">אזור מגורים<select value={zone} disabled={!editable} onChange={e => setZone(e.target.value)}>
          <option value="">— לא ידוע —</option>{Object.entries(meta.zones).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field">תכניות חלות (מופרד בפסיק)<input value={plans} disabled={!editable} onChange={e => setPlans(e.target.value)} /></label>
        <label className="field">מסלול<input value={meta.tracks[c.track]} disabled /></label>
      </div>
      <label className="field" style={{ marginTop: 12 }}>נתונים מוצהרים מהבקשה (JSON)
        <textarea dir="ltr" rows={10} value={declared} disabled={!editable} onChange={e => setDeclared(e.target.value)} className="mono" /></label>
      {editable && <button className="primary" style={{ marginTop: 10 }} onClick={save}>שמירה</button>}
    </>
  )
}


const FIELD_HE: Record<string, string> = {
  application_number: 'מספר בקשה', building_file_number: 'תיק בניין', address: 'כתובת', gush: 'גוש', helka: 'חלקה',
  zone: 'יעוד', plot_area_m2: 'שטח מגרש (מ״ר)', application_type: 'סוג בקשה (כנוסחו)', permit_type: 'סוג בקשה (סיווג)',
  description: 'מהות הבקשה', applicable_plans: 'תוכניות חלות', deviations: 'הקלות שפורסמו',
}
const OUTCOME_HE2: Record<string, string> = {
  approved: 'אושר', approved_with_conditions: 'אושר בתנאים / בהערות', renewed: 'חידוש אישור',
  objection_partially_accepted: 'התנגדות התקבלה בחלקה — אושר בתנאים', objection_rejected: 'התנגדות נדחתה — אושר',
  deferred: 'הדיון נדחה', rejected: 'נדחה', other: 'אחר — נדרש עיון',
}

function Extracted({ caseId }: { caseId: string }) {
  const { meta } = useApp()
  const [d, setD] = useState<any>(null)
  useEffect(() => { api.get(`/api/cases/${caseId}/extracted`).then(setD) }, [caseId])
  if (!d) return <div className="empty">טוען…</div>
  if (!d.fields.length && !d.comments.length && !d.decisions.length)
    return <div className="empty">לתיק זה אין נתונים מחולצים (התיק לא נקלט מקבצים).</div>
  const src = (s: any) => s ? (
    <button className="link-btn" title={`${s.method} · ${s.quote ?? ''}`}
      onClick={() => s.file_id && s.page && openBlob(`/api/files/${s.file_id}/page/${s.page}.png`)}>
      {s.file} · עמ׳ {s.page ?? '—'}{s.original_page ? ` (מקור ${s.original_page})` : ''}
    </button>) : <span className="muted">—</span>
  const byDept: Record<string, any[]> = {}
  d.comments.forEach((x: any) => { (byDept[x.department_he] ??= []).push(x) })
  return (
    <>
      <p className="small muted" style={{ marginTop: 0 }}>ערכים שחולצו אוטומטית מהמסמכים — לכל ערך מקור (קובץ ועמוד). ערכים בוודאות נמוכה מסומנים "נדרש אימות".</p>
      <div className="table-wrap"><table className="compact">
        <thead><tr><th>שדה</th><th>ערך</th><th>ודאות</th><th>מקור</th></tr></thead>
        <tbody>{d.fields.map((f: any, i: number) => (
          <tr key={i}><td className="small">{FIELD_HE[f.field] ?? f.field}</td>
            <td>{f.field === 'permit_type' ? (meta.permit_types[f.value] ?? f.value) : String(f.value)}
              {f.status === 'edited' && <div className="small muted">נערך ידנית · במקור: {String(f.original_value ?? '—')}</div>}</td>
            <td><span className={'chip ' + (f.confidence >= 0.8 ? 'ok' : 'warn')}>{f.confidence >= 0.8 ? `${Math.round(f.confidence * 100)}%` : 'נדרש אימות'}</span></td>
            <td className="small">{src(f.source)}</td></tr>))}</tbody>
      </table></div>
      {d.areas.length > 0 && (<>
        <h3 style={{ marginTop: 14 }}>שטחים <span className="chip warn">נדרש אימות</span></h3>
        <table className="compact"><thead><tr><th>קומה</th><th>מצב</th><th>שימוש</th><th>מ״ר</th></tr></thead>
          <tbody>{d.areas.slice(0, 60).map((a: any, i: number) => <tr key={i}><td>{a.value.floor ?? '—'}</td><td>{a.value.status === 'existing' ? 'קיים' : a.value.status === 'proposed' ? 'מוצע' : '—'}</td><td>{a.value.label}</td><td className="num">{a.value.value_m2}</td></tr>)}</tbody></table>
      </>)}
      {d.comments.length > 0 && (<>
        <h3 style={{ marginTop: 14 }}>הערות הוועדה וגורמי המקצוע</h3>
        {Object.entries(byDept).map(([dept, list]) => (
          <div className="dept" key={dept}><div className="dept-head">{dept} <span className="small muted">({list.length})</span> {src(list[0].source)}</div>
            <ol className="comments">{list.map((x, i) => <li key={i}>{x.item_no && <span className="num item-no">{x.item_no}.</span>} {x.text}</li>)}</ol></div>))}
      </>)}
      {d.decisions.map((x: any, i: number) => (
        <section key={i} className="decision-box" style={{ marginTop: 14 }}>
          <h3>החלטת הוועדה <span className="chip outline">{OUTCOME_HE2[x.outcome] ?? x.outcome}</span></h3>
          <p>{x.text}</p>
          {x.conditions.length > 0 && <ol>{x.conditions.map((c: string, j: number) => <li key={j}>{c}</li>)}</ol>}
          <div className="small muted">ישיבה <span className="num">{x.meeting_number ?? '—'}</span> · {x.meeting_date ?? '—'} · {src(x.source)}</div>
        </section>))}
    </>
  )
}
