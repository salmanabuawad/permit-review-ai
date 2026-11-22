import { Fragment, useEffect, useMemo, useState } from 'react'
import { OP_HE, REVIEW_STATE_HE, VERIFICATION_HE, api } from '../api'
import { useApp } from '../App'

const LEVEL_HE: Record<string, string> = {
  STATUTE: 'חוק', REGULATION: 'תקנות', STATUTORY_PLAN: 'תכנית סטטוטורית', SPATIAL_GUIDELINES: 'הנחיות מרחביות',
  MUNICIPAL_POLICY: 'מדיניות מקומית', COMMITTEE_DECISION: 'החלטת ועדה', INTERNAL_QA: 'בקרה פנימית', DEMO: 'הדגמה',
}
const KIND_HE: Record<string, string> = { compare: 'השוואה כמותית', doc_required: 'מסמך נדרש', cad_roles: 'שכבות CAD', declared_bool: 'נתון מוצהר', consistency: 'עקביות בין מסמכים', qualitative: 'איכותני — הכרעת בודק', condition: 'תנאי להיתר' }
const stateChip = (s: string) => s === 'PROFESSIONALLY_APPROVED' ? 'ok' : s === 'DEMO_FIXTURE' ? 'demo' : s === 'SOURCE_VERIFIED' ? 'outline' : 'warn'

export default function Rules() {
  const { can, toast } = useApp()
  const [rules, setRules] = useState<any[]>([])
  const [open, setOpen] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const load = () => api.get<any[]>('/api/rules').then(setRules)
  useEffect(() => { load() }, [])
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
        <span className="spacer" /><input placeholder="חיפוש כלל" value={q} onChange={e => setQ(e.target.value)} />
      </div>
      <div className="notice info small" style={{ marginBottom: 14 }}>
        היררכיית מקורות: חוק ← תקנות ← תכנית סטטוטורית ← הנחיות מרחביות ← מדיניות ← החלטות ועדה. כשכללים חלים סותרים זה את זה, המערכת מציגה "סתירת מקורות" ואינה מכריעה.
        אישור כלל — מהנדס העיר / מנהל אגף בלבד, עם נימוק, ונרשם ביומן הביקורת.
      </div>
      <div className="card"><div className="table-wrap"><table>
        <thead><tr><th>כלל</th><th>רמה משפטית</th><th>סוג בדיקה</th><th>תנאי</th><th>מצב אימות</th><th></th></tr></thead>
        <tbody>
          {shown.map(r => (
            <Fragment key={r.id}>
              <tr className="clickable" onClick={() => setOpen(open === r.id ? null : r.id)}>
                <td><b>{r.title_he}</b><div className="mono small muted">{r.id} v{r.version}</div></td>
                <td className="small">{LEVEL_HE[r.legal_level] ?? r.legal_level}</td>
                <td className="small">{KIND_HE[r.check.kind]}</td>
                <td className="small num">{r.check.operator ? `${OP_HE[r.check.operator]} ${r.check.threshold ?? (r.check.threshold_by ? 'לפי ' + r.check.threshold_by.label_he : 'חסר במקור')} ${r.check.units ?? ''}` : '—'}</td>
                <td><span className={'chip ' + stateChip(r.review_state)}>{REVIEW_STATE_HE[r.review_state] ?? r.review_state}</span></td>
                <td onClick={e => e.stopPropagation()}>
                  {can('rule.approve') && ['SOURCE_VERIFIED', 'SOURCE_LOCATED', 'DESIGN_ASSUMPTION'].includes(r.review_state) &&
                    <button className="sm" onClick={() => approve(r.id)}>אישור מקצועי</button>}
                </td>
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
    </>
  )
}
