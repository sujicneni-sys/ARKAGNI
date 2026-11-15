# Conflict register (Phase 0)

Every conflict found before implementation. Status values:

- **OPEN** - requires a decision before the affected component is built.
- **DEFERRED** - decision depends on a later phase's measured evidence.
- **RESOLVED_BY_DATA** - the conflict was tested against the frozen inputs.

Do not "resolve" a conflict by editing source documents or data.

| ID | Topic | Source A | Source B | Conflict | Status / action |
|---|---|---|---|---|---|
| C-01 | Served model identity | S3 v8: model H is served; S2 §7.3: "Identify H as the currently served model" | S1: `-> PR chosen in v9`; seven models B0..PR with PR selected by pre-registered LOYO | Which model is the operational artifact: H or PR? | **OPEN**. Build both in L4/L5; do not freeze a served model until the selection is re-run on regenerated pairs and the owner signs off. |
| C-02 | Audit endpoint | S1: `/harmonize /validity /version /health` | S3 §Endpoints and S2 §tech stack: `GET /audit` | `/validity` vs `/audit`; possibly the same payload | **OPEN**. Prefer S1 `/validity`, and add `/audit` as an alias only if the payload is identical. |
| C-03 | Presentation scope | S1: "4 panels + limitations footer" | S2: seven pages (Overview, Data Explorer, Harmonization, Uncertainty, Model Comparison, Audit & Validation, Live Analysis) | Four-panel dashboard vs seven-page application | **OPEN**. S1 governs the scientific figure set; S2 governs the application. A seven-page shell can host the four required panels, but this must be confirmed. |
| C-04 | Zero-FRP classification | S2 §4: 267 zero-FRP rows "flagged/excluded"; data has 267 zero-FRP rows | ZIP `reports/cleaning_audit.csv`: `invalid_frp_flagged=0`; Phase 0 measured `quality_flag_invalid_frp=True` count = 0 | Report says zero invalid FRP; UI spec and data say 267 zero-FRP rows exist | **RESOLVED_BY_DATA (defect)**. Both facts are true: 267 rows have `frp_mw=0`, and none are flagged invalid. L1 must define zero FRP as a validity flag and regenerate the audit from that rule. |
| C-05 | Time padding | S1: times are zero-padded first; `118` means `01:18` | Phase 0 measured 177,449 master rows (12.83%) with 1-3 digit `acquisition_time_utc` | Documented invariant is violated by the supplied master file | **RESOLVED_BY_DATA (defect)**. Normalize in L1; preserve raw bytes and report the count. |
| C-06 | Pair count | S3 and S1: 6,313 Aqua-SNPP pairs | Recovered prototype (reference only, not in project): 6,347 daytime pairs | 34-pair divergence | **DEFERRED to L2**. Regenerate pairing from data; the reproduced number becomes the record. Do not copy either value. |
| C-07 | Conformal coverage | S3/S2/S1: overall 0.816, 2-3.5 h bin 0.604 (n=53) | Recovered prototype: overall 0.8447, includes 2-sample calibration bins | Served coverage claims differ | **DEFERRED to L5**. Recompute from regenerated pairs with explicit low-sample policy. |
| C-08 | API contract | S1: columnar JSON request/response, vectorised batch | S2 and recovered prototype: single observation form / single-record payload | Batch-native vs per-record API | **OPEN**. Implement the columnar contract; add a single-record adapter only as a thin boundary. |
| C-09 | Version precedence | S1 (target v9/v10) | S3 (v8 measured) and S2 (H served) | Later architecture changes the selected model and adds `/validity` | **OPEN**. S1 is the architecture target; model identity remains C-01. |
| C-10 | CSV vs JSONL authority | Master CSV stores HHMM as a string | Master JSONL stores the same field as a number | Same logical dataset, different time encoding | **DEFERRED to L1**. Prove row-level equivalence, then declare one authority and a canonical typed form. |
| C-11 | Build prerequisites | S3 restore guide requires Python 3.12, Docker, git | Environment currently has `uv` and project Python 3.12 only; no Docker or git | Cannot reproduce the documented compose/git steps as written | **OPEN (environment)**. Phase 0 uses a project-local venv via `uv`; Docker/CI arrive with the deployment phase. |
| C-12 | Regional pair shares | S1: Southern Africa 62.9%, Amazon 28.5%, Australia 6.8%, California 1.9% | Arithmetic in the same sentence | Shares sum to 100.1% | **PARTIALLY_RESOLVED**. Phase 0 verified row share (Southern Africa 74.59%). Pair shares await L2; recompute exact shares and rounding, report both. |
| C-13 | Prototype status | S3/S1 build tables claim built core/audit | No source, tests, artifacts or lockfile exist in the project; a static HTML mockup hardcodes statistics | Documentation status contradicts repository contents | **RESOLVED (process)**. Clean rebuild; documents are specification, not evidence of working code. |
| C-14 | Git commit in `/version` | S1: `/version` returns git commit | Project is not a git repository and git is not installed | Version endpoint cannot report a commit today | **DEFERRED to L6/deployment**. Report `unknown` explicitly until a repository exists. |
| C-15 | Which layer `data_hash` identifies | S1: `data_hash` covers the three per-file hashes, in a section describing 3 cleaned CSVs | Phase 0: cleaned-file hash reproduces `37423f49...`; raw-file hash is `cf50b9f3...` | The documented anchor does not identify the raw FIRMS inputs | **OPEN before L1**. Decide whether supplied cleaned CSVs are the frozen L1 product with reproducible rules, or regenerate and declare a new L1 hash. |
