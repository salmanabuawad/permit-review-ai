# Permit360 — verified product facts for website content

Source of truth for every claim on the public website. Verified against the Permit360 code and the live
system on 27.11.2026. Anything not listed here must not be claimed. Items marked PLANNED must be presented
as planned, never as available.

## Brand
- Product: **Permit360 by Kortex Digital** (company: Kortex Digital Ltd, https://kortexd.com).
- Website and application share one address: https://permit360.kortexd.com — website pages under /he/ /ar/ /en/ /ru/,
  application sign-in at /login.
- Two editions: **Permit360 Pro** (engineers, architects, practical engineers, property owners / permit applicants)
  and **Permit360 Authority** (local and regional planning and building committees).
- Market: Israel. Interface languages: Hebrew, English, Arabic, Russian.
- Core message (Hebrew original): "מערכת חכמה להכנה, בדיקה ובקרה של בקשות להיתר בנייה בישראל." /
  "לא מחכים לוועדה כדי לגלות טעויות." — find problems before the committee does.
- Status: in active development and in use; functions below exist unless marked PLANNED. No customer names,
  no numbers of customers, no testimonials, no accuracy percentages, no time-saving percentages.

## Permit360 Pro (implemented)
1. **Committee discovery by block and parcel (gush / helka)** — the registered parcel boundary (Survey of Israel
   cadastre, about 1.1 million parcels) is intersected with the official planning-area boundaries published by the
   Planning Administration (all 131 local and regional committees in the national register are linked by their
   planning-area codes). Result: the responsible committee, or — when the parcel crosses more than one planning
   area — the candidate committees with each one's share of the parcel; the user chooses and the project is marked
   "not verified". The committee is never guessed from a locality name or a plan number. When no official boundary
   answers (parcel not in the cadastre), the user may choose manually; the project is marked "unresolved".
2. **Alternative path:** choose the committee from the national committee directory, and the system verifies the
   parcel is inside that committee's planning area (or reports a mismatch).
3. **Planning information for the plot:** applicable plans found through XPLAN (the Planning Administration's plan
   system) on the registered parcel — whether a plan covers the whole parcel or part of it, status, publication;
   land-use designations; restrictions such as section 77–78 notices and deposited plans; what is still missing.
4. **Building rights:** computed for the plot when the rights table / plan provisions are available; otherwise the
   system says what is missing (it does not invent numbers).
5. **AI engineering assistant:** answers questions using only the project's planning package and the committee's
   own published documents (guidelines, procedures, plans fetched from committee websites); every answer lists its
   sources; numbers not found in the sources are rejected. It runs on a local language model. Not a professional
   determination.
6. **Request wizard:** property → committee (from official boundaries) → request type and purpose → planning
   information → documents (PDF, DWG, DXF, XLSX) → summary and applicant declaration → submission with a
   confirmation number (format P360-<year>-<6 digits>), also e-mailed. When the committee works in Permit360, the
   request opens directly as a case in the committee's workspace with its documents; otherwise the user is told the
   committee is not connected yet and must also file in Rishuy Zamin (the national online permit system).
   Each step is saved; the wizard can be resumed.
7. **Pre-submission check:** the same rule engine committees use runs on the user's draft; readiness score,
   blockers and how to fix them; comparison of design alternatives. Drafts are private to their author.
8. **Self sign-up:** engineers, architects, practical engineers and property owners register, verify their e-mail,
   and are approved before the account opens.

## Permit360 Authority (implemented)
1. **Document intake:** PDF, DWG/DXF, DWFX, Excel and ZIP packages; documents classified by content; data
   extracted with its source (file, page) and confidence; committee protocols split into requests; repeated imports
   do not create duplicates.
2. **Rule engine with evidence:** deterministic checks (measurements and calculations are never done by the AI
   model); each finding cites its source — plan clause, regulation or committee guideline, with page; outcomes:
   complies / does not comply / requires review / not applicable. A rule takes effect only after professional
   approval; rules are versioned with validity dates; checks are re-run on new versions.
3. **CAD and drawings:** geometry from DXF/DWG (layers, areas, setbacks to plot boundaries, building lines),
   measurement uncertainty is carried into the result, findings are marked on the drawing; consistency between the
   drawings and the area tables.
4. **Reviewer decides:** the system recommends; reviewers accept or override each finding with a reason;
   corrections become classified feedback with regression checks; accepting a correction requires a second person
   (four-eyes). Accuracy is measured against reviewers' decisions.
5. **Workflow:** cases, tasks and deadlines, return for completions, waiting for external parties, PDF defects
   report, tamper-evident audit log (hash chain).
6. **Knowledge base:** committee documents fetched on demand from committees' websites; national knowledge
   (laws, regulations, procedures) and committee documents can be uploaded by the platform administrator; hybrid
   search (keyword + local embeddings); a source monitor detects changes in regulatory sources and proposes rule
   drafts — never changing a rule automatically.
7. **Requests submitted from Permit360 Pro** arrive as cases in the committee's workspace with their documents
   and confirmation number.

## Data and sources
- Survey of Israel cadastre (registered parcels); Planning Administration planning-area boundaries; XPLAN plans;
  committee websites; uploaded documents. Spatial data in PostgreSQL / PostGIS.
- Official references (safe to link): Planning Administration licensing steps
  https://www.gov.il/he/pages/steps_licensing_full_permit?chapterIndex=4 ; licensing forms
  https://www.gov.il/he/pages/forms_licensing_process?chapterIndex=2 ; Mavat (national plan information)
  https://mavat.iplan.gov.il
- Laws and regulations (name them; do not quote clause text): Planning and Building Law, 5725-1965;
  Planning and Building Regulations (Building Licensing), 5776-2016; Engineers and Architects Law, 5718-1958
  (licensing of the person who signs the plans).

## Local AI and information security (implemented)
- Language models run on local hardware operated for the platform; case documents are not sent to cloud AI
  services. An AI policy per data type blocks any processing location not allowed for that data; a cloud provider
  would require the authority's written approval (none approved by default).
- AI is used for classification, extraction and drafting; it never decides compliance and never measures.
- Separation between authorities' workspaces; role-based permissions (committee: administrator and reviewer;
  Pro: end users); HttpOnly session cookies; password policy with scrypt hashing; e-mail verification and
  approval for self sign-up; complete audit log.

## PLANNED (say "planned")
- Live interfaces to Rishuy Zamin, municipal GIS, permit systems and archives (today the system works with files).
- OCR for scanned documents without a text layer.

## Never claim
- That Permit360 issues permits or approves anything — the statutory decision belongs to the committee.
- That it replaces the engineer, architect or reviewer.
- Accuracy numbers, time savings, customer counts, partnerships or certifications.
- Integration with Rishuy Zamin (it is planned).
