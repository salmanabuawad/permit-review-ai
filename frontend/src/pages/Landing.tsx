import { useEffect, useState } from 'react'

/** Public landing page for signed-out visitors (and search engines): Hebrew, English, Arabic, Russian. */
type Lang = 'he' | 'en' | 'ar' | 'ru'

const T = {
  he: {
    dir: 'rtl', name: 'עברית',
    tag: 'בדיקת היתרי בנייה',
    title: 'מהגוש והחלקה ועד היתר הבנייה — עם המקור לכל ממצא',
    lead: 'KORTEX Permit360 בודקת בקשות להיתר בנייה עבור ועדות לתכנון ובנייה, ומלווה מהנדסים ואדריכלים בהכנת הבקשה — מזיהוי הוועדה המוסמכת ועד מוכנות להגשה.',
    signin: 'כניסה', register: 'הרשמה',
    committees: 'לוועדות לתכנון ובנייה',
    committeesItems: ['בדיקת הבקשה מול התכניות החלות (תב"ע), זכויות הבנייה, קווי הבניין, הגובה ומספר הקומות',
      'כל ממצא מפנה למקור — סעיף בתכנית, בתקנות או בהנחיות הוועדה — והבודק/ת מכריע/ה',
      'תהליך רישוי, משימות וזמני יעד, ויומן ביקורת מלא'],
    pro: 'Permit360 Pro למהנדסים, אדריכלים ובעלי נכסים',
    proItems: ['זיהוי הוועדה המוסמכת לפי גוש וחלקה, מתוך גבולות מרחבי התכנון הרשמיים — בלי ניחוש',
      'התכניות החלות על המגרש, ייעודי קרקע, זכויות בנייה ומגבלות (סעיפים 77–78, תכניות בהפקדה)',
      'עוזר הנדסי שעונה מתוך מסמכי הוועדה עצמה, ומסלול עבודה עד מוכנות להגשה',
      'גם לבעלי נכסים ומבקשי היתר: מה חל על המגרש שלכם, ומה נדרש כדי להגיש'],
    how: 'איך זה עובד', steps: [['גוש וחלקה', 'מזינים את פרטי הנכס'], ['ועדה מוסמכת', 'מזוהה מהגבולות הרשמיים'],
      ['תכניות וזכויות', 'מ-XPLAN ומהמידע התכנוני'], ['מוכנות להגשה', 'מה חסר ומה הצעד הבא']],
    trust: 'עקרונות', trustItems: [['מקור לכל ממצא', 'שום מספר בלי הפניה לסעיף ולמסמך'], ['האדם מחליט', 'המערכת מסייעת; ההחלטה של הוועדה'],
      ['בינה מלאכותית מקומית', 'מסמכי התיקים לא נשלחים לענן'], ['עברית, אנגלית, ערבית ורוסית', 'ממשק בעברית, מידע בארבע שפות']],
    ctaTitle: 'מהנדס/ת, אדריכל/ית או בעל/ת נכס?', ctaText: 'נרשמים, מאמתים את הדוא״ל, ולאחר אישור פותחים פרויקט לפי גוש וחלקה.',
    about: 'אודות',
  },
  en: {
    dir: 'ltr', name: 'English',
    tag: 'Building Permit Review',
    title: 'From block and parcel to building permit — with a source for every finding',
    lead: 'KORTEX Permit360 reviews building-permit applications for Israeli planning and building committees, and guides engineers and architects through preparing them — from finding the responsible committee to submission readiness.',
    signin: 'Sign in', register: 'Register',
    committees: 'For planning and building committees',
    committeesItems: ['Checks the application against the applicable zoning plans (TABA), building rights, building lines, height and floors',
      'Every finding cites its source — a plan clause, a regulation or the committee\'s guidelines — and a reviewer decides',
      'Permit workflow, tasks and deadlines, and a complete audit trail'],
    pro: 'Permit360 Pro for engineers, architects and property owners',
    proItems: ['Finds the responsible committee from block and parcel (gush / helka) using official planning boundaries — never a guess',
      'Applicable plans, land use, building rights and restrictions (section 77–78 notices, deposited plans)',
      'An engineering assistant that answers from the committee\'s own documents, and a guided path to submission',
      'For property owners and permit applicants too: what applies to your plot, and what you need to apply'],
    how: 'How it works', steps: [['Block & parcel', 'Enter the property'], ['Responsible committee', 'From the official boundaries'],
      ['Plans & rights', 'From XPLAN and planning data'], ['Ready to submit', 'What is missing, what comes next']],
    trust: 'Principles', trustItems: [['A source for every finding', 'No number without a clause and a document'], ['People decide', 'The system assists; the committee decides'],
      ['Local AI', 'Case documents are not sent to the cloud'], ['Hebrew, English, Arabic, Russian', 'Hebrew interface, information in four languages']],
    ctaTitle: 'Engineer, architect or property owner?', ctaText: 'Register, verify your e-mail, and once approved open a project by block and parcel.',
    about: 'About',
  },
  ar: {
    dir: 'rtl', name: 'العربية',
    tag: 'فحص رخص البناء',
    title: 'من الحوض والقسيمة حتى رخصة البناء — مع مصدر لكل نتيجة',
    lead: 'KORTEX Permit360 يفحص طلبات رخص البناء للجان التخطيط والبناء، ويرافق المهندسين والمعماريين في إعداد الطلب — من تحديد اللجنة المختصة حتى الجاهزية للتقديم.',
    signin: 'دخول', register: 'التسجيل',
    committees: 'للجان التخطيط والبناء',
    committeesItems: ['فحص الطلب مقابل المخططات الهيكلية السارية، وحقوق البناء، وخطوط البناء، والارتفاع وعدد الطوابق',
      'كل نتيجة مرفقة بمصدرها — بند في المخطط أو في الأنظمة أو في تعليمات اللجنة — والقرار للمراجِع',
      'مسار الترخيص والمهام والمواعيد، وسجل تدقيق كامل'],
    pro: 'Permit360 Pro للمهندسين والمعماريين وأصحاب العقارات',
    proItems: ['تحديد اللجنة المختصة حسب الحوض والقسيمة من حدود مناطق التخطيط الرسمية — دون تخمين',
      'المخططات السارية على القسيمة، واستعمالات الأرض، وحقوق البناء والقيود',
      'مساعد هندسي يجيب من مستندات اللجنة نفسها، ومسار عمل حتى الجاهزية للتقديم',
      'لأصحاب العقارات وطالبي الرخص أيضًا: ما يسري على قسيمتكم، وما المطلوب للتقديم'],
    how: 'كيف يعمل', steps: [['الحوض والقسيمة', 'إدخال بيانات العقار'], ['اللجنة المختصة', 'من الحدود الرسمية'],
      ['المخططات والحقوق', 'من XPLAN والمعلومات التخطيطية'], ['الجاهزية للتقديم', 'ما الناقص وما الخطوة التالية']],
    trust: 'مبادئ', trustItems: [['مصدر لكل نتيجة', 'لا رقم دون بند ومستند'], ['الإنسان يقرر', 'النظام يساعد؛ القرار للجنة'],
      ['ذكاء اصطناعي محلي', 'مستندات الملفات لا تُرسل إلى السحابة'], ['العبرية والإنجليزية والعربية والروسية', 'واجهة بالعبرية ومعلومات بأربع لغات']],
    ctaTitle: 'مهندس أو معماري أو صاحب عقار؟', ctaText: 'سجّل، أكّد بريدك الإلكتروني، وبعد الموافقة افتح مشروعًا حسب الحوض والقسيمة.',
    about: 'حول',
  },
  ru: {
    dir: 'ltr', name: 'Русский',
    tag: 'Проверка разрешений на строительство',
    title: 'От блока и участка до разрешения на строительство — с источником для каждого вывода',
    lead: 'KORTEX Permit360 проверяет заявки на разрешение на строительство для местных комиссий по планированию и строительству в Израиле и помогает инженерам, архитекторам и владельцам недвижимости подготовить заявку — от определения ответственной комиссии до готовности к подаче.',
    signin: 'Вход', register: 'Регистрация',
    committees: 'Для комиссий по планированию и строительству',
    committeesItems: ['Проверка заявки по действующим градостроительным планам (ТАБА), строительным правам, линиям застройки, высоте и этажности',
      'Каждый вывод ссылается на источник — пункт плана, норматив или указания комиссии, — а решение принимает проверяющий',
      'Процесс выдачи разрешения, задачи и сроки, полный журнал аудита'],
    pro: 'Permit360 Pro для инженеров, архитекторов и владельцев недвижимости',
    proItems: ['Определение ответственной комиссии по блоку и участку (гуш / хелька) по официальным границам районов планирования — без догадок',
      'Действующие планы, назначение земли, строительные права и ограничения (уведомления по статьям 77–78, планы на утверждении)',
      'Инженерный помощник, отвечающий по документам самой комиссии, и пошаговый путь до подачи заявки',
      'Также для владельцев и заявителей: что действует на вашем участке и что нужно для подачи'],
    how: 'Как это работает', steps: [['Блок и участок', 'Введите данные недвижимости'], ['Ответственная комиссия', 'По официальным границам'],
      ['Планы и права', 'Из XPLAN и планировочных данных'], ['Готово к подаче', 'Чего не хватает и что дальше']],
    trust: 'Принципы', trustItems: [['Источник для каждого вывода', 'Ни одной цифры без пункта и документа'], ['Решают люди', 'Система помогает; решение за комиссией'],
      ['Локальный ИИ', 'Документы дел не отправляются в облако'], ['Иврит, английский, арабский, русский', 'Интерфейс на иврите, информация на четырёх языках']],
    ctaTitle: 'Инженер, архитектор или владелец недвижимости?', ctaText: 'Зарегистрируйтесь, подтвердите e-mail и после одобрения откройте проект по блоку и участку.',
    about: 'О системе',
  },
} as const

function initialLang(): Lang {
  const q = new URLSearchParams(window.location.search).get('lang')
  if (q === 'he' || q === 'en' || q === 'ar' || q === 'ru') return q
  try { const s = localStorage.getItem('p360-lang'); if (s === 'he' || s === 'en' || s === 'ar' || s === 'ru') return s } catch { /* */ }
  const n = (navigator.language || '').slice(0, 2)
  return n === 'ar' ? 'ar' : n === 'en' ? 'en' : n === 'ru' ? 'ru' : 'he'
}

export default function Landing() {
  const [lang, setLang] = useState<Lang>(initialLang)
  const t = T[lang]
  useEffect(() => {
    document.documentElement.lang = lang
    document.documentElement.dir = t.dir
    document.title = `KORTEX Permit360 — ${t.tag}`
    try { localStorage.setItem('p360-lang', lang) } catch { /* */ }
  }, [lang, t])

  return (
    <div className="landing" dir={t.dir} lang={lang}>
      <header className="ld-top">
        <div className="ld-brand"><span className="ld-logo" aria-hidden>P</span><b>KORTEX Permit360</b></div>
        <nav className="ld-langs" aria-label="Language">
          {(Object.keys(T) as Lang[]).map(k => <button key={k} className={k === lang ? 'on' : ''} lang={k} onClick={() => setLang(k)}>{T[k].name}</button>)}
        </nav>
        <a className="ld-btn ghost" href="/login">{t.signin}</a>
      </header>

      <section className="ld-hero">
        <div className="ld-tag">{t.tag}</div>
        <h1>{t.title}</h1>
        <p>{t.lead}</p>
        <div className="ld-actions">
          <a className="ld-btn" href="/login?register=1">{t.register}</a>
          <a className="ld-btn ghost" href="/login">{t.signin}</a>
        </div>
      </section>

      <section className="ld-steps" aria-label={t.how}>
        <h2>{t.how}</h2>
        <ol>{t.steps.map(([a, b], i) => <li key={i}><span className="n">{i + 1}</span><b>{a}</b><span>{b}</span></li>)}</ol>
      </section>

      <section className="ld-cards">
        <article><h2>{t.pro}</h2><ul>{t.proItems.map((x, i) => <li key={i}>{x}</li>)}</ul></article>
        <article><h2>{t.committees}</h2><ul>{t.committeesItems.map((x, i) => <li key={i}>{x}</li>)}</ul></article>
      </section>

      <section className="ld-trust" aria-label={t.trust}>
        {t.trustItems.map(([a, b], i) => <div key={i}><b>{a}</b><span>{b}</span></div>)}
      </section>

      <section className="ld-cta">
        <div><h2>{t.ctaTitle}</h2><p>{t.ctaText}</p></div>
        <a className="ld-btn" href="/login?register=1">{t.register}</a>
      </section>

      <footer className="ld-foot">
        <span>KORTEX · <a href="https://kortexd.com/">kortexd.com</a></span>
        <a href="/about.html">{t.about}</a>
      </footer>
    </div>
  )
}
