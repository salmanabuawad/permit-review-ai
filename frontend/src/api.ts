// Thin typed client over the FastAPI backend. POC auth = X-User header (demo user switcher).
export type Status = 'PASS' | 'FAIL' | 'UNCERTAIN' | 'NA'

export interface Citation {
  source_id: string; title_he: string; url: string | null; edition?: string
  page: number | null; section: string | null; verification: string; quote_he?: string
}
export interface Finding {
  id: string; rule_id: string; rule_version: string; report: string
  status: Status; computed_result: Status; severity: string
  title_he: string; explanation_he: string; fix_hint_he: string | null
  measured_value: number | null; measured_uncertainty: number | null; threshold: number | null
  operator: string | null; units: string | null; confidence: number
  citations: Citation[]; evidence: any[]; flags: string[]; overlay_wkt: string | null
  reviewer_decision: string | null; reviewer_note: string | null; reviewer_id: string | null
}
export interface Report {
  kind: string; title_he: string; disclaimer_he: string; case: any
  run: { version: number; at: string; ruleset_hash: string; inputs: any[]; duration_ms: number; locked: boolean; ai_summary: string | null }
  findings: Finding[]; measurements: Record<string, any>
}
export interface CaseFile {
  id: string; filename: string; doc_type: string; kind: string; suggested_doc_type: string | null
  sha256: string; size_bytes: number; version: number; ingest_status: string; ingest_report: any
  av_status: string; signature_status: string; uploaded_at: string; lifecycle: string
}
export interface Case {
  id: string; case_number: string; title: string; is_demo: boolean; permit_type: string; track: string
  stage: string; gush: string | null; helka: string | null; address: string | null; zone: string | null
  applicable_plans: string[]; declared: Record<string, any>; status: string; assigned_to: string | null
  sla_due: string | null; locked_version: number | null; created_at: string
  last_run: null | { id: string; version: number; summary: any; at: string; duration_ms: number; locked: boolean }
  files?: CaseFile[]
}

let currentUser = localStorageGet('bbp_user') || 'u-reviewer'
function localStorageGet(k: string): string | null {
  try { return window.localStorage.getItem(k) } catch { return null }
}
export function setUser(u: string) {
  currentUser = u
  try { window.localStorage.setItem('bbp_user', u) } catch { /* ignore */ }
}
export function getUser() { return currentUser }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function req<T>(method: string, path: string, body?: any, isForm = false): Promise<T> {
  const headers: Record<string, string> = { 'X-User': currentUser }
  if (body && !isForm) headers['Content-Type'] = 'application/json'
  const r = await fetch(path, { method, headers, body: isForm ? body : body ? JSON.stringify(body) : undefined })
  if (!r.ok) {
    let msg = r.statusText
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* */ }
    throw new ApiError(r.status, msg)
  }
  return r.json()
}

export const api = {
  get: <T,>(p: string) => req<T>('GET', p),
  post: <T,>(p: string, b?: any) => req<T>('POST', p, b ?? {}),
  put: <T,>(p: string, b?: any) => req<T>('PUT', p, b),
  patch: <T,>(p: string, b?: any) => req<T>('PATCH', p, b),
  upload: <T,>(p: string, fd: FormData) => req<T>('POST', p, fd, true),
  // binary downloads need the auth header too
  async blob(p: string): Promise<Blob> {
    const r = await fetch(p, { headers: { 'X-User': currentUser } })
    if (!r.ok) throw new ApiError(r.status, r.statusText)
    return r.blob()
  },
}

export async function openBlob(path: string, filename?: string) {
  const b = await api.blob(path)
  const url = URL.createObjectURL(b)
  if (filename) {
    const a = document.createElement('a'); a.href = url; a.download = filename; a.click()
  } else {
    window.open(url, '_blank')
  }
}

export const STATUS_HE: Record<Status, string> = { PASS: 'עומד', FAIL: 'לא עומד', UNCERTAIN: 'דורש בדיקה', NA: 'לא חל' }
export const SEV_HE: Record<string, string> = { high: 'גבוהה', medium: 'בינונית', low: 'נמוכה' }
export const FLAG_HE: Record<string, string> = {
  RULE_NOT_APPROVED: 'כלל טרם אושר מקצועית', INCOMPLETE: 'חסר נתון', THRESHOLD_SOURCE_MISSING: 'ערך סף חסר במקור',
  WITHIN_UNCERTAINTY_BAND: 'בתחום אי-ודאות המדידה', REVIEW_REQUIRED: 'נדרשת הכרעת בודק',
  CONDITION_FOR_PERMIT: 'תנאי למתן היתר', APPLICABILITY_UNKNOWN: 'תחולה לא ידועה', SOURCE_CONFLICT: 'סתירת מקורות',
  DEMO_RULE: 'כלל הדגמה',
}
export const REVIEW_STATE_HE: Record<string, string> = {
  DRAFT: 'טיוטה', SOURCE_MISSING: 'מקור חסר', SOURCE_LOCATED: 'מקור אותר', SOURCE_VERIFIED: 'מקור נקרא ואומת',
  PROFESSIONALLY_APPROVED: 'אושר מקצועית', DESIGN_ASSUMPTION: 'הנחת תכנון', DEMO_FIXTURE: 'הדגמה', RETIRED: 'בוטל',
}
export const VERIFICATION_HE: Record<string, string> = {
  VERIFIED_READ: 'נקרא ואומת', FOUND_NOT_READ: 'אותר — לא נקרא', LISTING_ONLY: 'ברשימה רשמית בלבד',
  NOT_FOUND: 'לא נמצא', DESIGN_ASSUMPTION: 'הנחת תכנון', DEMO: 'הדגמה', UNKNOWN: 'לא ידוע',
}
export const OP_HE: Record<string, string> = { '>=': '≥', '<=': '≤', '>': '>', '<': '<', '==': '=' }
export const fmt = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? '—' : v.toFixed(d))
export const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('he-IL', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
