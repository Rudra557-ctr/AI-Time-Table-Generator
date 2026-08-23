# SIH Smart Timetable Generator — Project Plan

**What it is:** auto-generates a college timetable that satisfies all *hard* rules (no clashes) and optimizes *soft* preferences, for a NEP 2020 multi-programme institution (USAR, GGSIPU — see the real problem statement in `FINAL_PLAN.md` §8). Input = CSV/ZIP/XLSX upload → Output = per-offering `(slot, room, faculty)` assignment + per-section class grids.

**Dataset:** 133 offerings → 370 sessions, 65 courses, 40 faculty, 29 rooms, 35 slots (5 days × 7 periods), 16 sections. Lab-batch mode: 16 labs >40 students → 149 offerings, 386 sessions.

**Solver:** Google OR-Tools CP-SAT. Hard rules = `model.Add(...)` (never violated in a returned solution). Soft preferences = `model.Minimize(sum w_i * penalty_i)` (best-effort within the time budget).

**Last updated:** 2026-08-23.

---

## 1. What's Done

### Core solver — solid, well-tested
`sih_solver/{model,hard,full_model,soft,batches,preprocessing}.py` implement the full constraint model: faculty/room/section/student collision avoidance, synchronized cross-programme electives (the NEP 2020 PCE/OAE piece), equipment/room-type matching with a synonym map, workload caps, fixed-event blocking, and 9 weighted soft-optimization terms (student gaps, workload balance, room wastage, etc.). Lab-batch splitting (`batches.py`) handles oversized labs. Full detail with file:line references lives in `CONSTRAINTS.md` — that file is the source of truth for the constraint model, not this one.

### Solver reliability — hardened and verified with real runs (2026-08-23)
The honest starting point was: a single un-hinted 60s solve on this problem size reliably came back `UNKNOWN` — no timetable at all. Fixed in two pieces, both verified against the actual dataset, not just reviewed:

- **`sih_solver/solve_pipeline.py:solve_hard_then_soft()`** — solves hard-only first (retrying seeds `[0,1,42]`, 150s each), hints that solution into the combined hard+soft model, solves soft (150s). If soft times out, falls back to the valid hard-only schedule instead of returning nothing. **Verified: 3/3 real runs against the full dataset returned a usable schedule, zero `UNKNOWN`** — both the seed-retry and the fallback path fired for real during those runs (95.0–317.1s hard, obj up to 12403 when soft succeeded).
- **`sih_solver/dataset.py:quick_solvability_check()`** — a sub-second pre-check for the specific things that silently break a solve (a course with no eligible faculty gets dropped with no explanation; a missing contiguous slot pair crashes with a bare `ValueError`). Wired into `/api/solve`, returns `422` immediately with the exact problem instead of burning the full time budget. **Verified: 18ms fail with the exact blocker named**, on deliberately broken data.

`backend/app.py` now exposes `hard_time_limit`/`soft_time_limit` params (defaults `150.0`/`150.0`) instead of a single guessed `60s`. `timetables_generated/*.csv` and `FIX_REPORT.md` are regenerated to match (hard `OPTIMAL` 91.6s, soft `FEASIBLE` 153.9s, obj 12287).

### A data-wizard layer was built, then deliberately removed
A 19-dataset schema + L1/L2/L3 validator + per-job JSON store + 16-step wizard frontend got built on top of the solver, then reverted the same day after review found it was built without a single real user, ahead of what this plan actually called for. Two real bugs found while it was live (a substring-matching bug that could delete a user's real uploaded data; a `str`/`Path` crash in `load_all`) were fixed and kept in the simpler, reverted code, since they were bugs in the shared upload/solve path, not the wizard itself. Full story: `FINAL_PLAN.md` §8 and the Decision Log below.

### Hygiene fixes
No more hardcoded absolute paths (6 places fixed, all now resolve relative to `__file__`). `.gitignore` added, tracked `__pycache__`/`.DS_Store` cleaned up. A minimal `X-API-Key` gate on `/api/*` (opt-in via `SIH_API_KEY` env var; unset = open, so local dev is unaffected) for when a URL gets handed to someone outside your machine.

### Frontend design system drafted, build not started
`DESIGN.md` — Industrial/Utilitarian aesthetic, navy/parchment color (deliberately not the generic SaaS-green/cool-gray look, and not TimeEdit's purple-gradient consumer-SaaS style), Cabinet Grotesk/Source Sans 3/IBM Plex Mono, zero border-radius, minimal motion. Proposed and previewed via `/design-consultation`, not yet formally approved. No frontend code exists yet — removed along with the wizard, not yet rebuilt.

### A real, previously-unknown bug found by a synthetic "messy data" test — fixed
Before finding an actual real-world contact, ran a synthetic adversarial test (renamed columns the way a real spreadsheet would be, e.g. `section_id` → "Section Code") through the live API. Found: `adapter.py`'s `normalize_csv` had a hardcoded fallback — any unmapped `section_id` column silently became the literal string `"S_CSE_1_A"` for **every row**, with no error anywhere in the pipeline. Confirmed: uploading the real 16-section dataset with just that one column renamed collapsed all 16 real sections onto one fake ID. A confident wrong answer, not a missing one — worse than a crash. **Fixed:** removed the hardcoded identity-field fallbacks from `adapter.py` (identity fields are now left blank on a failed mapping instead of fabricated); added an identity-column integrity check to `quick_solvability_check` (blank or single-value-collapsed primary keys in `courses`/`sections`/`faculty`/`rooms` → `BLOCKER`). Re-verified against a live server restart: the same broken upload now gets a `422` in milliseconds naming the exact problem, instead of a 250s+ solve on corrupted data.

### A second silent-fallback bug, found by inspection — fixed
Same family of bug as above, different location: `adapter.py:normalize_upload_folder` didn't just fabricate individual fields — if an *entire required CSV* was missing from an upload (e.g. `rooms.csv` never included), it silently copied that file in from the bundled sample dataset and buried the fact in a warning string, so a solve could run to completion on a mix of the user's real data and the repo's demo data with no error. `backend/app.py` had already worked around this at the API layer (regex-parsing that warning string to delete the filler files and re-block the solve when `?fill=true` wasn't passed), but the underlying library function itself still defaulted to silent-fill for any other caller (tests, CLI, future frontend code hitting `adapter.py` directly). **Fixed:** `normalize_upload_folder` now takes `fill_missing=False` by default — a missing required file is reported and left absent (so `quick_solvability_check` blocks the solve on it) unless the caller explicitly opts in. `backend/app.py`'s ~20-line regex-purge workaround was removed and replaced with passing `fill_missing=fill` straight through, since the library now enforces the guarantee itself. Added `tests/test_adapter.py` (2 tests, both passing) covering the default-blocks / opt-in-fills behavior.

### Round 3C: two real hard-constraint bugs found by independent post-solve validation — fixed
Built `sih_solver/validate_output.py` (re-derives HC01,02,03,04,06,07,10,12,13,14,16 straight from a generated CSV + raw input, no shared code with `hard.py`/`full_model.py` — an honest second opinion) and `sih_solver/gap_stats.py` (independent compactness readout: gaps, spans, isolated runs, per section and faculty), specifically to check the solver's own "OPTIMAL" claims rather than trust them. Running the validator against a real "OPTIMAL" hard-only solve found two genuine violations, both the same bug shape: **`add_availability_constraints` (HC06/HC07)** and **`add_fixed_events` (HC14)** each only checked a multi-slot (duration>1) session's *starting* slot's availability/blocked-status, never the rest of the session's occupied span — so a 2-hour lab could be assigned a faculty/room/time that was explicitly unavailable for its second hour, or quietly run through a blocked fixed-event slot, while CP-SAT still reported the solution as satisfying its own (incompletely-specified) model. **Fixed** both, generically for any duration via a new shared helper `preprocessing.occupied_chain_map` (not hardcoded to 2) so this bug class can't recur a third time in a different function. Re-validated from scratch after the fix: 0 violations.

### Round 3C: soft-objective redesign, diagnosed with real numbers, made genuinely hierarchical
A first pass (widened `SC05_consecutive`'s window, added `SC02_gaps_excess`) was grounded in a real university timetable PDF but didn't move the generated schedule's gap numbers at all — even 450s and 43% of rows changing. Diagnosed with `diagnose_terms.py` (fix every variable to a real solved schedule, add the objective, solve trivially, read each penalty's actual value): `SC03_wastage` (room wastage), the **lowest** nominal weight (1), was **68.5%** of the total weighted objective on a real solve, vs. 11.3% for the gap terms at 10x the per-unit weight — its raw magnitude (rooms routinely much bigger than enrolled headcount, summed over 370 sessions) swamped the weight advantage. A weighted sum can't fix this reliably since the right rescaling factor is dataset-dependent. **Fixed properly:** `solve_pipeline.solve_lexicographic_soft` — real hierarchical optimization, 3 tiers solved in strict priority order (section/student-group day structure incl. a new `SC_isolated` term → faculty compactness → everything else including room wastage), each tier's achieved value LOCKED as a hard ceiling before the next tier is even considered, so a lower tier can never trade away a unit of a higher tier's quality regardless of raw magnitude. Verified on a real 450s run (0 hard violations, independently re-validated): total section gaps 112→106, isolated runs 60→55, mean span 6.03→5.95 — a real, modest improvement, with an honest tradeoff (faculty gaps 203→206, since faculty is now correctly subordinate to section structure). Inspected real example section-days: some now match the target block-lunch-block pattern exactly, others still show the old scattered pattern — tier 1 finished at `FEASIBLE` with an unproven best-bound of 0 in 220s, so more section-day compactness is likely available with a larger tier-1 time budget; not yet re-tested at a larger budget.

### A synthetic second dataset — first real evidence for the genericity claims
Every fix and test above was proven against one dataset (the bundled `SIH_Smart_Timetable_Dataset_CORRECTED`). Added `scripts/generate_synthetic_dataset.py` → `synthetic_data/`: an independently-built dataset (different institution/department/room-type vocabulary, different scale — 6 sections/29 courses/20 faculty/11 rooms vs. the bundled 16/65/40/29 — different IDs throughout), same relational schema. Deterministic (fixed seed), so re-running regenerates an identical dataset. Verified, not just generated: `quick_solvability_check` → 0 blockers/warnings; a real hard-only CP-SAT solve → `OPTIMAL` in 3.9s; `validate_output.py` on that solve → 0 violations. `tests/test_synthetic_dataset.py` (3 tests) keeps this a live regression check, not a one-off artifact. **What this does not test:** the fuzzy CSV adapter's robustness against a genuinely messy/differently-shaped upload (this dataset is clean and schema-conformant, just independently authored) — that gap, immediately below, is still fully open — and it keeps the same 5-day/7-period time structure the bundled dataset uses, since `soft.py`'s gap/consecutive-run terms currently hardcode `range(1,8)` rather than deriving the period range from `time_slots.csv`.

### A third real bug, found by actually driving the live API end-to-end — fixed
Asked "could a user's own data actually produce a timetable through the API a frontend would call" — rather than answer from inference, actually drove `/api/upload` → `/api/solve` → `/api/download` against the synthetic dataset for real. It failed. `students.csv` was documented in `data_dictionary.csv` but never added to `adapter.py`'s `CANONICAL` schema dict, so the fuzzy-matcher had nothing correct to classify it as — it scored just high enough against `course_offerings`' schema (both have `section_id`) to get misclassified and **silently overwrite the real `course_offerings.csv`** with hundreds of garbage rows, each missing a course. Every dataset in this project has a `students.csv`, so this broke every complete upload, not an edge case. `quick_solvability_check` did catch it (`422`, not a silent wrong answer) — but no timetable came out. **Fixed:** added `"students"` to `CANONICAL` with the fields `data_dictionary.csv` already documented. Re-verified live end-to-end after the fix: upload (17/17 tables correctly detected) → solve (`hard_status: OPTIMAL`, `soft_status: FEASIBLE`) → download → `validate_output.py` → 0 violations → per-section grid download all worked for real over HTTP.

### Dynamic re-solve — the named requirement, now built and verified live
The real problem statement's "every change to one section cascades through the rest" now has a real answer. `solve_pipeline.solve_lexicographic_soft` gained an optional stability tier (`stability_reference`, `_stability_expr`): solved FIRST, ahead of even section-day structure, minimizing how many sessions differ at all from a previous solve — each tier still locks its achieved value before the next tier runs, same mechanism as the rest of the lexicographic solver. `solve_incremental_resolve` wraps this into one call (previous CSV in, changed root data in, minimal-diff schedule out), and `hint_from_csv` (promoted out of a one-off script into real library code) translates a solved CSV back into hint values. Wired into a new `POST /api/resolve/{job_id}` — upload only the changed file(s) for an already-solved job, get back a re-solved schedule plus a human-readable diff (`old`/`new` per changed session). Verified live end-to-end, twice (once via direct Python call, once over real HTTP against the running server): marked one faculty member unavailable at their currently-assigned slot → `tier0_stability` proved **OPTIMAL at objective 1** (the mathematically minimal possible disruption) → exactly **one** decision changed (that offering's faculty, to another eligible instructor who was free) → the other 32 offerings' 83 sessions stayed byte-for-byte identical → independently re-validated: 0 violations. `tests/test_incremental_resolve.py` asserts the diff stays small (≤5 changes) and hard-clean on every run, not just this one measured case. Default re-solve time budgets are much shorter than a cold solve (60s/40s/30s/30s vs. 220s/100s/130s) since this is meant to feel interactive — not yet tuned against a larger production-scale dataset. **Not built:** "modification suggestions" (the problem statement's plural — presenting several candidate ways to accommodate a change, ranked) is a larger feature than this; what exists is one minimal-disruption re-solve per change, not a menu of options.

---

## 2. What's Remaining

**Ranked by actual leverage, not by how the sections happen to be ordered below.**

### The highest-value open item: nobody has tested this on real, messy data
The fuzzy CSV adapter (`adapter.py`) handles renamed columns of the *same* relational shape — now confirmed on a second, independently-built clean dataset (`synthetic_data/`, see above), not just the original sample. It has still never been tested against a genuinely different *shape* (a legacy ERP export, an existing Excel timetable with no relational IDs) — and there's still no confirmed college, department, or person lined up to try it. This is the thing every other item below is downstream of: building more UI or solver polish before this is answered risks repeating the exact mistake the wizard already made once. See `FINAL_PLAN.md`'s Assignment for the concrete next action.

### Frontend build — now the single largest gap vs. the problem statement's deliverables
`DESIGN.md` exists; the actual page doesn't yet. Scope (per the design consultation): upload panel, live solve-status display (`objective`, penalties, any `quick_solvability_check` blockers), and a per-section timetable grid preview reusing the `S_*.csv` format `backend/app.py` already produces — now also `/api/resolve`'s diff output, once there's a UI to show it in. Deliberately not another multi-step wizard. Covers most of "Admin dashboard" + "automated report generation" from the original deliverables list in one build; "Student/faculty timetable portal" is a thin read-only layer on top of the same grid component once this exists.

### "Modification suggestions" (plural) — a bigger feature than what's built
Dynamic re-solve itself is done (see §1) — one input changes, get back one minimal-disruption re-solve. What's *not* built: presenting several ranked candidate ways to accommodate a change (the problem statement's plural "suggestions"), letting a user pick between them before committing. Not urgent — the single-answer version already answers the core pain point named in the problem statement.

### Solver performance & quality (optional, not blocking)
- Reduce model size in `soft.py` (`SC_facgaps`/`SC06` have known redundancy — see file for specifics).
- Weight sensitivity — is `SC03` at weight 1 vs 2 worth testing? Should `SC_facgaps`/`SC11` be disabled by default for faster solves?
- Try `solver.parameters.use_lns = True` as an alternative to hinting.

### Observability
Log solver internals (`num_conflicts`, branches) per job — makes a future `UNKNOWN`/`INFEASIBLE` debuggable instead of a guess.

### Deployment
Dockerize `backend` + `sih_solver`, persist `uploads/`/`timetables_generated/` as volumes. Not started; not urgent until there's a real user to deploy for.

### Open questions (unresolved, need a real answer not a guess)
1. Does "lab batches must be split **and rotated**" (the real problem statement's wording) mean something beyond the parallel-batch splitting `batches.py` already does — e.g. a multi-week alternating cycle? The solver is single-week only today.
2. Should the lab-batch `threshold` (currently a hardcoded 40) be user-configurable?
3. Keep all 9 soft-weight terms enabled by default, or ship a lighter default?
4. Is `150s`/`150s` (up to ~450s worst-case across seed retries) an acceptable wait for a live demo, or does that need to come down — trading away some of the "never `UNKNOWN`" reliability?
5. Standardize on one dataset format (flat CSVs vs. the zipped "corrected" dataset), or keep supporting both?

---

## 3. Architecture

```
User ZIP/CSV/XLSX → parsers/ (zip/xlsx) → sih_solver/adapter.py (fuzzy column + dataset-type detection)
                                         ↓
                          uploads/{job_id}/normalized/*.csv
                                         ↓
                          sih_solver/dataset.py:quick_solvability_check()  ← fails fast (422) on bad data
                                         ↓
                          sih_solver/solve_pipeline.py:solve_hard_then_soft()
                            → full_model.build_full_hard_model() (hard.py collisions, availability, workload, sync electives)
                            → solve hard-only (seed retry) → AddHint → soft.py add_soft_objective() → solve soft
                            → falls back to hard-only schedule if soft times out
                                         ↓
                          generated_timetable.csv + class_timetables/{section}.csv
                                         ↓
                          backend/app.py (FastAPI): /api/upload, /api/solve/{id}, /api/resolve/{id},
                                                     /api/status/{id}, /api/download/{id},
                                                     /api/download_class/{id}/{section}
```

*(No frontend exists right now — see §2. Use `/docs`, the FastAPI Swagger UI, or `curl` to drive the API.)*

### Key Files

| Path | Role |
|------|------|
| `sih_solver/preprocessing.py` | `load_all`, `compatible_rooms_by_course`, `synchronized_offering_groups`, `elective_alternative_pairs` |
| `sih_solver/model.py` | `build_variables` — the CP-SAT decision variables |
| `sih_solver/hard.py`, `full_model.py` | All hard constraints (HC01–HC16) — see `CONSTRAINTS.md` for the full table |
| `sih_solver/soft.py` | 9 soft terms, `DEFAULT_WEIGHTS`, `apply_human_feedback` |
| `sih_solver/solve_pipeline.py` | **Hardened solve** — retry seeds, hint, fallback (§1) |
| `sih_solver/dataset.py` | `quick_solvability_check` (§1), `audit_dataset` (standalone flat-folder audit) |
| `sih_solver/batches.py` | Lab-batch splitting |
| `sih_solver/adapter.py` | Fuzzy CSV/dataset-type detection for uploads |
| `backend/app.py` | FastAPI — the entire current API surface |
| `tests/` | 51 tests (34 fast + 17 CP-SAT-solving) |
| `timetables_generated/` | Sample deliverables + `FIX_REPORT.md` |
| `CONSTRAINTS.md` | Full HC/SC reference — source of truth for the constraint model |
| `FINAL_PLAN.md` | Office-hours review: honest assessment, the wizard build-and-revert story, real USAR/NEP2020 problem statement findings |
| `DESIGN.md` | Frontend design system (drafted, not yet built against) |

---

## 4. Known Quirks

- **`C007` (WORKSHOP, `DRAWING_BOARDS`)** has no compatible room in the sample dataset → falls back to an arbitrary classroom; `SC03` uses `>=` not `==` to stay feasible. `quick_solvability_check` correctly flags this as a `WARNING` on every upload of the sample data — expected, not a bug.
- **CP-SAT is nondeterministic** — the same model can need a different seed to solve on different runs (this is *why* §1's retry logic exists, not a residual bug).

---

## 5. How to Re-run

```bash
# tests — fast subset (~15s)
python3 -m pytest tests/test_preprocess.py tests/test_dataset.py tests/test_diagnose.py tests/test_variables.py tests/test_adapter.py tests/test_synthetic_dataset.py -q

# tests — full suite including real CP-SAT solves (~4 min)
python3 -m pytest tests/ -q  # 51 passed

# hardened solve pipeline directly
PYTHONPATH=. python3 -c "
from sih_solver.solve_pipeline import solve_hard_then_soft
r = solve_hard_then_soft(None, hard_time_limit=150.0, soft_time_limit=150.0)
print(r['status'], r['hard_status'], r['soft_status'], r['objective'])
"

# backend
uvicorn backend.app:app --reload --port 8000
# POST /api/upload (multiple files: ZIP/CSV/XLSX)
# → POST /api/solve/{job_id}?hard_time_limit=150&soft_time_limit=150   (422 immediately if data can't solve)
# → GET /api/status/{job_id}
# → GET /api/download/{job_id}  /  /api/download_class/{job_id}/{section}
# No frontend yet — use /docs (Swagger UI) or curl -F "files=@courses.csv" ... http://localhost:8000/api/upload
```

---

## Appendix: Decision Log

| Date | Decision | Why |
|------|----------|-----|
| 2026-08-23 | Built a 19-dataset schema + validator + JSON store + 16-step wizard frontend, then reverted it the same day. | Built to make bad data fail fast in the browser. Reversed after review found it was built without a real user, ahead of this plan's own roadmap. Two real bugs found while it was live were kept (fixed in the simpler reverted code). |
| 2026-08-23 | Hardened solver invocation (retry seeds + hint + fallback) and added a fast pre-solve check, before any frontend or product work. | Direct answer to "will I get the best timetable with data a college hands over" was "no, not reliably" — fixed the two concrete reasons why, verified with real runs, before extending scope further. |
| 2026-08-23 | Drafted `DESIGN.md` (Industrial/Utilitarian, navy/parchment) for the Phase B frontend, paused before building it to check backend status first. | Keeping the "verify before extending" discipline — confirm the backend story is solid and current before investing in UI on top of it. |
| 2026-08-23 | Made `adapter.py:normalize_upload_folder`'s missing-required-file behavior explicit-opt-in (`fill_missing=False` default) instead of always silently copying bundled sample data; removed `backend/app.py`'s regex-based workaround for the same problem. | The always-fill default meant any caller other than `backend/app.py` (tests, CLI, future frontend code) got silent real-data/sample-data blending with no way to opt out — the same family of bug as the identity-field corruption fixed earlier that day, just in a different spot. Fixing it at the library source removes the need for a fragile string-matching workaround at the call site. |
