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

---

## 2. What's Remaining

**Ranked by actual leverage, not by how the sections happen to be ordered below.**

### The highest-value open item: nobody has tested this on real, messy data
The fuzzy CSV adapter (`adapter.py`) handles renamed columns of the *same* relational shape. It has never been tested against a genuinely different shape (a legacy ERP export, an existing Excel timetable with no relational IDs) — and there's still no confirmed college, department, or person lined up to try it. This is the thing every other item below is downstream of: building more UI or solver polish before this is answered risks repeating the exact mistake the wizard already made once. See `FINAL_PLAN.md`'s Assignment for the concrete next action.

### Frontend build
`DESIGN.md` exists; the actual page doesn't yet. Scope (per the design consultation): upload panel, live solve-status display (`objective`, penalties, any `quick_solvability_check` blockers), and a per-section timetable grid preview reusing the `S_*.csv` format `backend/app.py` already produces. Deliberately not another multi-step wizard.

### Dynamic / incremental re-solve — a named requirement, not a nice-to-have
The real problem statement explicitly names "modification suggestions" and "dynamic timetable updates" as required platform capabilities, and calls out "every change to one section cascades through the rest" as the core pain of manual scheduling. Nothing addresses this today — any change means re-running the full solve from scratch. The mechanism is already half-built: `solve_pipeline.py`'s `AddHint` approach could be reused to warm-start a re-solve after a single input changes, showing only the diff. Not started.

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
                          backend/app.py (FastAPI): /api/upload, /api/solve/{id}, /api/status/{id},
                                                     /api/download/{id}, /api/download_class/{id}/{section}
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
| `tests/` | 45 tests (28 fast + 17 CP-SAT-solving) |
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
# tests — fast subset (~9s)
python3 -m pytest tests/test_preprocess.py tests/test_dataset.py tests/test_diagnose.py tests/test_variables.py -q

# tests — full suite including real CP-SAT solves (~4 min)
python3 -m pytest tests/ -q  # 45 passed

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
