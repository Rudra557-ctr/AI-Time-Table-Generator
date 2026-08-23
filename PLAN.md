# SIH Smart Timetable Generator — Project Plan

**Dataset:** `SIH_Smart_Timetable_Dataset_CORRECTED.zip` → `/tmp/sih_timetable_dataset_corrected` (also flat CSVs at repo root for dev). Deduped: **133 offerings → 370 sessions**, 65 courses, 40 faculty, 29 rooms (12 CLASSROOM), 35 slots (5 days × 7 periods), 16 sections (`S_CSE_1_A` … `S_AR_4_A`). Lab-batch mode: 16 labs >40 → 149 offerings, 386 sessions.

**Solver:** Google OR-Tools **CP-SAT** (`cp_model.CpModel`). Hard = `model.Add(...)`; soft = `model.Minimize(sum w_i * penalty_i)`.

---

## 1. What the Project Is

Auto-generate a college timetable that satisfies all *hard* rules (no clashes) and optimizes *soft* preferences. Input = CSVs or ZIP upload → Output = per-offering assignment `(slot, room, faculty)` + per-section class grids `S_*`.

**Status (Aug 22, 2026; wizard layer added Aug 23):**
- Hard: `165757` vars, `505k` constraints, **OPTIMAL** `106.9s` (150s, 8 workers, retry seeds; 90s sometimes UNKNOWN due to filtered `alt_pairs`).
- Soft: `536675` vars, `1.22M` constraints, **FEASIBLE** `121.6s` hinted from hard (`obj 7408`, `SC02:91 SC05:147 SC06:0 SC08:106 SC_facgaps:208 SC11:108 SC01:72 SC09:150 SC03:3740`, bound 3030). Without hint, UNKNOWN in 150s.
- Batches: 16 labs → 32 batches, **OPTIMAL** 45s.
- Tests: `45 passed` on solver core (`pytest tests/ -q`, 17 hard_fixes+preprocess, 3 soft, etc.). **New data-wizard layer adds 56 more** (`test_schema.py` 25, `test_validator.py` 14, `test_data_api.py` 17, all <1s, re-verified passing) → **101 tests total**.
- **New since Aug 22:** a 19-dataset schema (`sih_solver/schema.py`) + L1/L2/L3 cross-dataset validator (`sih_solver/validator.py`) + per-job JSON store (`backend/store.py`) + 16-step wizard frontend (`frontend/js/*`) now sit in front of the solver, with `/api/solve` hard-gated on validation BLOCKERs instead of silently filling missing data. See §2a.

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
                              frontend/ (multi-file wizard: index.html + js/app.js,state.js,api.js,components.js + css/app.css)
                              cli.py (dev loop: hard → soft → human feedback via apply_human_feedback)
                              batches.py (split_lab_offerings threshold 40)
```

### 2a. Data Wizard Layer (Phase A/B/C — new since Aug 22, not yet solver-integrated for editing)

A schema-driven "fill in your data" UI sits in front of the raw upload flow so users without a ready CSV set can build one field-by-field, with typos structurally prevented and cross-dataset problems caught before a 100+s solve is wasted.

```
sih_solver/schema.py     (Phase A) SCHEMAS: all 19 datasets, per-field {dtype, required, enum, fk, pattern, format, min/max, unique, auto_id}
                                    → get_schema/list_datasets/validate_rows (L1: type/enum/required/range/format) /template_csv (header+example row)
                                        ↓
sih_solver/validator.py  (Phase B) validate_all(data) → L1 (delegates to schema.validate_rows) + L2 (FK existence via _fk_map) + L3 (solvability:
                                    eligible faculty per course, compatible room per course, capacity vs student_count, availability coverage,
                                    duration-2 contiguous-slot check, elective-groups-without-enrollments warning)
                                    → {blockers, warnings, per_dataset, summary:{can_solve}}
                                    also validate_single_dataset(ds, rows, whole_store) for per-tab save/import checks
                                        ↓
backend/store.py         (Phase C) uploads/{job_id}/data.json = {dataset: [row,...]} is now the per-job source of truth
                                    init_store/load_store/save_store (atomic tmp+rename), export_to_normalized (→ normalized/*.csv for the solver),
                                    import_from_normalized (legacy CSV → store), set_dataset/get_dataset
                                        ↓
backend/app.py            new endpoints: GET /api/schema, /api/schema/{dataset}, GET /api/templates/{dataset}|all.zip,
                                    POST /api/jobs (create empty job+store), GET /api/jobs/{id} (store+validation+solve status),
                                    GET/PUT /api/jobs/{id}/data/{dataset} (per-dataset CRUD, PUT rejects with 422 if L1/L2 BLOCKERs),
                                    POST /api/jobs/{id}/import/{dataset} (CSV/XLSX → fuzzy column map via adapter.infer_column_mapping → validate → merge)
                                    /api/solve/{id} now gated: refuses with 422 + full validation payload if any BLOCKER exists, no more silent
                                    fallback to /tmp or repo-root CSVs (?fill=true on /api/upload explicitly re-enables the old demo filler)
                                        ↓
frontend/js/app.js        16-step wizard (STEPS const): University → Departments → Programs → Terms → Time Slots → Rooms → Faculty →
                                    Sections → Students(+enrollments) → Courses → Assignments(faculty_courses) → Offerings → Availability →
                                    Electives → Fixed Events → Advanced(academic_rules, readonly) → Review & Solve
                                    state.js (job id + validation cache), api.js (fetch wrappers), components.js (tableEditor, matrixEditor,
                                    issueList, badgeFor for BLOCKER/WARNING pills)
```

**Why it exists:** the old flow only accepted a fully-formed CSV/ZIP and would either solve or silently fill gaps from the repo's base dataset — a user with partial or malformed data got no feedback until a slow solve failed. The wizard makes every one of the 19 datasets editable/importable in the browser with immediate per-row validation, and the solve endpoint now hard-refuses (422) instead of quietly patching holes.

**Not yet wired to the solver's own data flow beyond CSV export** — the wizard's `data.json`/`normalized/*.csv` round-trip is separate from `sih_solver/preprocessing.load_all`'s original flat-CSV-at-repo-root path; `full_model.build_full_hard_model(root)` still just points at a folder of CSVs, so `export_to_normalized` is the only bridge.

### Key Files

| Path | Role | Lines |
|------|------|-------|
| `sih_solver/preprocessing.py:11` | `load_all`, `compatible_rooms_by_course` (+ `EQUIPMENT_SYNONYMS`), `synchronized_offering_groups` (per `(group,course)` 13 groups), `elective_alternative_pairs` (filtered if student takes both) | 286 |
| `sih_solver/model.py` | `build_variables(offerings_override)` | — |
| `sih_solver/hard.py:153,224,278` | `add_section_collision`, `add_student_collision`, `add_synchronized_constraints` | 297 |
| `sih_solver/full_model.py:84` | `add_workload_constraints`, `add_availability_constraints`, `add_fixed_events`, `add_no_repeat...`, `build_full_hard_model` | 213 |
| `sih_solver/soft.py:17` | `DEFAULT_WEIGHTS` 9 terms, `_build_occupied`, `add_soft_objective`, `apply_human_feedback` | 515 |
| `sih_solver/batches.py` | `split_lab_offerings`, `build_lab_batch_hard_model` | — |
| `sih_solver/adapter.py:159` | `normalize_upload_folder`, `infer_column_mapping` (fuzzy header map, reused by wizard import) | 169 |
| `sih_solver/dataset.py:14` | `audit_dataset` | 109 |
| `sih_solver/diagnose.py` | `solve_with_diagnosis` | 50 |
| `sih_solver/schema.py` | **(new)** `SCHEMAS` (19 datasets), `get_schema`, `validate_rows` (L1), `template_csv`, `required_datasets`/`optional_datasets` | 587 |
| `sih_solver/validator.py` | **(new)** `validate_all` (L1+L2+L3 → blockers/warnings/can_solve), `validate_single_dataset` (per-tab) | 463 |
| `sih_solver/review.py` | **(new)** `generate_preview` — human-loop soft-scoring preview helper | 32 |
| `sih_solver/hard_interval.py` | **(new, unfinished stub)** `add_collisions_via_intervals` — Interval/NoOverlap experiment for HC01/HC02, body is a `pass`, not wired in anywhere | 29 |
| `backend/app.py:37` | FastAPI — legacy `/api/upload` → `/api/solve/{job_id}`, plus new wizard API: `/api/schema*`, `/api/templates/*`, `/api/jobs*`, `/api/jobs/{id}/data/{dataset}`, `/api/jobs/{id}/import/{dataset}` | ~600 |
| `backend/store.py` | **(new)** `init_store`/`load_store`/`save_store` (`uploads/{job_id}/data.json`), `export_to_normalized`, `import_from_normalized` | 162 |
| `timetables_generated/` | `generated_timetable_fixed.csv` (370 rows, OPTIMAL), `generated_timetable_soft.csv` (FEASIBLE), `S_*.csv/txt`, `FIX_REPORT.md` | 37 files |
| `tests/` | Solver: `test_hard_fixes.py`(7), `test_preprocess.py`(10), `test_soft.py`(3), `test_dataset.py`(11), `test_hard_core.py`(4), `test_hard_full.py`(3), `test_diagnose.py`(2), `test_variables.py`(5) = 45. Wizard: `test_schema.py`(25), `test_validator.py`(14), `test_data_api.py`(17) = 56. **Total 101** | — |

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
├── sih_solver/         # core solver + wizard schema/validation
│   ├── preprocessing.py
│   ├── model.py
│   ├── hard.py
│   ├── full_model.py
│   ├── soft.py
│   ├── batches.py
│   ├── adapter.py
│   ├── dataset.py
│   ├── diagnose.py
│   ├── cli.py
│   ├── schema.py        # (new) 19-dataset schema, L1 validation, CSV templates
│   ├── validator.py     # (new) L1+L2+L3 cross-dataset validator
│   ├── review.py        # (new) human-loop soft-scoring preview
│   └── hard_interval.py # (new, unfinished) Interval/NoOverlap collision experiment — not wired in
├── backend/
│   ├── app.py          # FastAPI — legacy upload/solve + new wizard API (/api/schema, /api/jobs, ...)
│   └── store.py        # (new) uploads/{job_id}/data.json store, export/import to normalized/*.csv
├── frontend/           # (rebuilt) multi-file wizard: index.html + js/{app,state,api,components}.js + css/app.css
├── parsers/            # csv/xlsx/zip
├── tests/              # 101 tests (45 solver + 56 wizard: schema/validator/data_api)
├── timetables_generated/ # fixed/soft/full CSVs + S_*.csv/txt + FIX_REPORT.md
├── uploads/            # per-job dirs (job_id/{data.json, raw, normalized, status.json, generated_timetable.csv})
├── courses.csv, rooms.csv, ... (flat dataset) + SIH_Smart_Timetable_Dataset_CORRECTED.zip
├── CONSTRAINTS.md (HC/SC + wizard/validation reference)
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

### A. Immediate (stabilize & document) — no new constraints

1. **Harden solver invocation** — wrap `build_full_hard_model` + `add_soft_objective` in `solve_with_retry` helper (seeds `[0,1,42]`, `150s` hard, `120s` soft hinted) and use it in `backend/app.py:68` `run_solve` and `cli.py`. Currently `app.py:106` does single `60s` solve with no retry/hint → will be UNKNOWN for filtered hard.
2. **Make `_build_occupied` conditional** — currently built unconditionally even when only `SC01/SC03` needed; guard with `if any(weights.get(k) for k in ["SC02","SC05","SC06","SC11"])`.
3. **Update `tests/test_hard_fixes.py:159`** — already bumped to `150s` retry for `HC04`; apply same to `test_lab_batch_split:115` and `test_hc13:134` (lab done, HC13 still 90s). Ensure CI uses `PYTHONPATH` and `/tmp/...` zip extracted.
4. **Regenerate & lock** — re-run `/tmp/gen_hinted2.py` and commit `FIX_REPORT.md` + `generated_timetable_*.csv` (soft is hinted FEASIBLE; consider committing both fixed and soft).

### B. Short-term (product polish)

5. **Backend robustness** — `backend/app.py:63` `time_limit` param is `int` (default 60) but hard needs 120-150; change default to `120`, add `hint` path (solve hard first, then soft with `AddHint`), and return `objective`/`penalties` in `/api/status`. Handle `C007` warning cleanly.
6. **Frontend** — `frontend/index.html` currently polls `/api/status`; add display of `audit` (equipment mismatches, compatible rooms) and `penalties` breakdown, plus per-section grid preview (reuse `S_*.csv` logic).
7. **Adapter** — `adapter.py:159` already auto-generates `offering_id`; add validation for `course_offerings.csv` dedup and `student_count` vs `room capacity` warnings (as in `dataset.py:audit_dataset`).
8. **Observability** — log solver `ResponseProto` (num_conflicts, branches) to `jobs[job_id]/solver.log` for debugging UNKNOWN vs FEASIBLE.

### C. Medium-term (solver performance)

9. **Reduce model size** — `soft.py` `SC_facgaps` hoisted `is_ass` already, but still `40 fac × 5 days × 7 periods × ~10 offerings × 3 sess` → `~4000` `is_ass` + `~1400` `occ` + `~200` gaps; profile with `model.Proto().variables` and consider disabling `SC_facgaps` by default or fixing `SC06` to use `Start` directly not `affecting` expansion (currently loops `for p in 1..7: for b in aff: conds.append(b)` → duplicates).
10. **Tune weights** — current `DEFAULT_WEIGHTS` from prompt; run sensitivity: try `SC03` weight 1 vs 2, `SC_facgaps` 2 vs 0, measure `obj 7408` vs hard-only `obj 0`.
11. **Alternative: LNS** — enable `solver.parameters.use_lns = True` for soft to find FEASIBLE faster without hint.

### D. Long-term / Optional

12. **Batches as first-class** — expose `split_lab_offerings` threshold as UI param (currently 40) and generate `offerings_override` mode via `build_variables(offerings_override)` in `backend/app.py` when `student_count > threshold`.
13. **Incremental solving** — implement human feedback loop `soft.py:493` `apply_human_feedback` end-to-end: frontend comment → `/api/feedback` → re-solve with new weights (currently `cli.py` only).
14. **Deployment** — Dockerize `backend` + `sih_solver`, add `uvicorn` startup with `PYTHONPATH`, persist `uploads/` and `timetables_generated/` volumes.

### E. Wizard/data-layer follow-ups (new, from Aug 23 build)

15. **Hardcoded `BASE` path** — `backend/app.py:31` sets `BASE = pathlib.Path("/Users/riyanshukumar/Downloads/sih")` (absolute, machine-specific). Replace with a path relative to the module (`pathlib.Path(__file__).resolve().parent.parent`) or an env var before this runs on any other machine (deploy, CI, teammate's laptop).
16. **`hard_interval.py` is a dead stub** — `add_collisions_via_intervals`'s body is just `pass`; either finish the Interval/NoOverlap rewrite of HC01/HC02 (would likely help solve time — CP-SAT's NoOverlap propagator is usually faster than pairwise reified disjunctions) or delete the file.
17. **Wizard ↔ solver bridge is CSV-only** — `backend/store.export_to_normalized` is the only link between the wizard's `data.json` and `sih_solver.preprocessing.load_all`; the solver still reads a folder of CSVs and doesn't know about `schema.py`/`validator.py` directly. Fine for now, but any future in-solver validation should reuse `validator.validate_all` rather than re-deriving checks.
18. **No `.gitignore`** — `__pycache__/*.pyc`, `.DS_Store`, and 80+ `uploads/{job_id}/` directories are all showing as tracked changes/untracked noise in `git status`. Add one before the next commit.

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
# legacy: POST /api/upload (ZIP/CSV), POST /api/solve/{job_id}?time_limit=120, GET /api/status/{job_id}, GET /api/download/{job_id}
# wizard: POST /api/jobs (new job) → GET/PUT /api/jobs/{id}/data/{dataset} (per-dataset CRUD, 19 datasets)
#         → POST /api/jobs/{id}/import/{dataset} (CSV/XLSX) → GET /api/jobs/{id} (validation + can_solve)
#         → POST /api/solve/{id} (422 if any BLOCKER) → GET /api/status/{id}
# frontend wizard UI: open http://localhost:8000/ (serves frontend/index.html, static assets at /frontend/*)
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
