# Fix Report – Hard-Constraint Bugs & Soft Constraints (CP-SAT)

**Dataset:** `SIH_Smart_Timetable_Dataset_CORRECTED.zip` (133 offerings, 370 sessions, 29 rooms, 35 slots, 16 sections)  
**Spec:** `SIH_Timetable_Round2_CPSAT_Model_Specification.md` + prompt fixes (ordered, no weakening)

## 1. Solver Status

| Run | Model | Time | Status | Solve Time |
|-----|-------|------|--------|------------|
| Hard only (HC01-16 + HC12) | `sih_solver/full_model.py` with fixed `hard.py` (occupied sets) + `HC12` + daily cap | 90s, 8 workers | **OPTIMAL** | ~58s |
| Hard + Soft (weighted) | Hard + `soft.py` SC02/SC01/SC09/SC03 weighted sum | 90s, 8 workers | **FEASIBLE** (optimal not proven within 90s, feasible found) | 90s |

> FEASIBLE is expected for full soft model with 370 sessions and 4 soft terms – CP-SAT found feasible solution improving objective, but needs >90s to prove optimality. Hard constraints are still enforced (soft never in Add()).

## 2. Hard Violations – Before vs After

| Check | Before (buggy) | After Fixed | Test |
|-------|----------------|-------------|------|
| **HC02 / R005 Room double-booking** (PL001 WED 10:00) | 2 violations: `PL001 WED 10:00` S_CSE_1_A vs S_AIML_1_A, `PL001 WED 11:00` | **0** | `test_room_no_double_booking` PASSED |
| **HC01 / R001 Faculty daily cap** (max 4) | 22 violations: `F018 THU 7>4`, `F028 6>4` etc. | **0** | `test_faculty_daily_cap` PASSED |
| **HC12 New: no repeat single-slot course same section same day** | 103 violations: `PROG101 S_AIML_1_A TUE 3×`, `MAT101 MON 2×` | **0** | `test_hc12_no_repeat_same_course_same_day` PASSED |
| **Total gaps SC02** | 83 (buggy, but with hard violations) | 98 (hard only) → **86** (hard+soft, -12) | - |

All 42 tests `pytest tests/ -v` **PASSED** (including 4 new hard-fix tests).

## 3. Soft Constraints – Weighted Sum (Part 15-16)

Implemented as `Minimize(sum w_i * normalized_penalty_i)` – soft only in objective, never in `Add()`.

| ID | Description | Raw Penalty (unweighted) | Weight | Weighted | Priority |
|----|-------------|--------------------------|--------|----------|----------|
| **SC02** | Student gaps (empty slots between first/last per section/day) | **86** gaps (was 98 hard only, 83 buggy) | 10 (highest) | 860 | 1 |
| **SC01** | Faculty preference (preferred boolean from `faculty_courses.csv`) – penalize non-preferred when preferred available | **51** non-preferred assignments | 8 | 408 | 2 |
| **SC09** | Workload balance – sum \|total - midpoint\| per faculty (mid=(min+max)/2) | **114** | 5 | 570 | 3 |
| **SC03** | Room wastage – sum(capacity - enrolled) | **8355** | 1 (lowest) | 8355 | 4 |
| **Total** | | | | **10193** | |

*Normalization:* Each term divided by its natural max (gaps max ~400, pref max 133, workload max ~40*10, wastage max ~370*100) before weighting – weights reflect true priority per prompt, not raw scale. Reported raw above, weighted sum is minimized.

## 4. Fixes Applied (in order, no weakening)

1. **HC02 Room** – `hard.py: add_room_collision` now uses `next_Start` via `AddElement` and checks `Start != Start`, `Start != next`, `next != Start`, `next != next` for duration 2 labs (PL001 etc.) – iterates over **every** session via `offerings` and `required_sessions`, not just theory sessions.
2. **HC01 Daily** – `full_model.py: add_workload_constraints` now creates `day_var` per session via `AddElement(Start, day_by_slot)` and `is_in_day` shared per session/day, then `is_on_day = is_assigned AND is_in_day` with `AddImplication` + `AddBoolOr` – enforces `sum(dur * is_on_day) <= max_daily` per `(faculty, day)` using `faculty.csv` per-faculty caps (F027 max 3, others 4).
3. **HC12** – `full_model.py: add_no_repeat_same_course_same_day` – for `sessions_per_week>1 && session_duration==1`, at most 1 per `(section, course, day)` via `Add(sum(is_on_day) <=1)` where `is_on_day` is `Start in day_slots`. Labs `duration==2` explicitly excluded.
4. **Soft** – `soft.py` weighted sum `SC02>SC01>SC09>SC03` as above, normalized, live only in `Minimize`. Added unit tests for each.

## 5. Deliverables

- Fixed timetables: `timetables_generated/generated_timetable_fixed.csv` (hard only, OPTIMAL, 370 rows, 0 hard violations) and `generated_timetable_soft.csv` (hard+soft, FEASIBLE, 0 hard violations, gaps 86)
- Class-wise `Mon-Fri` grids: `timetables_generated/S_*.txt` / `S_*.csv` (16 sections, 7 periods 09-17, lunch 13-14 free) – regenerated from soft solution
- Tests: `tests/test_hard_fixes.py` – 4 tests for the prompt's validation checks
- Full suite: `42 passed`

## 6. How to Re-run

```bash
python3 -m pytest tests/test_hard_fixes.py -v  # room, daily, HC12, soft
python3 /tmp/run_fixed_full.py  # hard only, 90s, reports 0 violations
python3 /tmp/run_soft.py        # hard+soft, 90s, reports per-SC penalties
```
