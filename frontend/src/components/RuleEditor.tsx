import { useEffect, useMemo, useState } from 'react'
import { OP_HE, REVIEW_STATE_HE, api } from '../api'

export const LEVEL_HE: Record<string, string> = {
  STATUTE: 'חוק', REGULATION: 'תקנות', STATUTORY_PLAN: 'תכנית סטטוטורית', SPATIAL_GUIDELINES: 'הנחיות מרחביות',
  MUNICIPAL_POLICY: 'מדיניות מקומית', COMMITTEE_DECISION: 'החלטת ועדה', CASE_INFO: 'מידע לתיק', INTERNAL_QA: 'בקרה פנימית', DEMO: 'הדגמה',
}
export const KIND_HE: Record<string, string> = {
  compare: 'השוואה כמותית', doc_required: 'מסמך נדרש', cad_roles: 'שכבות CAD', any_present: 'אחד מהפריטים קיים',
  declared_bool: 'נתון מוצהר', consistency: 'עקביות בין מסמכים', qualitative: 'איכותני — הכרעת בודק', condition: 'תנאי להיתר',
}
const REPORT_HE: Record<string, string> = { reviewer: 'דוח בודק', rights: 'דוח זכויות', completeness: 'דוח שלמות' }
const SEV_HE: Record<string, string> = { high: 'גבוהה', medium: 'בינונית', low: 'נמוכה' }

type Meta = { legal_levels: string[]; reports: string[]; severities: string[]; check_kinds: Record<string, string[]>;
  operators: string[]; review_states: string[]; permit_types: Record<string, string> }
type Src = { source_id: string; section?: string; page?: number | string; quote_he?: string }

const BLANK = { id: '', title_he: '', legal_level: 'MUNICIPAL_POLICY', report: 'reviewer', severity: 'medium',
  review_state: 'DRAFT', permit_types: [] as string[], check: { kind: 'compare', operator: '<=' }, sources: [] as Src[] }

const pretty = (v: any) => (v && Object.keys(v).length ? JSON.stringify(v, null, 2) : '')
const parseJson = (label: string, text: string) => {
  if (!text.trim()) return undefined
  try { return JSON.parse(text) } catch { throw new Error(`${label}: JSON לא תקין`) }
}

/** Create (rule = null) or edit a rule. Version and approval are set by the server: every save is a new version. */
export default function RuleEditor({ rule, meta, onClose, onSaved }:
  { rule: any | null; meta: Meta; onClose: () => void; onSaved: (msg: string) => void }) {
  const isNew = !rule
  const [r, setR] = useState<any>(() => {
    const base = rule ? structuredClone(rule) : structuredClone(BLANK)
    if (base.review_state === 'PROFESSIONALLY_APPROVED') base.review_state = base.yaml_review_state ?? 'SOURCE_VERIFIED'
    return base
  })
  const [sources, setSources] = useState<any[]>([])
  const [checkJson, setCheckJson] = useState(() => { const { kind, ...rest } = r.check ?? {}; return pretty(rest) })
  const [appJson, setAppJson] = useState(() => pretty(r.applicability))
  const [scopeJson, setScopeJson] = useState(() => pretty(r.spatial_scope))
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.get<any[]>('/api/sources').then(setSources).catch(() => setSources([])) }, [])
  const set = (k: string, v: any) => setR((x: any) => ({ ...x, [k]: v }))
  const setCheck = (k: string, v: any) => setR((x: any) => ({ ...x, check: { ...x.check, [k]: v } }))
  const kind = r.check?.kind ?? 'compare'
  const structured = kind === 'compare'
  const srcIds = useMemo(() => sources.map(s => s.id ?? s.source_id).filter(Boolean), [sources])

  const changeKind = (k: string) => {
    setR((x: any) => ({ ...x, check: k === 'compare' ? { kind: k, operator: '<=' } : { kind: k } }))
    setCheckJson(k === 'compare' ? '' : pretty(Object.fromEntries((meta.check_kinds[k] ?? []).map(f => [f, '']))))
  }
  const setSrc = (i: number, k: string, v: any) => set('sources', r.sources.map((s: Src, j: number) => (j === i ? { ...s, [k]: v } : s)))

  const save = async () => {
    setErr('')
    let rule2: any
    try {
      const check = structured
        ? { ...r.check, threshold: r.check.threshold === '' || r.check.threshold === undefined || r.check.threshold === null
            ? undefined : Number(r.check.threshold) }
        : { kind, ...(parseJson('הגדרות הבדיקה', checkJson) ?? {}) }
      rule2 = { ...r, check, applicability: parseJson('תחולה', appJson), spatial_scope: parseJson('תחולה מרחבית', scopeJson),
        sources: (r.sources ?? []).filter((s: Src) => s.source_id).map((s: Src) => ({ ...s, page: s.page === '' || s.page == null ? undefined : Number(s.page) })),
        stages: typeof r.stages === 'string' ? r.stages.split(',').map((x: string) => x.trim()).filter(Boolean) : r.stages }
    } catch (e: any) { setErr(e.message); return }
    setBusy(true)
    try {
      const res: any = isNew ? await api.post('/api/rules', { rule: rule2, note })
        : await api.put(`/api/rules/${encodeURIComponent(r.id)}`, { rule: rule2, note })
      onSaved(isNew ? `הכלל ${res.id} נוצר (גרסה ${res.version})` : `הכלל עודכן לגרסה ${res.version} — נדרש אישור מקצועי מחדש`)
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <>
      <div className="drawer-back" onClick={onClose} />
      <aside className="drawer drawer-wide" role="dialog" aria-label={isNew ? 'כלל חדש' : 'עריכת כלל'}>
        <div className="card-head"><h2>{isNew ? 'כלל חדש' : `עריכת כלל ${r.id}`}</h2><span className="spacer" /><button onClick={onClose}>סגירה</button></div>
        {!isNew && <div className="notice info small" style={{ marginBottom: 12 }}>
          גרסה נוכחית {rule.version}{rule.origin === 'file' ? ' (מהקטלוג)' : rule.origin === 'edited' ? ` (נערך; בקטלוג ${rule.file_version})` : ''}.
          השמירה יוצרת גרסה חדשה; אישור מקצועי של גרסה קודמת אינו עובר אליה.</div>}

        <h3>פרטי הכלל</h3>
        <div className="form-grid">
          <label className="field">מזהה<input dir="ltr" value={r.id} disabled={!isNew} placeholder="BB-POL26-EXAMPLE"
            onChange={e => set('id', e.target.value.toUpperCase())} /></label>
          <label className="field">כותרת<input value={r.title_he} onChange={e => set('title_he', e.target.value)} /></label>
          <label className="field">רמה משפטית<select value={r.legal_level} onChange={e => set('legal_level', e.target.value)}>
            {meta.legal_levels.map(l => <option key={l} value={l}>{LEVEL_HE[l] ?? l}</option>)}</select></label>
          <label className="field">דוח<select value={r.report ?? 'reviewer'} onChange={e => set('report', e.target.value)}>
            {meta.reports.map(x => <option key={x} value={x}>{REPORT_HE[x] ?? x}</option>)}</select></label>
          <label className="field">חומרה<select value={r.severity ?? 'medium'} onChange={e => set('severity', e.target.value)}>
            {meta.severities.map(x => <option key={x} value={x}>{SEV_HE[x] ?? x}</option>)}</select></label>
          <label className="field">מצב אימות<select value={r.review_state} onChange={e => set('review_state', e.target.value)}>
            {meta.review_states.map(x => <option key={x} value={x}>{REVIEW_STATE_HE[x] ?? x}</option>)}</select></label>
          <label className="field">בתוקף מ־<input type="date" value={r.valid_from ?? ''} onChange={e => set('valid_from', e.target.value)} /></label>
          <label className="field">בתוקף עד<input type="date" value={r.valid_to ?? ''} onChange={e => set('valid_to', e.target.value)} /></label>
        </div>
        <div className="field" style={{ marginTop: 10 }}>סוגי בקשה (ריק = כולם)
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', marginTop: 4 }}>
            {Object.entries(meta.permit_types).map(([k, v]) => (
              <label key={k} className="small" style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                <input type="checkbox" checked={(r.permit_types ?? []).includes(k)}
                  onChange={e => set('permit_types', e.target.checked ? [...(r.permit_types ?? []), k] : (r.permit_types ?? []).filter((x: string) => x !== k))} />{v}</label>))}
          </div></div>

        <h3 style={{ marginTop: 16 }}>הבדיקה</h3>
        <div className="form-grid">
          <label className="field">סוג בדיקה<select value={kind} onChange={e => changeKind(e.target.value)}>
            {Object.keys(meta.check_kinds).map(k => <option key={k} value={k}>{KIND_HE[k] ?? k}</option>)}</select></label>
          {structured && <>
            <label className="field">נתון נבדק (operand)<input dir="ltr" value={r.check.operand ?? ''} placeholder="measure.roof_room_front_setback_m"
              onChange={e => setCheck('operand', e.target.value)} /></label>
            <label className="field">תיאור הנתון<input value={r.check.operand_label_he ?? ''} onChange={e => setCheck('operand_label_he', e.target.value)} /></label>
            <label className="field">תנאי<select value={r.check.operator} onChange={e => setCheck('operator', e.target.value)}>
              {meta.operators.map(o => <option key={o} value={o}>{OP_HE[o] ?? o}</option>)}</select></label>
            <label className="field">ערך סף (ריק = חסר במקור)<input type="number" step="any" dir="ltr" value={r.check.threshold ?? ''}
              onChange={e => setCheck('threshold', e.target.value)} disabled={!!r.check.threshold_by} /></label>
            <label className="field">יחידות<input value={r.check.units ?? ''} onChange={e => setCheck('units', e.target.value)} /></label>
            <label className="field" style={{ gridColumn: '1 / -1' }}>שיטת מדידה<input value={r.check.geometry_method_he ?? ''}
              onChange={e => setCheck('geometry_method_he', e.target.value)} /></label>
          </>}
        </div>
        {structured && r.check.threshold_by && <p className="small muted">ערך הסף נקבע לפי {r.check.threshold_by.label_he ?? r.check.threshold_by.fact} — {Object.entries(r.check.threshold_by.map ?? {}).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>}
        {!structured && <label className="field" style={{ marginTop: 8 }}>הגדרות הבדיקה (JSON) — שדות חובה: {(meta.check_kinds[kind] ?? []).join(', ') || 'אין'}
          <textarea dir="ltr" rows={6} className="mono small" value={checkJson} onChange={e => setCheckJson(e.target.value)} /></label>}
        <label className="field" style={{ marginTop: 8 }}>תנאי תחולה (JSON, רשות) — {'{"all": [{"fact": "case.track", "op": "eq", "value": "...", "label_he": "..."}]}'}
          <textarea dir="ltr" rows={4} className="mono small" value={appJson} onChange={e => setAppJson(e.target.value)} /></label>
        <label className="field" style={{ marginTop: 8 }}>תחולה מרחבית (JSON, רשות) — {'{"plans": ["בב/105/ג"]}'}
          <textarea dir="ltr" rows={2} className="mono small" value={scopeJson} onChange={e => setScopeJson(e.target.value)} /></label>

        <h3 style={{ marginTop: 16 }}>מקורות</h3>
        {(r.sources ?? []).map((s: Src, i: number) => (
          <div key={i} className="src-row">
            <label className="field">מקור<select value={s.source_id} onChange={e => setSrc(i, 'source_id', e.target.value)}>
              <option value="">—</option>
              {[...new Set([s.source_id, ...srcIds].filter(Boolean))].map(id => <option key={id} value={id}>{sources.find(x => (x.id ?? x.source_id) === id)?.title_he ?? id}</option>)}
            </select></label>
            <label className="field">סעיף<input value={s.section ?? ''} onChange={e => setSrc(i, 'section', e.target.value)} /></label>
            <label className="field">עמוד<input type="number" dir="ltr" value={s.page ?? ''} onChange={e => setSrc(i, 'page', e.target.value)} /></label>
            <label className="field src-quote">ציטוט מהמקור<input value={s.quote_he ?? ''} onChange={e => setSrc(i, 'quote_he', e.target.value)} /></label>
            <button className="sm" onClick={() => set('sources', r.sources.filter((_: Src, j: number) => j !== i))}>הסרה</button>
          </div>))}
        <button className="sm" onClick={() => set('sources', [...(r.sources ?? []), { source_id: '' }])}>הוספת מקור</button>

        <h3 style={{ marginTop: 16 }}>נוסח והנחיות</h3>
        <label className="field">נוסח המקור (כפי שנקרא במקור)<textarea rows={3} value={r.exact_clause_he ?? ''} onChange={e => set('exact_clause_he', e.target.value)} /></label>
        <label className="field">הנחיה לתיקון<textarea rows={2} value={r.fix_hint_he ?? ''} onChange={e => set('fix_hint_he', e.target.value)} /></label>
        <label className="field">הערות<textarea rows={2} value={r.notes ?? ''} onChange={e => set('notes', e.target.value)} /></label>

        <div className="card" style={{ marginTop: 16 }}>
          <label className="field">נימוק לשינוי (נרשם ביומן הביקורת)<input value={note} onChange={e => setNote(e.target.value)} /></label>
          {err && <div className="notice bad small" style={{ marginTop: 8 }}>{err}</div>}
          <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
            <button className="primary" disabled={busy || note.trim().length < 3} onClick={save}>{busy ? 'שומר…' : isNew ? 'יצירת כלל' : 'שמירת גרסה חדשה'}</button>
            <button onClick={onClose}>ביטול</button>
          </div>
        </div>
      </aside>
    </>
  )
}
