import { LANGS, Lang, lang, setLang } from '../i18n'

/** Interface language for the whole app (he / en / ar / ru); switching reloads the page. */
export default function LangPicker({ className }: { className?: string }) {
  return <select className={'lang-picker notranslate ' + (className ?? '')} aria-label="Language / שפה" value={lang}
    onChange={e => setLang(e.target.value as Lang)}>
    {(Object.keys(LANGS) as Lang[]).map(k => <option key={k} value={k} lang={k}>{LANGS[k].name}</option>)}
  </select>
}
