import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../App'

interface Src { file: string; page: number | null; method: string; confidence: number }
interface DFile { ref: string; name: string; kind: string; size: number; doc_type: string; doc_type_source: string }
interface Draft { key: string; origin: string; fields: Record<string, any>; sources: Record<string, Src>; files: DFile[]; warnings: string[] }
interface EditDraft extends Draft { include: boolean; fileInclude: Record<string, boolean> }

const FIELDS: { key: string; label: string; dir?: 'ltr' }[] = [
  { key: 'case_number', label: 'מספר בקשה', dir: 'ltr' },
  { key: 'title', label: 'נושא' },
  { key: 'gush', label: 'גוש', dir: 'ltr' },
  { key: 'helka', label: 'חלקה', dir: 'ltr' },
  { key: 'address', label: 'כתובת' },
  { key: 'applicable_plans', label: 'תכניות חלות (מופרד בפסיק)' },
  { key: 'survey_map_date', label: 'תאריך מפת מדידה', dir: 'ltr' },
]

function srcText(s?: Src) {
  if (!s) return 'הוזן ידנית / לא נמצא'
  return `מקור: ${s.file}${s.page ? ` · עמ׳ ${s.page}` : ''} · ${s.method} · ודאות ${Math.round(s.confidence * 100)}%`
}

export default function ImportCases() {
  const { meta, can, toast } = useApp()
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [token, setToken] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<EditDraft[]>([])
  const [warnings, setWarnings] = useState<string[]>([])
  const [runChecks, setRunChecks] = useState(true)
  const [created, setCreated] = useState<any[] | null>(null)

  if (!can('case.create')) return <div className="notice">ייבוא בקשות זמין למזכירות, לבודקים, למנהל האגף ולמנהל המערכת.</div>

  const analyze = async () => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    setBusy(true); setCreated(null)
    try {
      const r = await api.upload<any>('/api/import/analyze', fd)
      setToken(r.token); setWarnings(r.warnings)
      setDrafts(r.drafts.map((d: Draft) => ({
        ...d, include: true,
        fields: { ...d.fields, applicable_plans: (d.fields.applicable_plans ?? []).join(', ') },
        fileInclude: Object.fromEntries(d.files.map(f => [f.ref, true])),
      })))
      toast(`נמצאו ${r.drafts.length} בקשות — יש לבדוק את הפרטים לפני היצירה`)
    } catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }

  const setField = (key: string, field: string, value: any) =>
    setDrafts(ds => ds.map(d => d.key === key ? { ...d, fields: { ...d.fields, [field]: value } } : d))
  const setDocType = (key: string, ref: string, doc_type: string) =>
    setDrafts(ds => ds.map(d => d.key === key ? { ...d, files: d.files.map(f => f.ref === ref ? { ...f, doc_type } : f) } : d))

  const commit = async () => {
    setBusy(true)
    try {
      const requests = drafts.map(d => ({
        key: d.key, include: d.include,
        fields: { ...d.fields, applicable_plans: String(d.fields.applicable_plans ?? '').split(',').map(s => s.trim()).filter(Boolean) },
        files: d.files.map(f => ({ ref: f.ref, doc_type: f.doc_type, include: d.fileInclude[f.ref] })),
      }))
      const r = await api.post<any>('/api/import/commit', { token, requests, run_checks: runChecks })
      setCreated(r.created); setDrafts([]); setToken(null); setFiles([])
      toast(`נוצרו ${r.created.length} תיקים`)
    } catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }

  const selected = drafts.filter(d => d.include)
  const missingType = selected.some(d => !d.fields.permit_type)

  return (
    <>
      <div className="page-head">
        <div>
          <div className="small muted"><Link to="/cases">תיקי בקשות</Link> ‹ ייבוא</div>
          <h1>ייבוא בקשות מקבצים</h1>
          <p>העלו קבצים המכילים בקשה אחת או יותר. המערכת מזהה את הבקשות וממלאת את פרטיהן — התיקים נוצרים רק לאחר אישורכם.</p>
        </div>
      </div>

      <div className="card">
        <h3>1. בחירת קבצים</h3>
        <div className="notice info small" style={{ marginBottom: 12 }}>
          נתמכים: <b>ZIP</b> עם תיקייה לכל בקשה (ואופציונלית רשימת בקשות Excel/CSV בשורש) ·
          <b> רשימת בקשות</b> Excel/CSV (מספר בקשה, נושא, סוג בקשה, גוש, חלקה, כתובת, תכניות, תיקייה) ·
          <b> PDF</b> עם כמה טפסי בקשה — יפוצל אוטומטית · קבצי PDF/DXF/DWG/Excel בודדים — בקשה אחת.
          פרטי המבקש (שם, ת.ז.) אינם מחולצים.
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <input type="file" multiple accept=".zip,.pdf,.xlsx,.xlsm,.csv,.dxf,.dwg" aria-label="קבצים לייבוא"
            onChange={e => setFiles(Array.from(e.target.files ?? []))} />
          <button className="primary" disabled={!files.length || busy} onClick={analyze}>{busy && !drafts.length ? 'מנתח…' : 'ניתוח הקבצים'}</button>
          {files.length > 0 && <span className="small muted">{files.length} קבצים נבחרו</span>}
        </div>
      </div>

      {warnings.length > 0 && <div className="notice" style={{ marginTop: 14 }}>{warnings.map((w, i) => <div key={i}>{w}</div>)}</div>}

      {drafts.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h3>2. בדיקת הבקשות שזוהו (<span className="num">{drafts.length}</span>)</h3>
            <span className="spacer" />
            <span className="small muted">שדות שמולאו אוטומטית מסומנים ברקע; יש לוודא אותם מול המסמך</span>
          </div>
          {drafts.map((d, i) => (
            <div key={d.key} className="finding" style={{ borderInlineStartColor: d.include ? 'var(--brand-2)' : 'var(--line)', opacity: d.include ? 1 : 0.55, marginTop: i ? 12 : 0 }}>
              <div className="row1" style={{ alignItems: 'center' }}>
                <input type="checkbox" checked={d.include} aria-label="לכלול בייבוא"
                  onChange={e => setDrafts(ds => ds.map(x => x.key === d.key ? { ...x, include: e.target.checked } : x))} />
                <div className="title">בקשה <span className="num">{i + 1}</span> <span className="small muted">· {d.origin}</span></div>
                <select value={d.fields.permit_type ?? ''} aria-label="סוג בקשה"
                  style={!d.fields.permit_type ? { borderColor: 'var(--fail)' } : undefined}
                  onChange={e => setField(d.key, 'permit_type', e.target.value || null)}>
                  <option value="">— סוג בקשה —</option>
                  {Object.entries(meta.permit_types).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
              <div className="small muted" style={{ margin: '2px 0 8px' }}>סוג הבקשה: {srcText(d.sources.permit_type)}</div>
              <div className="form-grid">
                {FIELDS.map(f => (
                  <label key={f.key} className="field" title={srcText(d.sources[f.key])}>
                    {f.label}
                    <input dir={f.dir} value={d.fields[f.key] ?? ''} onChange={e => setField(d.key, f.key, e.target.value)}
                      style={d.sources[f.key] ? { background: '#f3f9fc' } : undefined}
                      placeholder={f.key === 'case_number' ? 'יוקצה מספר זמני' : f.key === 'survey_map_date' ? 'YYYY-MM-DD' : ''} />
                    <span className="small muted" style={{ fontWeight: 400 }}>{d.sources[f.key] ? srcText(d.sources[f.key]) : '—'}</span>
                  </label>
                ))}
              </div>
              <div className="table-wrap" style={{ marginTop: 10 }}>
                <table>
                  <thead><tr><th></th><th>קובץ</th><th>סוג מסמך</th><th>זוהה לפי</th></tr></thead>
                  <tbody>{d.files.map(f => (
                    <tr key={f.ref}>
                      <td><input type="checkbox" checked={d.fileInclude[f.ref]} aria-label="לצרף קובץ"
                        onChange={e => setDrafts(ds => ds.map(x => x.key === d.key ? { ...x, fileInclude: { ...x.fileInclude, [f.ref]: e.target.checked } } : x))} /></td>
                      <td><span className="ltr">{f.name}</span> <span className="small muted num">({Math.ceil(f.size / 1024)}KB)</span></td>
                      <td><select value={f.doc_type} onChange={e => setDocType(d.key, f.ref, e.target.value)}
                        style={f.doc_type === 'other' ? { borderColor: 'var(--unc)' } : undefined}>
                        {Object.entries(meta.doc_types).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}</select></td>
                      <td className="small muted">{f.doc_type_source}</td>
                    </tr>))}</tbody>
                </table>
              </div>
              {d.warnings.length > 0 && <div className="flags">{d.warnings.map((w, j) => <span key={j} className="chip warn">{w}</span>)}</div>}
            </div>
          ))}
          <div className="card-head" style={{ marginTop: 16, marginBottom: 0 }}>
            <label className="small" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input type="checkbox" checked={runChecks} onChange={e => setRunChecks(e.target.checked)} /> להריץ בדיקה מיד לאחר יצירת התיקים
            </label>
            <span className="spacer" />
            {missingType && <span className="chip bad">יש לבחור סוג בקשה לכל בקשה שנבחרה</span>}
            <button onClick={() => { setDrafts([]); setToken(null) }}>ביטול</button>
            <button className="primary" disabled={busy || !selected.length || missingType} onClick={commit}>
              {busy ? 'יוצר…' : `3. יצירת ${selected.length} תיקים`}
            </button>
          </div>
        </div>
      )}

      {created && (
        <div className="card">
          <h3>נוצרו <span className="num">{created.length}</span> תיקים</h3>
          <table>
            <thead><tr><th>מספר בקשה</th><th>נושא</th><th>קבצים</th><th>בדיקה</th></tr></thead>
            <tbody>{created.map(c => (
              <tr key={c.id}>
                <td><Link to={`/cases/${c.id}`} className="ltr nowrap">{c.case_number}</Link></td>
                <td>{c.title}</td>
                <td className="small"><span className="num">{c.files}</span>{c.file_errors.length > 0 && <div style={{ color: 'var(--unc)' }}>{c.file_errors.join('; ')}</div>}</td>
                <td className="small">{c.run ? `גרסה ${c.run.version}` : 'לא הורצה'}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </>
  )
}
