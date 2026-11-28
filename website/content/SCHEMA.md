# Content file schema — website/content/<lang>.json

One JSON object per language (he, ar, en, ru). All values are plain text (no HTML, no Markdown), except where
noted. `{n}` placeholders must be kept. Lengths are limits, not targets.

```jsonc
{
  "meta": {
    "home_title": "≤ 60 chars — must contain 'Permit360'",
    "home_description": "120–155 chars",
    "og_locale": "he_IL | ar_IL | en_IL | ru_IL"
  },
  "ui": {
    "skip": "Skip to content", "menu": "Menu", "close": "Close", "language": "Language",
    "signin": "Sign in", "register": "Register / Start", "request_demo": "Request a demo",
    "nav_product": "Product", "nav_pro": "Permit360 Pro label", "nav_authority": "Permit360 Authority label",
    "nav_guides": "Guides / Knowledge", "nav_contact": "Contact",
    "read_more": "Read more", "back_home": "Back to home", "on_this_page": "On this page",
    "sources": "Official sources", "related": "Related pages", "faq": "Questions and answers",
    "simulated": "Simulation badge (e.g. 'Illustration')", "live": "Live badge (e.g. 'Live data')",
    "planned": "Planned badge"
  },
  "home": {
    "eyebrow": "short line above H1",
    "h1": "first line of H1", "h1_accent": "second line of H1 (highlighted)",
    "lead": "2–3 sentences",
    "cta_primary": "button (to registration)", "cta_secondary": "button (to demo)",
    "proof": ["4 short factual chips, e.g. '131 planning committees linked to official boundaries'"],
    "pro":       { "label": "Permit360 Pro", "title": "...", "text": "2 sentences", "bullets": ["4–5 items"] },
    "authority": { "label": "Permit360 Authority", "title": "...", "text": "2 sentences", "bullets": ["4–5 items"] },
    "advantage": { "title": "the core message: find problems before the committee does", "text": "1–2 sentences" },
    "lookup": {
      "title": "Find the responsible committee", "text": "1–2 sentences: real lookup on official data",
      "gush": "Block (gush)", "helka": "Parcel (helka)", "button": "Find committee", "checking": "Checking…",
      "resolved": "Responsible committee", "ambiguous": "The parcel crosses {n} planning areas",
      "not_found": "parcel not in registered cadastre / no official answer — explanation",
      "unlinked": "planning area without a linked committee — explanation",
      "invalid": "digits only", "error": "service unavailable, try later", "rate": "too many lookups, wait a minute",
      "share": "of the parcel", "area": "Planning area", "code": "Code", "district": "District",
      "locality": "Locality", "parcel_area": "Registered parcel area", "sqm": "m²",
      "note": "1 sentence: result from official boundaries; open a project in Permit360 Pro to continue",
      "continue": "Continue in Permit360 Pro"
    },
    "demo": {
      "title": "...", "text": "1–2 sentences, say clearly it is an illustration with example data",
      "tab_pro": "Permit360 Pro", "tab_authority": "Permit360 Authority",
      "steps_pro": [ {"title": "...", "text": "1–2 sentences"} ],        // exactly 6, in this order:
      // identify property · discover committee · understand building rights · ask the AI engineering assistant ·
      // prepare the application · validate before submission
      "steps_authority": [ {"title": "...", "text": "1–2 sentences"} ],  // exactly 6:
      // receive application · identify applicable regulations · analyze drawings · verify measurements ·
      // evidence-backed findings · track corrections
      "prev": "Previous", "next": "Next", "step": "Step {n} of 6"
    },
    "stages": { "title": "...", "text": "...", "source": "...", "source_url": "gov.il", "p360": "Permit360", "outside": "...",
                "role": {"pro": "...", "authority": "...", "both": "..."},
                "items": [ {"n": "0".."7", "title": "official stage name", "time": "official deadline or ''",
                            "text": "what happens (Planning Administration guide)", "help": "Permit360's part ('' when none)",
                            "role": "pro|authority|both|none"} ] },  // 8 items: planning information + the 7 official stages
    "principles": { "title": "...", "items": [ {"title": "...", "text": "1–2 sentences"} ] }, // 4: evidence, people decide, local AI, Israeli data
    "faq": [ {"q": "...", "a": "2–3 sentences"} ],  // 6
    "contact": { "title": "...", "text": "1–2 sentences" }
  },
  "form": {
    "title": "...", "name": "Full name", "organization": "Organization / office", "role": "I am…",
    "roles": { "engineer": "...", "architect": "...", "committee": "...", "owner": "...", "other": "..." },
    "email": "...", "phone": "Phone (optional)", "message": "Message (optional)",
    "consent": "consent to be contacted about Permit360 and to processing of these details for that purpose only",
    "submit": "...", "sending": "...", "ok": "thank-you message", "error": "...", "rate": "...", "required": "..."
  },
  "pages": {                     // exactly these 9 slugs
    "building-permit-preparation": PAGE,
    "building-permit-review":      PAGE,
    "engineers-architects":        PAGE,
    "planning-committees":         PAGE,
    "building-rights":             PAGE,
    "committee-lookup":            PAGE,   // committee discovery by block and parcel
    "planning-regulations":        PAGE,   // Israeli planning regulations
    "cad-gis":                     PAGE,
    "local-ai-security":           PAGE
  },
  "footer": { "tagline": "...", "status": "1 sentence honest status", "product": "Product", "guides": "Guides",
              "company": "Company", "privacy": "1 sentence: what the contact form stores / sends" },
  "llms_summary": "4–6 sentences describing Permit360 factually for AI systems"
}
```

PAGE:
```jsonc
{
  "nav": "short menu label (≤ 28 chars)",
  "title": "≤ 60 chars, includes the main search phrase for this page in this language",
  "description": "120–155 chars",
  "h1": "...",
  "lead": "2–3 sentences answering the searcher's question directly",
  "sections": [ { "h2": "...", "paragraphs": ["2–4 sentences each"], "bullets": ["optional"] } ],  // 3–5 sections
  "faq": [ { "q": "...", "a": "2–3 sentences" } ],   // 2–4
  "sources": [ { "label": "...", "url": "only URLs listed in FACTS.md" } ]  // 0–3
}
```
Total per page: 350–600 words. Write for professionals. Every product claim must be in FACTS.md; general
explanations of the Israeli permit process must be accurate and conservative (name the law / regulations, do
not quote clause numbers you are not sure of, do not give legal advice).
