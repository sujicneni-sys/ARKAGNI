# Specification index and precedence (Phase 0)

This project is rebuilt from the supplied documents and data. No prior
implementation is treated as current. The documents below are the
specification; where they disagree, the conflict register records the
disagreement and its status.

## Source documents

| ID | Document | Role | Apparent version / status |
|---|---|---|---|
| S1 | `final system architecture.docx` | Governing architecture: L1-L7, serving, audit, deployment, backup | Target v9/v10; mixes `[BUILT]`, `[PROTOTYPED]`, `[TO BUILD]` |
| S2 | `layoutnew.docx` | Seven-page product and UI specification, including scientific wording rules | Design specification; references a served model H |
| S3 | `PyroHarmonize_v8_Architecture.docx` | Prior architecture with measured v8 results and a build status table | Historical v8; explicitly superseded in parts by S1 |
| S4 | `Implication Architecture.docx` | Scientific and operational implications, risks, backup expectations | Narrative companion |
| S5 | `FireSync_MODIS_VIIRS Harmonization System.docx` | Problem definition and research requirements | Requirements |
| S6 | `NASA SPACE APPS CHALLENGE 2026 Problem Statement.docx` | Challenge requirements | Requirements |

Derived reference copies of the extracted text are under
`C:\Users\cneni\AppData\Local\Temp\opencode\pyro_docs\` and are not part of the
repository. The `.docx` originals remain untouched in the project root.

## Proposed precedence

1. **S1 governs architecture and interfaces** where it is explicit, because it
   is the newest architectural document and defines the rebuild target.
2. **S2 governs presentation and scientific wording**, except where it asserts
   a served model identity or backend endpoint that S1 contradicts. Those are
   escalated in the conflict register, not silently resolved.
3. **S3 is evidence of v8 behaviour, not a target.** Its measured numbers
   (6,313 pairs, coverage 0.816, 177 refusals) are claims to reproduce or
   disprove from data.
4. **S4-S6 constrain scientific honesty and scope**; they do not define
   implementation details.
5. **No document outranks verified data.** Every numeric claim is recomputed
   from the frozen inputs. A document that disagrees with the data is recorded
   as a conflict, not "fixed" by editing the data.

## Non-negotiable specification rules extracted from S1/S2

- Raw inputs are read-only; every output is a function of a recorded hash.
- `data_hash` = SHA-256 of the three per-file digests concatenated in order
  MODIS, SNPP, NOAA-20.
- Times are HHMM UTC and must be zero-padded before parsing (`118` -> `01:18`).
- `harmonize()` is pure and vectorised: no file reads, network, clock or
  per-row Python.
- The applicability gate refuses unsupported cells; it never silently assumes
  they are fine. Saturation, plume and canopy states are `not_evaluated`.
- The dashboard reads only hashed results and never recomputes science.
- Never fabricate missing outputs; show a labelled unavailable state.
