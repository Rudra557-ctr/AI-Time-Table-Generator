# SIH Smart Timetable Generator — Project Plan

**Dataset:** `SIH_Smart_Timetable_Dataset_CORRECTED.zip` → `/tmp/sih_timetable_dataset_corrected` (also flat CSVs at repo root for dev). Deduped: **133 offerings → 370 sessions**, 65 courses, 40 faculty, 29 rooms (12 CLASSROOM), 35 slots (5 days × 7 periods), 16 sections (`S_CSE_1_A` … `S_AR_4_A`). Lab-batch mode: 16 labs >40 → 149 offerings, 386 sessions.

**Solver:** Google OR-Tools **CP-SAT** (`cp_model.CpModel`). Hard = `model.Add(...)`; soft = `model.Minimize(sum w_i * penalty_i)`.

---

## 1. What the Project Is

Auto-generate a college timetable that satisfies all *hard* rules (no clashes) and optimizes *soft* preferences. Input = CSVs or ZIP upload → Output = per-offering assignment `(slot, room, faculty)` + per-section class grids `S_*`.

**Status (2026-08-23):**
- Hard: `165757` vars, `505k` constraints, **OPTIMAL** `106.9s` (150s, 8 workers, retry seeds; 90s sometimes UNKNOWN due to filtered `alt_pairs`).
- Soft: `536675` vars, `1.22M` constraints, **FEASIBLE** `121.6s` hinted from hard (`obj 7408`, `SC02:91 SC05:147 SC06:0 SC08:106 SC_facgaps:208 SC11:108 SC01:72 SC09:150 SC03:3740`, bound 3030). Without hint, UNKNOWN in 150s.
- Batches: 16 labs → 32 batches, **OPTIMAL** 45s.
- Tests: `28 passed` (`pytest tests/ -q`).
- **Reverted (2026-08-23):** a data-wizard layer (`sih_solver/schema.py`, `sih_solver/validator.py`, `backend/store.py`, 16-step `frontend/`, plus their tests) was built and then deliberately removed — see "Decision log" below. `backend/app.py` is back to the simple pre-wizard shape: `/api/upload` normalizes via `adapter.py`'s fuzzy column/dataset-type detection with no persistent JSON store or BLOCKER-gate, `/api/solve` reads straight from the job's `normalized/` folder. Two real bugs found while the wizard's upload-first flow was live got carried forward into this simpler code, since they were bugs in the shared upload/solve logic, not the wizard: (1) the `?fill`-cleanup step used to match dataset names by substring, so a filled `faculty_availability.csv` could get an uploaded `faculty.csv` deleted by mistake (fixed with an exact regex match); (2) `sih_solver/preprocessing.py:load_all` now coerces `root` to `pathlib.Path` defensively, since `backend/app.py` passes it a `str`.

### Decision log

- **2026-08-23 — Built, then removed, a 19-dataset schema + validator + per-job JSON store + 16-step wizard frontend.** Reasoning at the time: make bad data fail fast in the browser instead of during a slow solve. Reversed the same day after an `/office-hours` review found the wizard was built and fully fleshed out without a single real user, ahead of the original plan below, which never called for it. Decision: drop it, recommit to this plan's original Phase A–D sequencing (solver hardening and product polish on the existing upload/solve flow), and revisit a smarter import layer later only if real usage (see Assignment in `FINAL_PLAN.md`) shows the plain fuzzy-CSV adapter isn't enough.

---

## 2. Architecture

```
User ZIP/CSV → parsers/ (csv/xlsx/zip) → sih_solver/adapter.py (normalize_upload_folder, auto-generates offering_id/course_id)
                                        ↓
                              preprocessing.py (load_all, compatible_rooms_by_course, EQUIPMENT_SYNONYMS, synchronized_offering_groups, elective_alternative_pairs, contiguous_slot_sets)
                                        ↓
                              model.py: build_variables(offerings_override) → Start[(oid,s)]: slot idx, Teacher[oid]: fac idx, Room[(oid,s)]: room idx + meta (slot/room/fac maps, eligible, compatible)
                                        ↓
                              full_model.py: build_full_hard_model() wires hard constraints:
                                - hard.py: add_faculty_collision, add_room_collision (HC02, dur2 via next_Start), add_section_collision (HC03, skips alt_pairs), add_student_collision (HC04), add_synchronized_constraints (HC13)
                                - full_model.py: add_availability_constraints, add_fixed_events, add_workload_constraints (HC01/HC16), add_no_repeat_same_course_same_day (HC12)
                                        ↓
                              soft.py: add_soft_objective(..., DEFAULT_WEIGHTS) → shared _build_occupied, SC02 gaps, SC05 consecutive, SC06 spread, SC08 undesirable (p1/p7), SC_facgaps, SC11 building (gated bld), SC01 pref, SC09 balance, SC03 wastage
                                        ↓
                              CpSolver.Solve() → CSV (offering_id,course_id,section_id,session,slot_id,day,start_time,end_time,room_id,faculty_id) → class grids S_*.csv/txt → timetables_generated/
                                        ↓
                              backend/app.py (FastAPI) → /api/upload → /api/solve/{job_id} (background_tasks, patched load_all) → /api/status, /api/download/{job_id}, /api/download_class/{job_id}/{section}
                              cli.py (dev loop: hard → soft → human feedback via apply_human_feedback)
                              batches.py (split_lab_offerings threshold 40)
```

*(No frontend currently exists — removed along with the wizard layer, see Decision log above. Use `/docs` (FastAPI's Swagger UI) or `curl` to drive `backend/app.py` until Phase B below rebuilds one.)*

### Key Files

| Path | Role | Lines |
|------|------|-------|
| `sih_solver/preprocessing.py:11` | `load_all`, `compatible_rooms_by_course` (+ `EQUIPMENT_SYNONYMS`), `synchronized_offering_groups` (per `(group,course)` 13 groups), `elective_alternative_pairs` (filtered if student takes both) | 286 |
| `sih_solver/model.py` | `build_variables(offerings_override)` | — |
| `sih_solver/hard.py:153,224,278` | `add_section_collision`, `add_student_collision`, `add_synchronized_constraints` | 297 |
| `sih_solver/full_model.py:84` | `add_workload_constraints`, `add_availability_constraints`, `add_fixed_events`, `add_no_repeat...`, `build_full_hard_model` | 213 |
| `sih_solver/soft.py:17` | `DEFAULT_WEIGHTS` 9 terms, `_build_occupied`, `add_soft_objective`, `apply_human_feedback` | 515 |
| `sih_solver/batches.py` | `split_lab_offerings`, `build_lab_batch_hard_model` | — |
| `sih_solver/adapter.py:159` | `normalize_upload_folder`, `infer_column_mapping`, `detect_dataset_type`, `CANONICAL` (17 datasets) — fuzzy header/dataset-type detection for uploads | 169 |
| `sih_solver/dataset.py:14` | `audit_dataset` — standalone dataset audit/report (counts, dedup, equipment mismatch, eligibility) over a flat CSV folder | 109 |
| `sih_solver/diagnose.py` | `solve_with_diagnosis` | 50 |
| `sih_solver/review.py` | `generate_preview` — human-loop soft-scoring preview helper | 32 |
| `backend/app.py` | FastAPI — `/api/upload`, `/api/solve/{job_id}`, `/api/status/{job_id}`, `/api/download/{job_id}`, `/api/download_class/{job_id}/{section}` | ~250 |
| `timetables_generated/` | `generated_timetable_fixed.csv` (370 rows, OPTIMAL), `generated_timetable_soft.csv` (FEASIBLE), `S_*.csv/txt`, `FIX_REPORT.md` | 37 files |
| `tests/` | `test_hard_fixes.py`(7), `test_preprocess.py`(10), `test_soft.py`(3), `test_dataset.py`(11), `test_hard_core.py`(4), `test_hard_full.py`(3), `test_diagnose.py`(2), `test_variables.py`(5) = **28 total** | — |

### Data Flow — Hard Constraints (HC)

- HC02 room double-booking (dur2 labs `PL001` via `next_Start`)
- HC01 daily cap per faculty (`faculty.csv:max_hours_per_day`, F027=3)
- HC12 no repeat same course same section same day (single-slot, `sessions_per_week>1`)
- HC03 section no-overlap (skips `alt_pairs`)
- HC04 student-level OAE/PCE (cross-section vs core + elective vs elective; 35 pairs like `O0141/O0143 S_AR_4_A` globally disjoint via filtered `alt_pairs`)
- HC13 synchronized (same course across sections same slot per session idx)
- HC10 equipment (synonym map)
- Availability, fixed events, workload

### Soft Constraints (SC) — weights `SC02(10)>SC01(8)>SC09(5)>SC05/06(4)>SC08/11/facgaps(2)>SC03(1)`

- SC02 student gaps, SC05 consecutive 3+, SC06 spread distinct days, SC08 undesirable p1/p7, SC_facgaps faculty gaps, SC11 building movement, SC01 pref, SC09 workload balance, SC03 wastage (`max(0,cap-cnt)`)

---

## 3. Repo Structure

```
/sih/
├── sih_solver/         # core solver
│   ├── preprocessing.py
│   ├── model.py
│   ├── hard.py
│   ├── full_model.py
│   ├── soft.py
│   ├── batches.py
│   ├── adapter.py      # fuzzy CSV/dataset-type detection for uploads
│   ├── dataset.py
│   ├── diagnose.py
│   ├── review.py
│   └── cli.py
├── backend/
│   └── app.py          # FastAPI — /api/upload, /api/solve/{id}, /api/status, /api/download
├── (no frontend/ currently — removed with the wizard layer; use /docs or curl)
├── parsers/            # csv/xlsx/zip
├── tests/              # 28 tests
├── timetables_generated/ # fixed/soft/full CSVs + S_*.csv/txt + FIX_REPORT.md
├── uploads/            # per-job dirs (job_id/{raw, normalized, status.json, generated_timetable.csv})
├── courses.csv, rooms.csv, ... (flat dataset) + SIH_Smart_Timetable_Dataset_CORRECTED.zip
├── CONSTRAINTS.md (HC/SC reference)
├── FINAL_PLAN.md (office-hours review: honest status, the wizard build-and-revert decision, USAR/NEP2020 problem-statement findings)
└── PLAN.md (this file)
```

---

## 4. Current Status & Known Quirks

- **Hard with filtered `alt_pairs` (18 vs 53)** is more constrained (enforces 35 same-section alternative pairs where students take both C060/C065) → takes ~110s vs 58s previously. Nondeterministic (portfolio search + time limit); hard needs `150s` retry, soft needs hint.
- **Soft** is `536k` vars, `1.22M` constraints; without hint, UNKNOWN in 150s (LP bound 3030, no integer solution). With hard hint, FEASIBLE `121.6s`.
- **`C007` WORKSHOP `DRAWING_BOARDS`** has no compatible room → fallback any classroom, SC03 uses `>=` not `==` to stay feasible.
- **Tests:** `45 passed` after extracting zip to `/tmp/sih_timetable_dataset_corrected` and guarding `full_model.py:84` empty `slot_to_idx`. `test_hc04` and `test_lab_batch_split` use `150s` retry (seed 1).
- **Generated:** `timetables_generated/generated_timetable_fixed.csv` (370 rows, OPTIMAL) + `soft.csv` (FEASIBLE) via `/tmp/gen_hinted2.py` (hard hint → soft).

---

## 5. Next Steps — Plan

### A. Make solving actually reliable — DONE (2026-08-23), verified with real runs

This section exists because of a direct question asked 2026-08-23: *"will I get the best timetable with data a college hands over?"* The honest answer at the time was **no, not reliably** — for two concrete, fixable reasons. Both are now fixed and verified against the real dataset, not just reviewed by reading the code.

**A1. Harden solver invocation — never return nothing if a valid schedule exists. DONE.**
- Implemented in `sih_solver/solve_pipeline.py:solve_hard_then_soft()`, used by `backend/app.py:run_solve` (not yet wired into `cli.py` — out of scope for now, `cli.py` is a dev-loop tool, not the production path):
  1. Solve **hard-only** first, trying seeds `[0, 1, 42]` in order (each gets its own full `150s`), stopping at the first `OPTIMAL`/`FEASIBLE`.
  2. `INFEASIBLE` on any seed stops immediately (proven no valid schedule exists — no point retrying or attempting soft).
  3. On hard-only success, hints its variable assignments into the combined hard+soft model (one `model.AddHint(var, val)` call per variable — this OR-Tools version's binding takes a single var/value pair, not batched lists; a batched-list attempt threw `TypeError` inside OR-Tools' own `add_hint()`, caught during verification, fixed by reading the library source), then solves soft with its own `150s` budget (bumped from an initially-planned `120s` — see acceptance data below for why).
  4. If soft times out without an integer solution, **falls back to the hard-only schedule** (`HARD_ONLY_FALLBACK` status) instead of returning nothing.
  5. `/api/solve` now takes `hard_time_limit`/`soft_time_limit` query params (defaults `150.0`/`150.0`), replacing the old single `time_limit: int = 60`.
- **Acceptance test result (3 real runs against the actual repo dataset, 133 offerings):**

  | Run | Hard | Soft | Final status | Total wall time |
  |---|---|---|---|---|
  | 1 | OPTIMAL @ 95.5s (seed 0) | timed out (UNKNOWN) @ 122.7s | `HARD_ONLY_FALLBACK` | 225.6s |
  | 2 | OPTIMAL @ 317.1s (seed 0 failed → seed 1 succeeded) | FEASIBLE @ 124.2s, obj 12261 | `FEASIBLE_SOFT` | 449.4s |
  | 3 | OPTIMAL @ 95.0s (seed 0) | FEASIBLE @ 124.5s, obj 12403 | `FEASIBLE_SOFT` | 226.8s |

  **3/3 runs returned a usable, conflict-free schedule. Zero `UNKNOWN`.** Both failure-recovery paths fired for real during these runs (run 2 needed the seed retry; run 1 needed the hard-only fallback), not just in theory. Run 1's 120s soft timeout is why the soft budget was raised to 150s afterward.

**A2. Lightweight solvability pre-check — the gap created by removing the wizard. DONE.**
- Implemented as `sih_solver/dataset.py:quick_solvability_check(normalized_dir)` — checks required files present/non-empty, every used course has ≥1 eligible faculty (**BLOCKER** — otherwise `model.py` silently drops the offering with only a stdout print, the worst kind of silent failure) and ≥1 compatible room (**WARNING** — falls back to an arbitrary classroom, not a crash), and a contiguous slot pair exists if any course/offering needs `session_duration==2` (**BLOCKER** — otherwise a bare `ValueError` crashes the whole background solve).
- Wired into `/api/solve` as a synchronous check before the background task starts; returns `422` with the blocker list immediately if any are found.
- **Acceptance test result:** removed all `faculty_courses` rows for one course, called the live `/api/solve` endpoint — **18ms**, `HTTP 422`, exact message: `"Course 'C001' has no eligible faculty in faculty_courses.csv — that offering would be silently dropped from the schedule."` Clean data on the same job: 0 blockers, 1 warning (correctly identifies the pre-existing, previously-documented `C007` no-compatible-room case).

**A3. Test time limits updated. DONE.** — `test_hc13_synchronized_same_slot` bumped `90s`→`150s` + seed-1 retry, matching `test_hc04`/`test_lab_batch_split` which already had this pattern.

**A4. Deliverables regenerated. DONE.** — `timetables_generated/generated_timetable_fixed.csv` (hard-only), `_soft.csv`/`_full.csv` (hinted, `FEASIBLE`, obj **12287**), and all 16 `S_*.csv`/`.txt` section grids regenerated via `solve_pipeline.py` (hard `OPTIMAL` 91.6s, soft `FEASIBLE` 153.9s). `FIX_REPORT.md`'s solver-status table updated with these numbers and an honest note that the objective (12287 vs. the old 7408 sample) isn't directly comparable run-to-run under CP-SAT's nondeterministic search — flagged as "watch for a pattern," not dismissed.

### A+. Verify before extending — the discipline that got skipped last time

A1-A4 are done and verified. Phase B, C, D below — and Phase 2 of `FINAL_PLAN.md` (finding a real USAR/NEP-2020 contact) — can now proceed. The wizard got built because this discipline was skipped once already: effort went into new surface area before the existing surface area was proven reliable. Keep applying it going forward — verify a change against the real dataset before calling it done, the way A1/A2 were.

### B. Short-term (product polish) — only after A+ is verified

5. ~~Backend robustness: hint path, realistic time_limit~~ — **now covered by A1/A2 above**, not a separate later item.
6. **Frontend** — none exists right now (removed with the wizard). Rebuild a minimal one: upload, poll `/api/status`, display `objective`/penalties breakdown and A2's solvability blockers if any, per-section grid preview (reuse `S_*.csv` logic). Deliberately not the 16-step wizard — see `PLAN.md`'s Decision log for why.
7. ~~Adapter validation as in dataset.py:audit_dataset~~ — **now covered by A2 above.**
8. **Observability** — log solver `ResponseProto` (num_conflicts, branches) to `jobs[job_id]/solver.log` for debugging UNKNOWN vs FEASIBLE.

### C. Medium-term (solver performance)

9. **Reduce model size** — `soft.py` `SC_facgaps` hoisted `is_ass` already, but still `40 fac × 5 days × 7 periods × ~10 offerings × 3 sess` → `~4000` `is_ass` + `~1400` `occ` + `~200` gaps; profile with `model.Proto().variables` and consider disabling `SC_facgaps` by default or fixing `SC06` to use `Start` directly not `affecting` expansion (currently loops `for p in 1..7: for b in aff: conds.append(b)` → duplicates).
10. **Tune weights** — current `DEFAULT_WEIGHTS` from prompt; run sensitivity: try `SC03` weight 1 vs 2, `SC_facgaps` 2 vs 0, measure `obj 7408` vs hard-only `obj 0`.
11. **Alternative: LNS** — enable `solver.parameters.use_lns = True` for soft to find FEASIBLE faster without hint.

### D. Long-term / Optional

12. **Batches as first-class** — expose `split_lab_offerings` threshold as UI param (currently 40) and generate `offerings_override` mode via `build_variables(offerings_override)` in `backend/app.py` when `student_count > threshold`.
13. **Incremental solving** — implement human feedback loop `soft.py:493` `apply_human_feedback` end-to-end: frontend comment → `/api/feedback` → re-solve with new weights (currently `cli.py` only).
14. **Deployment** — Dockerize `backend` + `sih_solver`, add `uvicorn` startup with `PYTHONPATH`, persist `uploads/` and `timetables_generated/` volumes.

### E. Already done (2026-08-23, survived the wizard revert)

15. ~~Hardcoded `BASE` path~~ — fixed. `backend/app.py`, `sih_solver/preprocessing.py`, `sih_solver/dataset.py`, `sih_solver/adapter.py`, and both test files that referenced the absolute repo path now all resolve relative to `__file__`.
16. ~~`hard_interval.py` dead stub~~ — deleted (confirmed unused first).
17. ~~No `.gitignore`~~ — added (`__pycache__/`, `.DS_Store`, `uploads/`, `.pytest_cache/`); already-tracked cruft untracked.
18. **Minimal access gate added** — `backend/app.py` 401s any `/api/*` request missing an `X-API-Key` header when `SIH_API_KEY` is set; unset (default) leaves it open, so local dev is unaffected.

---

## 6. How to Re-run

```bash
# tests
python3 -m pytest tests/test_hard_fixes.py tests/test_preprocess.py -q  # 17 passed
python3 -m pytest tests/ -q  # 45 passed (ensure /tmp/sih_timetable_dataset_corrected exists: unzip SIH_Smart_Timetable_Dataset_CORRECTED.zip -d /tmp)

# hard only
python3 -c "from sih_solver.full_model import build_full_hard_model; from ortools.sat.python import cp_model; m,S,T,R,meta=build_full_hard_model(); s=cp_model.CpSolver(); s.parameters.max_time_in_seconds=150; s.parameters.num_search_workers=8; print(s.Solve(m), s.StatusName(s.Solve(m)))"

# soft hinted (as in gen_hinted2.py)
PYTHONPATH=. python3 -u /tmp/gen_hinted2.py  # hard 112s OPTIMAL → soft 121s FEASIBLE

# backend
uvicorn backend.app:app --reload --port 8000
# POST /api/upload (ZIP/CSV/XLSX, multiple files) → POST /api/solve/{job_id}?time_limit=120
# → GET /api/status/{job_id} → GET /api/download/{job_id} / /api/download_class/{job_id}/{section}
# No frontend yet — use /docs (Swagger UI) or curl -F "files=@x.csv" http://localhost:8000/api/upload
```

---

## 7. Clarifying Questions (for prioritization)

1. **Priority:** Solver stability (A) first, or product demo (B) for SIH submission?
2. **Lab batches:** Should `threshold 40` be user-configurable or fixed? Always split 16 labs, or only when hard infeasible?
3. **Soft weights:** Keep all 9 terms enabled by default, or lighter default (e.g., disable `SC_facgaps`/`SC11` heaviest) for faster solves?
4. **Time limits:** Is `120-150s` acceptable for demo, or need `<60s` (trade optimality for speed)?
5. **Dataset:** Support both flat `*.csv` at repo root and zipped corrected dataset, or standardize on one?

---

*Generated: 2026-08-22 — Build mode. Source: inspection of `sih_solver/`, `backend/app.py`, `timetables_generated/FIX_REPORT.md`, and last solver runs (hard 106.9s OPTIMAL, soft 121.6s FEASIBLE).*
