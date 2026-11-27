# Remaining blockers (2026-11-26)

What is built is in CHANGELOG.md and IMPLEMENTATION_ROADMAP.md. These items cannot be completed by engineering alone
or were deliberately left for a later increment.

| # | Item | Why blocked / open | What unblocks it |
|---|---|---|---|
| 1 | Accuracy figures (defect precision / recall, Recall@K, MRR) | No professionally verified ground truth beyond 1 blind + 1 known-outcome case | Authority experts answer a question set and review ≥ 30 decided cases |
| 2 | Model selection (V11 §34–45) | Benchmark of ≥ 100 Hebrew planning questions must be professionally answered; several candidates not downloaded (DictaLM 24B, Gemma 4 31B, NeoDictaBERT, e5-base/large) | Expert answers; approval to download each model |
| 3 | Official committee codes | Not in the Planning Administration list | An official register (e.g. iplan / data.gov.il) or the Administration |
| 4 | ~~XPLAN plan discovery live~~ — DONE 2026-11-27 (crawler job; verified in all six districts). Registered parcels: DONE 2026-11-27 (Survey of Israel open data, 1.1 M parcels loaded) | Refresh: a person downloads the new snapshot (data.gov.il needs a Google sign-in) and runs scripts/load_cadastre.py |
| 5 | Integrations (רישוי זמין, BarTech, Complot, OneCity, GIS) | No agreed interfaces; public pages only | Agreements with the Planning Administration / vendors |
| 6 | OCR | ≈ 220 fetched documents have no text layer (scanned) | Approve a local OCR engine (Tesseract heb) in the crawler |
| 7 | Clauses for curated YAML passages and uploads | Clause model built for committee sources first | Next increment |
| 8 | Document-level dependencies in the PDG | Post-processing context is coarse (any document change re-evaluates all rules) | Trace which document each post-processing step reads |
| 9 | Construction360 beyond inspections | Mobile app, photogrammetry / LiDAR / point clouds, BIM | Later phase |
| 10 | Backups | Owner declined application-level backups | Confirm the server-level backup policy |
| 11 | English UI | Hebrew RTL only | i18n increment |
| 12 | Haifa / Beit Shemesh requests | Not yet uploaded | Upload in the UI |
