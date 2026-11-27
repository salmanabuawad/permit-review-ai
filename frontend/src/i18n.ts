/** App-wide languages: Hebrew (source), English, Arabic, Russian.
 *
 * The interface is written in Hebrew. For another language the page loads /i18n/<lang>.json — a dictionary keyed by
 * the Hebrew text — and a translator swaps every Hebrew text node and the placeholder / title / aria-label / alt
 * attributes as React renders them (a MutationObserver runs before paint, so nothing flickers). Server messages and
 * labels that reach the page are translated the same way. Text inside .notranslate / [translate=no], form fields
 * and user data that is not in the dictionary stay as they are. Keys may contain {0}, {1}… for interpolated parts.
 * The language lives in localStorage ("p360-lang", shared with the landing page); switching reloads the page. */
export type Lang = 'he' | 'en' | 'ar' | 'ru'
export const LANGS: Record<Lang, { name: string; dir: 'rtl' | 'ltr' }> = {
  he: { name: 'עברית', dir: 'rtl' }, en: { name: 'English', dir: 'ltr' }, ar: { name: 'العربية', dir: 'rtl' }, ru: { name: 'Русский', dir: 'ltr' },
}
const KEY = 'p360-lang'
const HEB = /[֐-׿]/
const ATTRS = ['placeholder', 'title', 'aria-label', 'alt']
const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'CODE', 'PRE'])

function initial(): Lang {
  const isLang = (x: any): x is Lang => x === 'he' || x === 'en' || x === 'ar' || x === 'ru'
  const q = new URLSearchParams(window.location.search).get('lang')
  if (isLang(q)) { try { localStorage.setItem(KEY, q) } catch { /* */ } return q }
  try { const s = localStorage.getItem(KEY); if (isLang(s)) return s } catch { /* */ }
  const n = (navigator.language || '').slice(0, 2)
  return isLang(n) ? n : 'he'
}

export const lang: Lang = initial()
export const dir = LANGS[lang].dir

let exact = new Map<string, string>()
let patterns: { re: RegExp; out: string }[] = []
const norm = (s: string) => s.replace(/\s+/g, ' ').trim()
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Translate one Hebrew string (whole text, or a pattern with {n} parts); unknown text is returned unchanged. */
export function tr(text: string): string {
  if (lang === 'he' || !text || !HEB.test(text)) return text
  const k = norm(text)
  const lead = text.match(/^\s*/)![0], trail = text.match(/\s*$/)![0]
  const hit = exact.get(k)
  if (hit !== undefined) return lead + hit + trail
  for (const p of patterns) {
    const m = k.match(p.re)
    if (m) return lead + p.out.replace(/\{(\d+)\}/g, (_, i) => tr(m[+i + 1] ?? '')) + trail
  }
  return text
}

export function setLang(l: Lang) {
  try { localStorage.setItem(KEY, l) } catch { /* */ }
  const u = new URL(window.location.href)
  u.searchParams.delete('lang')
  window.location.assign(u.toString())
}

// ------------------------------------------------------------------ the DOM translator

const done = new WeakMap<Node, string>()            // node → the text we last wrote (so our own writes are ignored)

function textNode(n: Text) {
  const v = n.nodeValue ?? ''
  if (done.get(n) === v || !HEB.test(v)) return
  const p = n.parentElement
  if (!p || SKIP.has(p.tagName) || p.closest('.notranslate,[translate="no"]')) return
  const t = tr(v)
  done.set(n, t)
  if (t !== v) n.nodeValue = t
}

function element(el: Element) {
  if (SKIP.has(el.tagName) || el.closest('.notranslate,[translate="no"]')) return
  for (const a of ATTRS) {
    const v = el.getAttribute(a)
    if (v && HEB.test(v)) { const t = tr(v); if (t !== v) el.setAttribute(a, t) }
  }
}

function walk(root: Node) {
  if (root.nodeType === Node.TEXT_NODE) { textNode(root as Text); return }
  if (root.nodeType !== Node.ELEMENT_NODE) return
  element(root as Element)
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT)
  for (let n = w.nextNode(); n; n = w.nextNode()) n.nodeType === Node.TEXT_NODE ? textNode(n as Text) : element(n as Element)
}

/** Load the dictionary and start translating the page. Resolves when ready (immediately for Hebrew). */
export async function startI18n(): Promise<void> {
  document.documentElement.lang = lang
  document.documentElement.dir = dir
  if (lang === 'he') return
  try {
    const r = await fetch(`/i18n/${lang}.json`, { cache: 'no-cache' })
    const d: Record<string, string> = r.ok ? await r.json() : {}
    exact = new Map()
    const pats: { re: RegExp; out: string; len: number }[] = []
    for (const [he, out] of Object.entries(d)) {
      const k = norm(he)
      if (/\{\d+\}/.test(k)) pats.push({ re: new RegExp('^' + esc(k).replace(/\\\{(\d+)\\\}/g, '(.+?)') + '$'), out, len: k.length })
      else exact.set(k, out)
    }
    patterns = pats.sort((a, b) => b.len - a.len)
  } catch { /* stay in Hebrew text, but with the chosen direction */ }
  const c = window.confirm.bind(window), pr = window.prompt.bind(window), al = window.alert.bind(window)
  window.confirm = (m?: string) => c(tr(m ?? ''))                   // native dialogs bypass the DOM
  window.prompt = (m?: string, d?: string) => pr(tr(m ?? ''), d)
  window.alert = (m?: any) => al(typeof m === 'string' ? tr(m) : m)
  walk(document.documentElement)
  new MutationObserver(ms => {
    for (const m of ms) {
      if (m.type === 'characterData') textNode(m.target as Text)
      else if (m.type === 'attributes') element(m.target as Element)
      else m.addedNodes.forEach(walk)
    }
  }).observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS })
}
