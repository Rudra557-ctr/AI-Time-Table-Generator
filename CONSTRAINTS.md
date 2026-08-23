# Constraints Reference — SIH Smart Timetable Generator

**Last updated:** 2026-08-23  
**Dataset:** `SIH_Smart_Timetable_Dataset_CORRECTED.zip` (133 offerings → 370 sessions; lab-batch mode 149 → 386) — `sih_timetable_dataset_corrected/`  
**Solver:** OR-Tools CP-SAT (`cp_model.CpModel`). **Hard** = `model.Add(...)` (must hold). **Soft** = `model.Minimize(...)` only (never `Add`).

> Source of truth: `sih_solver/hard.py`, `sih_solver/full_model.py`, `sih_solver/soft.py`, `sih_solver/preprocessing.py`, `sih_solver/batches.py`, `sih_solver/dataset.py` for HC/SC (§1–§3 below); `sih_solver/schema.py`, `sih_solver/validator.py`, `backend/store.py` for the pre-solve data wizard/validation layer (§0, new). Line numbers below match current `main`.

---

## 0. Data Wizard & Validation Layer (new, Aug 23) — runs *before* HC/SC ever see the data

A separate, three-tier gate now sits in front of the CP-SAT model so bad data is rejected in the browser instead of causing a slow UNKNOWN/INFEASIBLE solve. This layer does not implement any HC/SC itself — it only decides whether the 19 CSV-shaped datasets are well-formed enough to attempt one.

| Tier | Checks | Severity | Implementation |
|------|--------|----------|-----------------|
| **L1 — Schema** | Per-field: required/blank, type (`int64`/`bool`/`object`/`time`/`date`), `min`/`max` range, `enum` membership (unless `allow_custom`), `pattern` (e.g. `slot_id` `^[A-Z]{3}_\d{4}$`), plus per-dataset cross-field rules (`end_time>start_time`, `weekly_hours == sessions_per_week × session_duration`, `max_hours_per_day <= max_hours_per_week`, `minimum_choices <= maximum_choices`, offering `(course_id,section_id)` uniqueness, composite-pair uniqueness for `faculty_courses`/`elective_group_courses`/`student_enrollments`). | Always **BLOCKER** | `sih_solver/schema.py:298` `validate_rows` |
| **L2 — Referential (FK)** | Every field with `"fk": "dataset.field"` in `SCHEMAS` must resolve to an existing value in the target dataset's column (built from `_fk_map()` over all 19 schemas). Caps detail issues at 20 per field + a summary "…and N more". | Always **BLOCKER** | `sih_solver/validator.py:40,80` `_fk_map`, `_l2_blockers` |
| **L3 — Solvability** | Required datasets present & non-empty (`required_datasets()`); every course used in an offering has ≥1 row in `faculty_courses` (eligible faculty) and ≥1 compatible room (`compatible_rooms_for_course`, reuses `preprocessing.py` logic); room capacity vs `student_count`; a contiguous same-day slot pair exists if any course/offering has `session_duration==2`; `faculty_availability`/`room_availability` empty → warn (HC06/HC07 effectively disabled); OAE/PCE enrollments with no `elective_groups` → warn. | **BLOCKER** or **WARNING** per check | `sih_solver/validator.py:143` `_l3_issues` |

**Downgrade rules in `validate_all`** (so the shipped synthetic dataset — which has known, solver-tolerated quirks — stays solvable): duplicate-row L1 blockers (offering dedup, composite-pair dedup) are downgraded to WARNING with "(auto-deduped on save/solve)"; "no compatible room" / "exceeds largest compatible room capacity" L3 blockers are downgraded to WARNING (handled by SC03's `>=` fallback, same as `C007` in §2). Per-tab `validate_single_dataset` does **not** apply these downgrades — it reports the strict versions so a user editing one tab still sees the real severity.

**Schema coverage:** all 19 datasets from `data_dictionary.csv` — `universities, departments, programs, academic_terms, time_slots, sections, students, rooms, courses, faculty, faculty_courses, faculty_availability, room_availability, course_offerings, elective_groups, elective_group_courses, student_enrollments, fixed_events, academic_rules`. Each schema entry also declares `auto_id` (UI auto-generation format, e.g. `C{idx:03d}`) and doubles as the source for CSV template generation (`template_csv`, header + one example row, used by `GET /api/templates/{dataset}` and `/api/templates/all.zip`).

**Per-job store:** `backend/store.py` persists the wizard's working copy as `uploads/{job_id}/data.json` (`{dataset: [row,...]}`), atomically written (tmp file + rename). `export_to_normalized(data, dest)` writes it out as `normalized/*.csv` in schema column order for the solver to consume; `import_from_normalized(src)` does the reverse for jobs created via the legacy upload path. This JSON store — not `normalized/*.csv` — is the source of truth for a job; `normalized/` is always derived from it before a solve.

**API surface (`backend/app.py`):** `GET /api/schema[/​{dataset}]`, `GET /api/templates/{dataset}` / `/api/templates/all.zip`, `POST /api/jobs` (creates empty store), `GET /api/jobs/{id}` (rows-per-dataset counts + `validate_all` result + solve status), `GET`/`PUT /api/jobs/{id}/data/{dataset}` (PUT runs `validate_single_dataset` and rejects with HTTP 422 + the validation payload if any BLOCKER), `POST /api/jobs/{id}/import/{dataset}` (CSV/XLSX upload → `adapter.infer_column_mapping` fuzzy header match → validate → merge into the store). `POST /api/solve/{id}` now calls `validate_all` first and refuses with 422 if `total_blockers > 0` — no more silent fallback to `/tmp` or repo-root CSVs (the legacy behavior is preserved only behind `?fill=true` on `/api/upload`, an explicit demo-mode opt-in).

**Frontend (`frontend/js/app.js`):** a 16-step wizard (`STEPS` array) — University → Departments → Programs → Terms → Time Slots → Rooms → Faculty → Sections → Students(+enrollments) → Courses → Assignments(faculty_courses) → Offerings → Availability(faculty+room) → Electives → Fixed Events → Advanced(academic_rules, read-only) → **Review & Solve**. `state.js` tracks the active job id and cached validation; `components.js` provides `tableEditor`/`matrixEditor` (grid-style editors, e.g. availability) and `badgeFor`/`issueList` (BLOCKER/WARNING pill rendering).

**Tests:** `tests/test_schema.py` (25), `tests/test_validator.py` (14), `tests/test_data_api.py` (17) — **56 passed**, run in <1s (pure-Python + FastAPI `TestClient`, no CP-SAT solve).

**Known gap:** this layer validates and stores data but the actual CP-SAT model (`sih_solver.preprocessing.load_all` → `full_model.build_full_hard_model`) still reads a plain folder of CSVs — `export_to_normalized` is the only bridge. `sih_solver/schema.py`/`validator.py` are not imported anywhere inside the solver core itself.

---

## 1. Hard Constraints (HC) — Must be satisfied

| ID | Name (Spec) | Description | Type | Status | Implementation |
|----|-------------|-------------|------|--------|----------------|
| **HC01** | Faculty no double-booking (+ daily cap) | Two sessions taught by same faculty cannot overlap (occupied sets disjoint, incl. duration-2 via `next_Start`). Daily cap `max_hours_per_day` from `faculty.csv` (e.g. `F027=3`, others `4`), weekly cap `max_hours_per_week` (HC16). | Hard | **FIXED & OPTIMAL** — was 22 violations (`F018 THU 7>4`) → 0 | `hard.py:51` `add_faculty_collision` (reified `Teacher[oid1]==Teacher[oid2]` → disjoint `Start`/`next_Start`); `full_model.py:84` `add_workload_constraints` (shared `day_var` via `AddElement`, `is_in_day`/`is_on_day` with `AddImplication`+`AddBoolOr`, `sum(dur*is_on_day) <= max_daily`) |
| **HC02** | Room no double-booking | Two sessions in same room cannot overlap (same occupied-set logic as HC01). | Hard | **FIXED & OPTIMAL** — was 2 violations `PL001 WED 10:00` (`S_CSE_1_A` vs `S_AIML_1_A`) → 0 | `hard.py:88` `add_room_collision` (reified `Room[oid1]==Room[oid2]` → disjoint) |
| **HC03** | Section no double-booking | Two sessions of same `section_id` cannot overlap. **Skips** alternative offerings in same synchronized elective group + same section (student picks one) via `alt_pairs`. | Hard | **FIXED & OPTIMAL** | `hard.py:153` `add_section_collision` (pairwise `Start`/`next_Start` disjoint, `is_alt` check); `preprocessing.py:233` `elective_alternative_pairs` (now filtered — see HC04) |
| **HC04** | Student-level OAE/PCE no overlap *(Item 4A)* | Per-student elective offering(s) must not collide with own section CORE nor with second elective. Same-section pairs already covered by HC03, so HC04 only adds **cross-section electives vs core** and **elective vs second elective**. | Hard | **ADDED & VERIFIED** — was 30 violations `O0143(C065) vs O0141(C060) S_AR_4_A FRI_1500` (both in `EG06`, `C060` also in `EG01`) → 0 | `hard.py:224` `add_student_collision` (helpers `hard.py:124` `_next_start_map`, `hard.py:137` `_add_disjoint_pair`); wired `full_model.py:205` |
| **HC06** | Faculty availability | `(Teacher, Start)` must be in `faculty_availability.csv` allowed pairs. | Hard | **Active** | `full_model.py:11` `add_availability_constraints` (`AddAllowedAssignments([Teacher[oid], Start[(oid,s)]], allowed)` via `preprocessing:valid_faculty_slots`) |
| **HC07** | Room availability | `(Room, Start)` must be in `room_availability.csv`. Building/room-type filtered via `compatible_rooms_by_course`. | Hard | **Active** | `full_model.py:38` (second half of `add_availability_constraints`, `valid_room_slots`) |
| **HC10** | Equipment / room-type / capacity *(Item 4B)* | `course.required_room_type` + `equipment_required` must be satisfied. **Vocabulary map** applied: `DATABASE_SYSTEMS→COMPUTERS`, `GPUS→COMPUTERS`, `MICROCONTROLLER→MICROCONTROLLERS`, `OSCILLOSCOPE→OSCILLOSCOPES`, `ROBOT_KIT→ROBOT_KITS`, `3D_PRINTERS→3D_PRINTER`, `DRAWING_BOARD→DRAWING_BOARDS`, `PHYSICS_EQUIPMENT_SET→PHYSICS_EQUIPMENT`, `AUDIO→AUDIO_SYSTEM`, `PROJECTOR_SCREEN→PROJECTOR`, etc. `C028 DATABASE_SYSTEMS` now maps to `EL001 COMPUTERS` (was 0 compatible); `C006→PL001` OK. Audit in `dataset.py` excludes synonyms. | Hard | **ADDED** | `preprocessing.py:17` `EQUIPMENT_SYNONYMS`, `preprocessing.py:98` mapping in `compatible_rooms_by_course` (`req_tokens = [EQUIPMENT_SYNONYMS.get(t,t) ...]`), `preprocessing.py:111` `compatible_rooms_by_course`, `dataset.py:11,77` audit (`room_equips` vs `EQUIPMENT_SYNONYMS`) |
| **HC12** | No repeat same course same section same day *(new)* | For `sessions_per_week>1 && session_duration==1`, at most one session of that `(section,course)` per day. Labs `duration==2` excluded. | Hard | **FIXED** — was 103 violations (`PROG101 S_AIML_1_A TUE 3×`) → 0 | `full_model.py:143` `add_no_repeat_same_course_same_day` (`AddAllowedAssignments` for `is_on_day`, `sum(bools) <=1` per `(section,course,day)`) |
| **HC13** | Synchronized electives *(Item 4C)* | Offerings of the **same course** across sections (cross-section common class) must share the same slot per session idx. **Per-(group_id, course_id)** groups (13 groups, not per-group). Full-group sync (EG01 16 offerings → 16 rooms) was **infeasible** (only 12 CLASSROOM rooms). Per-course is correct. | Hard | **ADDED & OPTIMAL** — 0 violations | `preprocessing.py:212` `synchronized_offering_groups` (per `(group,course)`), `hard.py:278` `add_synchronized_constraints` (`Start[(base,s)] == Start[(oid,s)]` per `req` group), wired `full_model.py:193,209` |
| **HC14** | Fixed events / blocked slots | `fixed_events.csv` scope `ALL` / `ALL_FACULTY` blocks `Start != blocked_indices` (duration-2 simplified). | Hard | **Active** | `full_model.py:54` `add_fixed_events` (`blocked_assignments`) |
| **HC16** | Faculty workload (weekly + daily) | See HC01 `add_workload_constraints` — weekly `sum(dur*is_assigned) <= max_weekly`, daily `sum(dur*is_on_day) <= max_daily` per faculty. | Hard | **FIXED & OPTIMAL** | `full_model.py:84` |
| **HC (alt_pairs)** | Elective alternative skip logic | Same synchronized group + same section → student picks one → HC03 skips disjoint. Now **filtered**: if a student is enrolled in both courses of a pair (e.g. `C060` in `EG01/EG02` + `C065` in `EG06`, `S_AR_4_A` students take both), that pair is **NOT** considered alternative (35 pairs removed, 53→18 `alt_pairs`). HC04 then ensures those 35 are globally disjoint. | Hard | **UPDATED** | `preprocessing.py:233` `elective_alternative_pairs(elective_groups, elective_group_courses, offerings, student_enrollments=None)` (now takes `student_enrollments`, builds `both_taken` set, skips), `full_model.py:196` passes `student_enrollments.csv` |

> **Other HC (not explicitly coded as separate functions but covered):** `HC05` etc. are soft or via preprocessing (e.g., `contiguous_slot_sets` for duration-2). All hard live in `model.Add`, never in `Minimize`.

### Hard — Lab Batches (Item 6)

| Feature | Detail | Status | Implementation |
|---------|--------|--------|----------------|
| **Batch threshold** | `BATCH_THRESHOLD = 40` — lab offering with `student_count > 40` and `requires_lab==True` split into two batch offerings `-B1`/`-B2` (halved `student_count`, keep `course_id`/`section_id`, same `faculty`/`room` logic). | **Active** | `batches.py:17` |
| **Split function** | `split_lab_offerings(offerings, courses_by_id, threshold)` → `149` offerings, `386` sessions (16→32 batches). Sequential batches ensured by HC02 room collision (no `PL002` added). | **OPTIMAL 45s** | `batches.py:22` |
| **Batch hard model** | `build_lab_batch_hard_model(root, threshold)` reuses `build_variables(offerings_override)` ( `model.py` gained `offerings_override` param) + same HC wiring. Tested `OPTIMAL`, 0 room double-booking. | **Active** | `batches.py:48`, `model.py:build_variables` |

---

## 2. Soft Constraints (SC) — Weighted `Minimize` only

> **Never** `model.Add(...)` — all reified vars are definitions, penalties only in `Minimize(sum terms)`. Weights reflect prompt priority.

| ID | Description | Penalty Definition | Weight | Priority | Status | Implementation |
|----|-------------|--------------------|--------|----------|--------|----------------|
| **SC02** | **Student gaps** (highest) — empty periods between first/last occupied per `(section, day)`. | `occupied[sec][day][p]` Bool → `has_any = OR(occupied)`, `first = min(p if occupied else 8)`, `last = max(p if occupied else 0)` via `AddMinEquality`/`AddMaxEquality`, `gaps = last - first +1 - sum(occupied)` if `has_any` else `0`. | **10** | 1 | **Active** — raw `91` (hinted FEASIBLE) was `86` (4-term) / `98` (hard only). Domain fix `first/last` `0..7→0..8` for empty days. | `soft.py:35` `_build_occupied`, `soft.py:107` SC02 block |
| **SC01** | **Faculty preference** — penalize non-preferred assignment when preferred exists (`faculty_courses.csv: preferred==True`). | `is_pref` Bool via `AddAllowedAssignments([Teacher[oid], is_pref], allowed_pref + allowed_not)`, `pref_terms = 1 - is_pref`. | **8** | 2 | **Active** — `72` non-preferred (was `51`). Now conditional on weight (`if weights.get("SC01_pref")`). | `soft.py:409` |
| **SC09** | **Workload balance** — `sum\|total - midpoint\|` per faculty, `mid=(min+max)//2` from `faculty.csv`. | `is_ass = (Teacher==fac)` reified, `total = sum(dur*is_ass)`, `abs_pen >= total-mid`, `abs_pen >= mid-total`. | **5** | 3 | **Active** — `150` (was `114`). Now conditional. | `soft.py:434` |
| **SC05** | **Excessive consecutive** — `3+` occupied periods per `(section,day)` (new, Item 5). | `triple = (occupied[p-1] AND occupied[p] AND occupied[p+1])` via `AddBoolAnd`/`AddBoolOr`. | **4** | 4 | **ADDED** — `147` | `soft.py:151` |
| **SC06** | **Spread same course across distinct days** — per `(section, course)` where `sessions_per_week>1 && duration==1` (new, Item 5). | `any_day = OR(affecting)` (now per-group sessions, not all `affecting`), `distinct = sum(any_day)`, `pen = max(0, len(sess_list) - distinct)`. | **4** | 4 | **ADDED** — `0` (fixed to use per-group `sess_list`, not all `affecting`) | `soft.py:170` |
| **SC08** | **Undesirable slots** — period `1` & `7` per day (new, Item 5). | `is_und = (Start in und_slots)` via `AddAllowedAssignments`, `total_und = sum(is_und)`. | **2** | 5 | **ADDED** — `106` | `soft.py:212` |
| **SC11** | **Building movement** — consecutive periods with different `building` per `(section,day)` (new, Item 5). `building` from `rooms.csv:building`. | `building_at[p] = sum(bld)` (gated: `bld==raw_bld if occ_b else 0` via `AddElement(Room, building_arr, raw_bld)`), `both = occupied[p] AND occupied[p+1]`, `diff = (building_at[p] != building_at[p+1])`, `move = both AND diff`. | **2** | 5 | **ADDED** — `108` (was INFEASIBLE before gating fix) | `soft.py:326` |
| **SC_facgaps** | **Faculty idle gaps** per `(faculty,day)` (new, Item 5 / SC03b). | Per faculty/day `occ_bools` via `is_ass = (Teacher==fac)` + `b_start = (Start==slot)` + `conj = is_ass AND b_start` → `MaxEquality(b, conds)`, then same `first/last/min/max` as SC02. Hoisted `is_ass` per `(oid,s,fac)` (was per `(day,period)` 35× blowup). Domain `first/last` `0..7→0..8`. | **2** | 5 | **ADDED** — `208` (was INFEASIBLE before domain fix) | `soft.py:233` |
| **SC03** | **Room wastage** (lowest) — `sum(capacity - enrolled)` per session (was ` ==`, now `>=`). | `cap_var` via `AddElement(Room, caps, cap_var)`, `waste >= cap - cnt`, `waste in 0..200` (so `waste = max(0, cap-cnt)` when minimized). `total_waste` domain `0..200*len` (was `0..10000` clipped). Now conditional. Fallback for `C007 WORKSHOP DRAWING_BOARDS` (65 students, no compatible room → any classroom, waste 0 if `cap<cnt`). | **1** | 6 | **Active** — `3740` (was `8355`, avg ~10/seat, vs `8605` post-HC04). Fixed `==`→`>=` and conditional. | `soft.py:467` |

**Total weighted objective (hinted FEASIBLE, 9 terms, `gen_hinted2.py`):** `7408` (`SC02:910 + SC05:588 + SC06:0 + SC08:212 + SC_facgaps:416 + SC11:216 + SC01:576 + SC09:750 + SC03:3740`).  
**Previous total (4 terms):** `10193` (`SC02:860 SC01:408 SC09:570 SC03:8355`) — not directly comparable (different hard `alt_pairs` and hinting).

**Shared helper:** `soft.py:35` `_build_occupied` → `occ[sec][day][period]` Bool + `affecting` (for `SC06`/`SC11` lookups). Built unconditionally (could be conditional on `SC02/SC05/SC06/SC11`).

**Soft wiring:** `soft.py:76` `add_soft_objective(model, Start, Teacher, Room, meta, weights=None→DEFAULT_WEIGHTS)` → `soft.py:489` `model.Minimize(sum(terms))` returns `penalties` dict; `soft.py:493` `apply_human_feedback` (tunes weights via comment, e.g. `"gap"` +2).

---

## 3. Implementation Status & Solver

| Build | Vars | Constraints | Time | Status | File |
|-------|------|-------------|------|--------|------|
| Hard only (HC01-16+HC12+HC04+HC13) | `165757` | `505125` | `150s`, 8 workers, retry seeds | **OPTIMAL** `106.9s` (90s sometimes UNKNOWN, 150s retry → OPTIMAL) | `full_model.py:185` `build_full_hard_model` |
| Hard + Soft (9 terms, hinted) | `536675` | `1.22M` | `120s`, 8 workers, hinted from hard | **FEASIBLE** `121.6s` (`obj 7408`, `bound 3030`) | `soft.py:76` |
| Hard + Soft (no hint) | same | same | `150s` | **UNKNOWN** (`obj 25888`, `bound 3030`, 0 integer solutions) | — |
| Lab batches | `~149` off, `386` sess | — | `90s` | **OPTIMAL** `45s` | `batches.py:48` |

> **Why hinted?** Soft is `536k` vars — needs hard solution as `AddHint` to find integer feasible quickly. Hard alone finds feasible; soft without hint finds LP bound but no integer solution in 150s.

**Tests (solver core):** `pytest tests/test_hard_fixes.py tests/test_preprocess.py tests/test_dataset.py tests/test_hard_core.py tests/test_hard_full.py tests/test_diagnose.py tests/test_soft.py tests/test_variables.py -q` → **45 passed**, 1 skipped (was 42; added `test_hc04`, `test_hc13`, `test_lab_batch_split` in `tests/test_hard_fixes.py:7,120,148`). Hard fixes `150s` retry, preprocess `10` tests, soft `3`.

**Tests (data wizard layer, new — see §0):** `pytest tests/test_schema.py tests/test_validator.py tests/test_data_api.py -q` → **56 passed** in <1s (25 schema, 14 validator, 17 data-api via FastAPI `TestClient`).

**Grand total: 101 tests.**

**Deliverables (regenerated via `/tmp/gen_hinted2.py`):**
- `timetables_generated/generated_timetable_fixed.csv` — 370 rows, hard **OPTIMAL**
- `timetables_generated/generated_timetable_soft.csv` — 370 rows, hard+soft hinted **FEASIBLE**
- `timetables_generated/generated_timetable_full.csv` — copy of soft
- `timetables_generated/S_*.csv` / `S_*.txt` — 16 sections × 7 periods `09-17` (lunch `13-14` free), `S_CSE_1_A.txt` etc.
- `timetables_generated/FIX_REPORT.md` — updated with solver status, penalties, fixes

---

## 4. How to Re-run

```bash
# 1. Ensure corrected dataset exists
unzip -o SIH_Smart_Timetable_Dataset_CORRECTED.zip -d /tmp  # → /tmp/sih_timetable_dataset_corrected

# 2. Tests (all)
python3 -m pytest tests/test_hard_fixes.py tests/test_preprocess.py -q  # 17 passed
python3 -m pytest tests/ -q  # 45 passed (~274s)

# 3. Hard only (as in FIX_REPORT)
python3 -c "from sih_solver.full_model import build_full_hard_model; from ortools.sat.python import cp_model; m,S,T,R,meta=build_full_hard_model(); s=cp_model.CpSolver(); s.parameters.max_time_in_seconds=150; s.parameters.num_search_workers=8; st=s.Solve(m); print(s.StatusName(st), s.WallTime())"

# 4. Soft hinted (as in gen_hinted2.py)
PYTHONPATH=. python3 -u /tmp/gen_hinted2.py  # hard 112s OPTIMAL → soft 121s FEASIBLE, writes timetables_generated/*.csv

# 5. Single soft terms (for debugging)
# python3 -c "from sih_solver.full_model import build_full_hard_model; from sih_solver.soft import add_soft_objective; ..."
```

---

## 5. File Map (quick reference)

```
sih_solver/preprocessing.py:17  EQUIPMENT_SYNONYMS (14 mappings)
sih_solver/preprocessing.py:111 compatible_rooms_by_course (with synonyms)
sih_solver/preprocessing.py:212 synchronized_offering_groups (per (group,course) 13 groups)
sih_solver/preprocessing.py:233 elective_alternative_pairs (filtered, takes student_enrollments)
sih_solver/model.py              build_variables(offerings_override) — Start/Teacher/Room
sih_solver/hard.py:51            add_faculty_collision
sih_solver/hard.py:88            add_room_collision
sih_solver/hard.py:153           add_section_collision (alt_pairs)
sih_solver/hard.py:224           add_student_collision (HC04)
sih_solver/hard.py:278           add_synchronized_constraints (HC13)
sih_solver/full_model.py:11      add_availability_constraints (HC06/HC07)
sih_solver/full_model.py:54      add_fixed_events (HC14)
sih_solver/full_model.py:84      add_workload_constraints (HC01/HC16, guard empty slot_to_idx)
sih_solver/full_model.py:143     add_no_repeat_same_course_same_day (HC12)
sih_solver/full_model.py:185     build_full_hard_model (wires all hard)
sih_solver/soft.py:17            DEFAULT_WEIGHTS (9 terms)
sih_solver/soft.py:35            _build_occupied
sih_solver/soft.py:107           SC02, 151 SC05, 170 SC06, 212 SC08, 233 SC_facgaps, 326 SC11, 409 SC01, 434 SC09, 467 SC03
sih_solver/soft.py:493           apply_human_feedback
sih_solver/batches.py:17,22,48   BATCH_THRESHOLD=40, split_lab_offerings, build_lab_batch_hard_model
sih_solver/dataset.py:11,77      EQUIPMENT_SYNONYMS audit
sih_solver/diagnose.py           solve_with_diagnosis
sih_solver/adapter.py:159        normalize_upload_folder, infer_column_mapping (generic upload / wizard import)
sih_solver/schema.py             SCHEMAS (19 datasets), get_schema, validate_rows (L1), template_csv, required/optional_datasets
sih_solver/validator.py          validate_all (L1+L2+L3), validate_single_dataset, _fk_map
sih_solver/review.py             generate_preview (human-loop soft-scoring preview)
sih_solver/hard_interval.py      add_collisions_via_intervals — UNFINISHED stub (body is `pass`), not wired in
backend/app.py:37                FastAPI: legacy /api/upload, /api/solve/{job_id}, /api/status, /api/download
                                  + wizard: /api/schema*, /api/templates/*, /api/jobs*, /api/jobs/{id}/data/{dataset}, /api/jobs/{id}/import/{dataset}
backend/store.py                 init_store/load_store/save_store (uploads/{job_id}/data.json), export_to_normalized, import_from_normalized
frontend/js/app.js               16-step wizard (STEPS), state.js/api.js/components.js
timetables_generated/            generated_timetable_fixed.csv / soft.csv / full.csv + S_*.csv/txt + FIX_REPORT.md
```

---

*This file is the single source of truth for constraints implemented till now. §0 (data wizard/validation) is a pre-solve gate, not an HC/SC — it never touches the CP-SAT model. For solver tuning, see `PLAN.md` and `timetables_generated/FIX_REPORT.md`.*
