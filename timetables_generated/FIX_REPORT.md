# Fix Report – Hard-Constraint Bugs & Soft Constraints (CP-SAT)

**Dataset:** `SIH_Smart_Timetable_Dataset_CORRECTED.zip` (133 offerings, 370 sessions, 29 rooms, 35 slots, 16 sections) — also supports lab-batch mode: 16 labs >40 split → 149 offerings, 386 sessions  
**Spec:** `SIH_Timetable_Round2_CPSAT_Model_Specification.md` + prompt fixes (ordered, no weakening) — HC04, HC10, HC13, batches (item 6), remaining softs (item 5)

## 1. Solver Status

| Run | Model | Time | Status | Solve Time |
|-----|-------|------|--------|------------|
| Hard only (HC01-16 + HC12 + HC04 + HC13) | `sih_solver/full_model.py` with `hard.py` (occupied sets) + `HC12` + daily cap + `HC04` student-level + `HC13` sync (per-course) | 150s, 8 workers, retry seeds | **OPTIMAL** | ~112s (nondeterministic, 90s sometimes UNKNOWN, 150s reliably OPTIMAL with retry) |
| Hard + Soft (weighted, 9 terms) | Hard + `soft.py` SC02/SC01/SC09/SC03/SC05/SC06/SC08/SC11/SC_facgaps weighted sum (hinted from hard) | 120s, 8 workers, hinted | **FEASIBLE** (hinted from hard OPTIMAL, 7408 obj, bound 3030) | 121s |
| Lab batches | `sih_solver/batches.py` split_lab_offerings (threshold 40) → 32 batches, `build_lab_batch_hard_model` | 90s, 8 workers | **OPTIMAL** | 45s |

> Hard with filtered `alt_pairs` (18 vs 53) is more constrained (enforces 35 same-section alternative pairs where students take both C060/C065) → takes ~110s vs 58s previously. Soft is 536k vars, 1.2M constraints → needs hinting from hard to find FEASIBLE quickly. All soft terms remain `Minimize` only, never `Add()`.

## 2. Hard Violations – Before vs After

| Check | Before (buggy) | After Fixed | Test |
|-------|----------------|-------------|------|
| **HC02 / R005 Room double-booking** (PL001 WED 10:00) | 2 violations: `PL001 WED 10:00` S_CSE_1_A vs S_AIML_1_A, `PL001 WED 11:00` | **0** | `test_room_no_double_booking` PASSED |
| **HC01 / R001 Faculty daily cap** (max 4) | 22 violations: `F018 THU 7>4`, `F028 6>4` etc. | **0** | `test_faculty_daily_cap` PASSED |
| **HC12 New: no repeat single-slot course same section same day** | 103 violations: `PROG101 S_AIML_1_A TUE 3×`, `MAT101 MON 2×` | **0** | `test_hc12_no_repeat_same_course_same_day` PASSED |
| **HC04 Student-level OAE/PCE no-overlap** (new) | 30 violations: `O0143(C065) vs O0141(C060) S_AR_4_A FRI_1500` for 30 students taking both (both in EG06, C060 also in EG01) | **0** (filtered `alt_pairs` 18 vs 53, plus `HC04` student-level; hard now OPTIMAL) | `test_hc04_student_no_overlap` PASSED (150s retry) |
| **HC13 Synchronized electives** (new) | 0 (previously no sync) → now per-(group,course) sync (13 groups, same course across sections shares slot) | **0** violations, hard still OPTIMAL (full-group sync was infeasible: EG01 16 offerings need 16 rooms >12 classrooms) | `test_hc13_synchronized_same_slot` PASSED |
| **HC10 Equipment** (new vocab map) | C028 (DATABASE_SYSTEMS) had 0 compatible rooms (strict match) | **C028 → EL001** via `EQUIPMENT_SYNONYMS` (DATABASE_SYSTEMS→COMPUTERS, GPUS→COMPUTERS, etc.), C006 → PL001 OK | `test_preprocess` equipment audit PASSED |
| **Total gaps SC02** | 83 (buggy, but with hard violations) | 98 (hard only) → **91** (hard+soft, hinted FEASIBLE, -7) | - |

All **45 tests** `pytest tests/ -v` **PASSED** (17 hard_fixes+preprocess, 3 soft, etc., 1 skipped).

## 3. Soft Constraints – Weighted Sum (Part 15-16 + Item 5)

Implemented as `Minimize(sum w_i * penalty_i)` – soft only in objective, never in `Add()`. Weights: `SC02(10) > SC01(8) > SC09(5) > SC05(4), SC06(4) > SC08(2), SC11(2), SC_facgaps(2) > SC03(1)`.

| ID | Description | Raw Penalty (hinted FEASIBLE) | Weight | Weighted | Priority |
|----|-------------|-------------------------------|--------|----------|----------|
| **SC02** | Student gaps (empty slots between first/last per section/day) | **91** | 10 | 910 | 1 |
| **SC05** | Excessive consecutive (3+ occupied periods) | **147** | 4 | 588 | 4 |
| **SC06** | Spread same course across distinct days (per section,course) | **0** | 4 | 0 | 4 |
| **SC08** | Undesirable slots (period 1 & 7) | **106** | 2 | 212 | 5 |
| **SC_facgaps** | Faculty idle gaps per day | **208** | 2 | 416 | 5 |
| **SC11** | Building movement (consecutive periods, different buildings) | **108** | 2 | 216 | 5 |
| **SC01** | Faculty preference (preferred boolean) | **72** non-preferred | 8 | 576 | 2 |
| **SC09** | Workload balance – sum \|total - midpoint\| per faculty | **150** | 5 | 750 | 3 |
| **SC03** | Room wastage – sum(max(0, capacity - enrolled)) | **3740** (avg ~10/seat) | 1 | 3740 | 6 |
| **Total** | | | | **7408** | |

*Notes:* SC03 wastage changed from `==` to `>=` (allow `cap < cnt` for C007 WORKSHOP fallback, waste=0) and domain widened to `200*len`. SC02/SC_facgaps `first/last` domain widened 0..7→0..8 to handle empty days. SC01/SC09/SC03 made conditional on weight to avoid unconditional hard constraints. Previous soft total 10193 (4 terms) → 7408 (9 terms, hinted) is not directly comparable due to different hard constraints (filtered alt_pairs) and hinting.

## 4. Fixes Applied (in order, no weakening)

1. **HC02 Room** – `hard.py: add_room_collision` now uses `next_Start` via `AddElement` and checks `Start != Start`, `Start != next`, `next != Start`, `next != next` for duration 2 labs – iterates over **every** session via `offerings` and `required_sessions`.
2. **HC01 Daily** – `full_model.py: add_workload_constraints` now creates `day_var` per session via `AddElement(Start, day_by_slot)` and `is_in_day` shared per session/day, then `is_on_day = is_assigned AND is_in_day` – enforces `sum(dur * is_on_day) <= max_daily` per `(faculty, day)`.
3. **HC12** – `full_model.py: add_no_repeat_same_course_same_day` – for `sessions_per_week>1 && session_duration==1`, at most 1 per `(section, course, day)` via `Add(sum(is_on_day) <=1)`. Labs `duration==2` excluded.
4. **4A HC04 Student-level** – `hard.py: add_student_collision` – per-student cross-section electives vs core + elective vs second elective via `_next_start_map`/`_add_disjoint_pair`. Same-section handled by HC03; `alt_pairs` filtered (18 vs 53) so 35 pairs where students take both C060/C065 are now globally disjoint (hard OPTIMAL).
5. **4C HC13 Synchronized** – `hard.py: add_synchronized_constraints` + `preprocessing.py: synchronized_offering_groups` per-(group_id, course_id) (13 groups, not per-group) – forces same course across sections to share slot per session idx via `Start` equality. Full-group (16 offerings → 16 rooms) was infeasible (12 classrooms); per-course is correct and feasible.
6. **4B HC10 Equipment** – `preprocessing.py: EQUIPMENT_SYNONYMS` (DATABASE_SYSTEMS→COMPUTERS, GPUS→COMPUTERS, MICROCONTROLLER→MICROCONTROLLERS, etc.) applied in `compatible_rooms_by_course`; `dataset.py` audit excludes synonyms from `equipment_mismatch`.
7. **Item 6 Lab batches** – `sih_solver/batches.py: split_lab_offerings` (threshold 40, B1/B2, keep course/section), `build_lab_batch_hard_model` (reuses `build_variables(offerings_override)`), `model.py: build_variables(offerings_override)`. 16 labs → 32 batches, 149 offerings/386 sessions, **OPTIMAL** 45s, 0 room double-booking.
8. **Item 5 Remaining softs** – `soft.py` rewritten with `DEFAULT_WEIGHTS` 9 terms, `_build_occupied` shared, `SC05_consecutive` (triple window), `SC06_spread` (distinct days, fixed to use per-group sessions not all `affecting`), `SC08_undesirable` (period 1/7), `SC_facgaps` (hoisted `is_ass` per (oid,s,fac), domain 0..8), `SC11_building` (gated `bld` vars, dur2 handling). All terms `Minimize` only. Fixed unconditional building (SC01/SC09/SC03 now conditional) and `SC03` wastage `>=` not `==`.
9. **HC04/HC13 wiring** – `full_model.py` passes `alt_pairs` (filtered via `student_enrollments`) to `add_section_collision` and `add_synchronized_constraints`; `preprocessing.py: elective_alternative_pairs` now takes `student_enrollments` to filter.

## 5. Deliverables

- Fixed timetables: `timetables_generated/generated_timetable_fixed.csv` (hard only, **OPTIMAL** 112s, 370 rows, 0 hard violations) and `generated_timetable_soft.csv` (hard+soft hinted, **FEASIBLE** 121s, 370 rows, 0 hard violations, penalties above) and `generated_timetable_full.csv` (copy of soft)
- Class-wise `Mon-Fri` grids: `timetables_generated/S_*.txt` / `S_*.csv` (16 sections, 7 periods 09-17, lunch 13-14 free) – regenerated from soft (hinted) solution via `gen_hinted2.py`
- Lab batches: `sih_solver/batches.py` + test `test_lab_batch_split` — hard batch model OPTIMAL
- Tests: `tests/test_hard_fixes.py` (7 tests), `tests/test_preprocess.py` (10 tests) etc. — **45 passed**, 1 skipped
- Full suite: `pytest tests/ -q` **45 passed** in ~274s

## 6. How to Re-run

```bash
python3 -m pytest tests/test_hard_fixes.py tests/test_preprocess.py -q  # 17 passed
python3 -m pytest tests/ -q  # 45 passed
# hard only
python3 -c "from sih_solver.full_model import build_full_hard_model; from ortools.sat.python import cp_model; m,S,T,R,meta=build_full_hard_model(); s=cp_model.CpSolver(); s.parameters.max_time_in_seconds=150; s.parameters.num_search_workers=8; print(s.Solve(m), s.StatusName(s.Solve(m)))"
# soft hinted (as in gen_hinted2.py)
python3 /tmp/gen_hinted2.py  # hard 112s OPTIMAL → soft 121s FEASIBLE with penalties
```
