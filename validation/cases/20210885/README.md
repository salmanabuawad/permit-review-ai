# Blind regression case 20210885 (Be'er Ganim, lot 1652, block 3155 parcel 148)

Inputs the engine may use — what the applicant submitted, as the committee register publishes it, and the GIS
planning panel: `register_facts.json`, `gis.json`. No status, decision, requirement sheet or reviewer comment.

Not available publicly: the 2021 drawings, basement plan, area tables per floor, survey and proposed ±0.00 level
(held in Rishui Zamin behind the applicant's login; see exports/blind_validation/20210885/missing_files.json). The
engine therefore must not confirm a basement or route defect for this case; it must name what is missing.

The committee's decision is in `../../ground_truth/20210885.yaml` and is read only by `scripts/evaluate_blind.py`,
after the engine's result is written.
