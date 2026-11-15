# Phase 0 report - input freeze and provenance

**Status: COMPLETE.** Phase 1 has not started. No scientific pipeline result is
claimed in this report; every number below is a property of the supplied
inputs, measured by `scripts/00_freeze_inputs.py`.

Generated artifacts:

- `artifacts/manifests/phase0_manifest.json`
- `artifacts/reports/csv_jsonl_comparison.json`

## 1. Outcome

- The supplied archive was extracted once into `data/raw/NASA_Fire_Data_Engine`.
- All 20 extracted files were hashed and marked **read-only**.
- The documented `data_hash` was reproduced **exactly** from the three cleaned
  CSVs, proving the provenance anchor.
- The master table has exactly **1,382,752 rows and 33 columns**, matching the
  JSONL line count.
- All four satellite counts and all four region counts were recomputed from the
  master CSV and match the documented values.
- The CSV/JSONL time-encoding difference was measured: **177,449** master rows
  (12.83%) have a non-zero-padded `acquisition_time_utc`.
- **22 tests pass**; they re-hash every frozen file and reject any byte change.
- Five source documents were hashed before work began and re-verified by tests.

## 2. Environment and repository decisions

| Decision | Value | Reason |
|---|---|---|
| D-01 Interpreter | CPython 3.12.16, project-local `.venv` via `uv 0.13.7` | No system Python; the spec requires Python 3.12 |
| D-02 Dependencies | Pinned runtime set from the supplied `requirements.txt`; `uv.lock` generated | Reproducibility; only pipeline-required packages installed |
| D-03 Source of truth | Existing DOCX specifications; precedence in `docs/SPEC_INDEX.md` | Owner decision 1 |
| D-04 Prior code | Not restored or imported; deleted copies remain untouched | Owner decision 2 |
| D-05 Raw layout | Archive structure preserved verbatim under `data/raw` | Traceability to archive paths |
| D-06 Immutability | `os.chmod(..., S_IREAD)` on every extracted file | Prevent accidental edits; verified by tests |
| D-07 No canonical dataset yet | CSV/JSONL reconciliation deferred to Phase 1 | Owner decision 3 |
| D-08 Version control | **Not initialized**: `git` is not installed in this environment | Recorded as unresolved issue U-01; no substitute claimed |

`.venv`, `uv.lock`, and `pyproject.toml` are real and reproducible. The
dependency set resolved without substitutions.

## 3. Frozen inputs

| Property | Measured value |
|---|---|
| Source archive | `NASA_SpaceApps_Task2_Completed.zip` |
| Archive size | 203,164,772 bytes |
| Archive SHA-256 | `09aa2c1da7fbb8d030df5dc6faa0b95ba879a1fffd44374d7fd95aa77d2db0b8` |
| File entries | 20 |
| Extracted size | 1,933,126,337 bytes |
| Extraction target | `data/raw/NASA_Fire_Data_Engine/` |
| Immutable | Yes, every file read-only |
| Manifest verification | Passed (sizes, SHA-256, read-only, no extra files) |

The source documents were preserved in place. Their hashes are recorded in the
manifest and re-checked by tests:

| Document | SHA-256 prefix |
|---|---|
| `final system architecture.docx` | `32b6e3a207a5` |
| `FireSync_MODIS_VIIRS Harmonization System.docx` | `bd7f4d3ce5e9` |
| `Implication Architecture.docx` | `effcf46e648c` |
| `layoutnew.docx` | `a77cf0fef7b6` |
| `NASA SPACE APPS CHALLENGE 2026 Problem Statement.docx` | `0bfe0673d929` |

## 4. Dataset verification from actual bytes

Master: `data/processed/NASA_Fire_Harmonized_Master.csv`

| Check | Measured | Expected | Result |
|---|---|---|---|
| Rows | 1,382,752 | 1,382,752 | Match |
| Columns | 33 | 33 | Match |
| JSONL lines | 1,382,752 | 1,382,752 | Match |
| Terra rows | 39,029 | 39,029 | Match |
| Aqua rows | 127,704 | 127,704 | Match |
| SNPP rows ("N") | 545,196 | 545,196 | Match |
| NOAA-20 rows ("N20") | 670,823 | 670,823 | Match |
| Invalid latitude/longitude | 0 | 0 | Match |
| Missing FRP | 0 | 0 | Match |
| Negative FRP | 0 | 0 | Match |
| Zero-FRP rows | **267** | 267 (S2) | Match |
| `quality_flag_invalid_frp = True` | **0** | 0 (ZIP audit) | Does not match the 267 zero-FRP rows; see C-04 |

Raw and cleaned file row counts both sum to 1,382,752, so no rows appear or
disappear between the two stages.

Region rows and shares:

| Region | Rows | Share |
|---|---|---|
| Southern_Africa | 1,031,439 | 74.59% |
| Amazon | 234,554 | 16.96% |
| Australia | 70,137 | 5.07% |
| California | 46,622 | 3.37% |

The documented row share of 74.6% for Southern Africa is reproduced. Pair
shares cannot be checked until L2 exists.

## 5. Data hash: resolved definition

`data_hash = sha256(concat(per-file sha256 hex, order MODIS, SNPP, NOAA-20))`

Measured candidates:

| Candidate | Value |
|---|---|
| Cleaned CSVs in documented order | `37423f49d2235a911caaebbdc660388ed7e775333ae7f224672342720adf8290` |
| Raw CSVs in documented order | `cf50b9f3384cd2d4e6ab1f6ae1d1e89b1c83d8a01f75025911c8bb1b8c1db17e` |

Only the **cleaned** files reproduce the documented hash. This is a material
provenance decision:

- The documented anchor identifies the cleaned L1 output, not the raw FIRMS
  inputs.
- The raw hash is now also recorded, so both layers are traceable.
- If Phase 1 regenerates cleaning and byte output differs, `data_hash` will
  change. Phase 1 must therefore either (a) adopt the supplied cleaned files as
  the frozen L1 product and prove the cleaning rules reproduce them, or
  (b) declare a new L1 hash and keep the documented one as a cross-check.
  **Unresolved issue U-02.**

## 6. CSV vs JSONL reconciliation (measured, not yet resolved)

| Property | CSV | JSONL |
|---|---|---|
| Rows | 1,382,752 | 1,382,752 |
| Columns | 33 | 33 |
| Column sets | Identical | Identical |
| `acquisition_time_utc` storage | string | JSON number (1000/1000 sampled records) |
| Example | `"0118"` | `118` |

Time-format distribution in the master CSV:

| Form | Rows | Share |
|---|---:|---:|
| Zero-padded 4-digit | 1,205,303 | 87.17% |
| 3-digit | 157,193 | 11.37% |
| 2-digit | 15,306 | 1.11% |
| 1-digit | 4,950 | 0.36% |
| Empty | 0 | 0% |
| **Total non-padded** | **177,449** | **12.83%** |

This violates the documented invariant that times are zero-padded before use.
Semantically, `118` is 01:18 UTC, not 11:08; a parser that treats the numeric
form as HHMM without padding would misplace 177,449 observations. Counts and
column sets are equivalent, but row-level equivalence has **not** been proven,
so no canonical dataset is declared. That is Phase 1 work.

## 7. Tests

`22 passed in 4.67s`:

- Provenance units: SHA-256 vectors, order-sensitive data hash, missing-sensor
  refusal, ZIP traversal rejection, JSONL line counting, deterministic JSON.
- Integration: archive hash/size unchanged, all five documents preserved,
  every frozen file re-hashed, all files read-only, no unexpected files.
- Data: master rows/columns, JSONL row count, per-sensor source sums, satellite
  counts, region coverage, documented data hash, measured time-format totals,
  CSV/JSONL report consistency.

No test uses mock data. The integration tests read the real 1.9 GB frozen tree.

## 8. Unresolved issues before Phase 1

| ID | Issue | Impact |
|---|---|---|
| U-01 | `git` is not installed; no repository/history exists | Cannot report a commit hash or enforce review history; install before deployment work |
| U-02 | Documented `data_hash` is the cleaned-file hash, not the raw hash | Phase 1 must choose frozen-cleaned vs regenerated cleaning and document the consequence |
| U-03 | `quality_flag_invalid_frp` is `False`/0 for all 267 zero-FRP rows | L1 must define and implement zero-FRP semantics; C-04 |
| U-04 | 177,449 times are non-padded; JSONL stores numbers | L1 canonical time parsing and row-level CSV/JSONL equivalence |
| U-05 | No canonical authority between CSV and JSONL | L1 must prove equivalence and declare one |
| U-06 | Served model identity (H vs PR) | Blocks L4/L5 freeze; C-01 |
| U-07 | `/validity` vs `/audit` and four panels vs seven pages | Blocks L6/L7 interface freeze; C-02/C-03 |
| U-08 | 6,313 vs 6,347 pair count | L2 must regenerate pairing; C-06 |
| U-09 | Docker and CI prerequisites absent | Deployment phase; C-11 |
| U-10 | No lockfile existed previously | Resolved for the current environment: `uv.lock` is generated and kept in the project |

## 9. Phase gate

Phase 0 is complete because:

- [x] Raw inputs are frozen, read-only, and hashed.
- [x] The documented data hash is reproduced from actual bytes.
- [x] A machine-readable manifest exists and is verified by tests.
- [x] Source documents are preserved and hashed.
- [x] Conflicting document versions and claims are registered before coding.
- [x] CSV/JSONL differences are measured, not assumed.
- [x] No canonical processed dataset is declared prematurely.
- [x] No scientific result, model, or metric is fabricated.

**Phase 1 (L1 canonicalization) has not begun.** It needs owner approval to
proceed and a decision on U-02 (frozen cleaned files vs regenerated cleaning).
