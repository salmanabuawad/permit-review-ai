import { Fragment, useEffect, useMemo, useState } from 'react'
import { OP_HE, REVIEW_STATE_HE, VERIFICATION_HE, api } from '../api'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../App'
import RuleEditor, { KIND_HE, LEVEL_HE } from '../components/RuleEditor'

const ORIGIN_HE: Record<string, [string, string]> = { file: ['קטלוג', 'outline'], edited: ['נערך', 'warn'], custom: ['כלל חדש', 'ok'] }
const stateChip = (s: string) => s === 'PROFESSIONALLY_APPROVED' ? 'ok' : s === 'DEMO_FIXTURE' ? 'demo' : s === 'SOURCE_VERIFIED' ? 'outline' : 'warn'

export default function Rules() {
  const { can, toast } = useApp()
  const [rules, setRules] = useState<any[]>([])
  const [open, setOpen] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [drafts, setDrafts] = useState(0)
  const nav = useNavigate()
  const [meta, setMeta] = useState<any>(null)
  const [showDeleted, setShowDeleted] = useState(false)
  const [editing, setEditing] = useState<any | null | undefined>(undefined)   // undefined = closed, null = new rule
  const load = () => api.get<any[]>('/api/rules' + (showDeleted ? '?include_deleted=true' : '')).then(setRules)
  useEffect(() => { load() }, [showDeleted])
  useEffect(() => { api.get('/api/rules/meta').then(setMeta) }, [])
  const canEdit = can('rule.edit')
  const remove = async (r: any) => {
    const note = window.prompt(`מחיקת הכלל ${r.id} — הכלל לא ייבדק יותר בהרצות הבאות. נימוק:`)
    if (!note) return
    try { await api.del(`/api/rules/${encodeURIComponent(r.id)}?note=${encodeURIComponent(note)}`); toast('הכלל נמחק (ניתן לשחזר)'); load() }
    catch (e: any) { toast(e.message, true) }
  }
  const restore = async (r: any) => {
    const what = r.origin === 'edited' ? 'החזרה לנוסח הקטלוג' : 'שחזור הכלל'
    const note = window.prompt(`${what} ${r.id} — נימוק:`)
    if (!note) return
    try { await api.post(`/api/rules/${encodeURIComponent(r.id)}/restore`, { rule: {}, note }); toast('הכלל שוחזר'); load() }
    catch (e: any) { toast(e.message, true) }
  }
  useEffect(() => {
    api.get<any>('/api/source-monitor').then(d => setDrafts(d.drafts?.open ?? 0)).catch(() => { /* optional */ })
  }, [])
  const shown = useMemo(() => rules.filter(r => !q || (r.id + r.title_he).includes(q)), [rules, q])
  const approve = async (id: string) => {
    const note = window.prompt('נימוק לאישור הכלל (סעיף/עמוד שנבדק):')
    if (!note) return
    try { await api.post(`/api/rules/${id}/approval`, { note }); toast('הכלל אושר — יחול בהרצות הבאות'); load() }
    catch (e: any) { toast(e.message, true) }
  }
  return (
    <>
      <div className="page-head">
        <div><h1>מאגר כללים</h1><p>כל כלל מקושר למקור, סעיף ועמוד. כלל שלא אושר מקצועית אינו יכול להוביל לפסילה אוטומטית.</p></div>
        <span className="spacer" />
        <label className="small" style={{ display: 'flex', gap: 4, alignItems: 'center' }}><input type="checkbox" checked={showDeleted} onChange={e => setShowDeleted(e.target.checked)} />הצגת כללים שנמחקו</label>
        <input placeholder="חיפוש כלל" value={q} onChange={e => setQ(e.target.value)} />
        {canEdit && meta && <button className="primary" onClick={() => setEditing(null)}>כלל חדש</button>}
        <button onClick={() => nav('/rules/sources')}>סריקת מקורות{drafts ? ` (${drafts} הצעות ממתינות)` : ''}</button>
      </div>
      <div className="notice info small" style={{ marginBottom: 14 }}>
        היררכיית מקורות: חוק ← תקנות ← תכנית סטטוטורית ← הנחיות מרחביות ← מדיניות ← החלטות ועדה. כשכללים חלים סותרים זה את זה, המערכת מציגה "סתירת מקורות" ואינה מכריעה.
        אישור כלל — מהנדס העיר / מנהל אגף בלבד, עם נימוק, ונרשם ביומן הביקורת. כל עריכה יוצרת גרסה חדשה הדורשת אישור מחדש.
      </div>
      <div className="card"><div className="table-wrap"><table>
        <thead><tr><th>כלל</th><th>רמה משפטית</th><th>סוג בדיקה</th><th>תנאי</th><th>מצב אימות</th><th></th></tr></thead>
        <tbody>
          {shown.map(r => (
            <Fragment key={r.id}>
              <tr className="clickable" onClick={() => setOpen(open === r.id ? null : r.id)} style={r.deleted ? { opacity: .55 } : undefined}>
                <td><b>{r.title_he}</b><div className="mono small muted">{r.id} v{r.version}{' '}
                  {r.deleted ? <span className="chip bad">נמחק</span> : ORIGIN_HE[r.origin] && r.origin !== 'file' && <span className={'chip ' + ORIGIN_HE[r.origin][1]}>{ORIGIN_HE[r.origin][0]}</span>}</div></td>
                <td className="small">{LEVEL_HE[r.legal_level] ?? r.legal_level}</td>
                <td className="small">{KIND_HE[r.check.kind] ?? r.check.kind}</td>
                <td className="small num">{r.check.operator ? `${OP_HE[r.check.operator]} ${r.check.threshold ?? (r.check.threshold_by ? 'לפי ' + r.check.threshold_by.label_he : 'חסר במקור')} ${r.check.units ?? ''}` : '—'}</td>
                <td><span className={'chip ' + stateChip(r.review_state)}>{REVIEW_STATE_HE[r.review_state] ?? r.review_state}</span></td>
                <td onClick={e => e.stopPropagation()}><div className="row-actions">
                  {!r.deleted && can('rule.approve') && ['SOURCE_VERIFIED', 'SOURCE_LOCATED', 'DESIGN_ASSUMPTION'].includes(r.review_state) &&
                    <button className="sm" onClick={() => approve(r.id)}>אישור מקצועי</button>}
                  {canEdit && meta && !r.deleted && <button className="sm" onClick={() => setEditing(r)}>עריכה</button>}
                  {canEdit && !r.deleted && <button className="sm" onClick={() => remove(r)}>מחיקה</button>}
                  {canEdit && (r.deleted || r.origin === 'edited') && <button className="sm" onClick={() => restore(r)}>{r.deleted ? 'שחזור' : 'נוסח הקטלוג'}</button>}
                </div></td>
              </tr>
              {open === r.id && (
                <tr><td colSpan={6} style={{ background: 'var(--surface-2)' }}>
                  <dl className="kv">
                    <dt>מקורות</dt><dd>{r.sources_resolved.map((s: any, i: number) => (
                      <div key={i}>{s.source.title_he ?? s.source_id} {s.section ? `· ${s.section}` : ''} {s.page ? `· עמ׳ ${s.page}` : ''} <span className="chip outline">{VERIFICATION_HE[s.source.verification] ?? '—'}</span></div>))}</dd>
                    {r.exact_clause_he && <><dt>נוסח המקור</dt><dd><div className="quote">{r.exact_clause_he}</div></dd></>}
                    <dt>תחולה</dt><dd className="small">
                      {r.permit_types ? 'סוגי בקשה: ' + r.permit_types.join(', ') : 'כל סוגי הבקשות'}
                      {r.stages ? ' · שלבים: ' + r.stages.join(', ') : ''}
                      {r.valid_from ? ` · בתוקף מ־${r.valid_from}` : ''}
                      {r.spatial_scope?.plans ? ' · תכניות: ' + r.spatial_scope.plans.join(', ') : ''}
                      {(r.applicability?.all ?? []).map((c: any, i: number) => <div key={i}>• {c.label_he}</div>)}
                    </dd>
                    {r.check.geometry_method_he && <><dt>שיטת מדידה</dt><dd className="small">{r.check.geometry_method_he}</dd></>}
                    {r.check.threshold_by && <><dt>ספים לפי {r.check.threshold_by.label_he}</dt><dd className="small">{Object.entries(r.check.threshold_by.map).map(([k, v]) => `${k}: ${v}`).join(' · ') || 'לא הוגדר'}</dd></>}
                    {r.notes && <><dt>הערות</dt><dd className="small ltr" style={{ display: 'block', direction: 'ltr', textAlign: 'left' }}>{r.notes}</dd></>}
                    {r.reviewer && <><dt>אושר ע"י</dt><dd>{r.reviewer}</dd></>}
                  </dl>
                </td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table></div></div>
      {editing !== undefined && meta && <RuleEditor rule={editing} meta={meta} onClose={() => setEditing(undefined)}
        onSaved={msg => { toast(msg); setEditing(undefined); load() }} />}
    </>
  )
}
