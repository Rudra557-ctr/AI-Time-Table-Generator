# SIH Smart Timetable — Round 1: Problem Understanding, Dataset Audit & Constraint Discovery

**Scope of this document:** analysis only. No implementation, no OR-Tools/CP-SAT code. All findings below were produced by directly inspecting the uploaded ZIP (`sih_timetable_dataset/`, 24 files) and the SIH problem statement (GGSIPU2627), not by assuming a schema.

---

## PART A — PROJECT UNDERSTANDING

### A1. What the system must solve
GGSIPU2627 asks for an AI-based system that automatically generates **conflict-free, optimized weekly academic timetables** for a multi-program university (USAR, GGSIPU) operating under **NEP 2020**. The core difficulty stated explicitly: four B.Tech programmes **share** a limited pool of classrooms, specialised labs, workshops and faculty; students pick **Program Core Electives (PCE)** and **Open Area Electives (OAE)** *across* programmes; lab batches must be split/rotated; guest/visiting faculty are available only on fixed days; and any single change cascades through the rest of the timetable.

### A2. Inputs (as stated)
University academic data, course catalog, faculty information, classroom/lab resource data, student enrollment data, NEP 2020 curriculum structures, academic regulations. (The uploaded dataset instantiates these as 20 relational CSVs — see Part B.)

### A3. Required output
A conflict-free schedule per section/faculty/room, exposed through: an admin dashboard, a student/faculty timetable portal, automated conflict detection, modification suggestions, and dynamic/regenerable updates when inputs change. The problem statement does **not** specify an output file format (e.g. grid, JSON, iCal) — that is an implementation decision, not a given requirement.

### A4. Entities involved
University → Department → Program → Section (year + branch) → Student.
Course → Course Offering (course × section) → Session (instances of a required weekly session count).
Faculty (with department, designation, employment type, workload limits) — linked to courses via an *eligibility* table, not a 1:1 assignment.
Room/Resource (type, capacity, equipment).
Time Slot (day + period).
Elective Group (OAE/PCE, with synchronization flag).
Fixed Event (institution-wide blocked time).
Academic Rule (global default constraint values).

### A5. Problems with the manual process (explicit)
Weeks of senior-faculty time consumed each semester; clashes are discovered only **after** classes begin, i.e. the manual process cannot pre-validate feasibility; NEP flexibility (cross-program electives, multiple entry-exit) makes manual coordination across four programmes and two campuses (Dwarka + East Delhi) especially hard; every edit cascades and forces re-checking by hand.

### A6. Optimization goals (explicit)
Conflict-free schedules; maximised resource utilization; support for flexible/interdisciplinary curricula; minimised conflicts generally. The statement does **not** enumerate a weighted objective function or give numeric targets (e.g. "minimize gaps by X%") — any weighting scheme we build is a design choice, not an SIH requirement.

### A7. Requirements that are EXPLICIT in the SIH statement
- Must be conflict-free (faculty, room, section/student).
- Must support 4 programmes sharing rooms/labs/faculty.
- Must support OAE/PCE electives chosen across programmes.
- Must support lab batch splitting/rotation.
- Must support faculty with restricted (fixed-day) availability.
- Must maximise resource utilization.
- Must provide conflict detection, modification suggestions, dynamic updates (i.e. re-solve on change, not just a one-shot generator).
- Must be built with a CSP/optimization approach (GA, RL, CP, ILP or hybrid — technology choice is open, not mandated to be CP-SAT specifically; CP-SAT/OR-Tools is only listed as one allowed tool).

### A8. Requirements that are ASSUMPTIONS needing confirmation
Everything below appears **only** in the synthetic dataset or in common scheduling practice, not in the SIH text itself, and should be confirmed with an actual university stakeholder before being treated as binding:
- Exact numeric limits: max 4 hours/day, max 18 hours/week, min hours/week per faculty (`academic_rules.csv`, `faculty.csv`).
- The specific 7-periods/day × 5-day slot grid with a 13:00–14:00 lunch break.
- The exact room/equipment taxonomy (7 room types, per-room equipment tags).
- The rule that OAE/PCE choices are "synchronized" (`elective_groups.csv.synchronized=True`), i.e. all students of a chosen elective must sit it at the same time.
- Whether faculty assignment should be solver-chosen or pre-fixed (dataset explicitly models it as **open** — see Part J).
- Whether minimum faculty weekly hours (`min_hours_per_week`) is a binding HR rule or just a workload-balancing preference.

I have **not** promoted any of A8 to "official requirement" status anywhere below — each candidate constraint in Part D/M is labeled with its true provenance.

---

## PART B — DATASET ARCHITECTURE

24 files were found in the ZIP; 20 are relational CSVs, 1 is a data dictionary, 3 are documentation/validation notes (`README.md`, `docs_constraint_discovery_prompt.md`, `scheduling_validation_notes.md`) which were also read and folded into this analysis.

| File | Rows (excl. header) | Key columns | Primary key | Foreign keys → | Purpose |
|---|---|---|---|---|---|
| `universities.csv` | 1 | university_id, name, campus, academic_year | university_id | — | Top-level institution record |
| `departments.csv` | 5 | department_id, department_name | department_id | — | Academic departments (5: CSE, ECE, and others hosting shared courses) |
| `programs.csv` | 4 | program_id, program_code, program_name, department_id, degree, duration_years | program_id | department_id → departments | 4 B.Tech programmes: CSE, ECE, AIML, AR (Robotics) |
| `academic_terms.csv` | 1 | term_id, academic_year, term_type, start/end date | term_id | — | Single active term (ODD 2026-27) |
| `sections.csv` | 16 | section_id, program_id, year, section_name, student_count | section_id | program_id → programs | 1 section per (program × year) = 4 programs × 4 years = 16 |
| `students.csv` | 1000 | student_id, student_name, program_id, branch, year, section_id | student_id | program_id, section_id | Individual students, each pinned to exactly one section |
| `courses.csv` | 65 | course_id, course_code, name, department_id, course_type (THEORY/LAB/WORKSHOP), course_category (CORE/OAE/PCE/INTERDISCIPLINARY/SKILL), credits, weekly_hours, sessions_per_week, session_duration, requires_lab, required_room_type, min_room_capacity, equipment_required | course_id | department_id → departments | Course catalog with intrinsic scheduling requirements |
| `course_offerings.csv` | 144 | offering_id, course_id, section_id, required_sessions, session_duration, student_count | offering_id | course_id → courses, section_id → sections | **The actual thing the solver schedules** — a course delivered to a specific section, with how many sessions/week and how many students |
| `faculty.csv` | 40 | faculty_id, name, department_id, designation, employment_type (PERMANENT/VISITING/ADJUNCT), max_hours_per_week, max_hours_per_day, min_hours_per_week | faculty_id | department_id → departments | Faculty roster with **per-individual** workload caps (overrides any global default) |
| `faculty_courses.csv` | 777 | faculty_id, course_id, qualification_level, preferred | (faculty_id, course_id) | faculty_id → faculty, course_id → courses | **Eligibility**, not assignment — a course can have many eligible faculty, a faculty can be eligible for many courses |
| `faculty_availability.csv` | 1400 | faculty_id, slot_id, available, preference_score | (faculty_id, slot_id) | faculty_id → faculty, slot_id → time_slots | Full slot-level grid: every faculty has a row for all 35 slots |
| `rooms.csv` | 29 | room_id, room_name, building, floor, room_type, capacity, has_projector, has_computers, has_ac, equipment | room_id | — | 7 room types: CLASSROOM(12), COMPUTER_LAB(6), LECTURE_HALL(4), ELECTRONICS_LAB(2), ROBOTICS_LAB(2), WORKSHOP(2), PHYSICS_LAB(1) |
| `room_availability.csv` | 1015 | room_id, slot_id, available | (room_id, slot_id) | room_id, slot_id | Full grid: every room × every slot (29 × 35) |
| `time_slots.csv` | 35 | slot_id, day, period_number, start_time, end_time, is_break | slot_id | — | 5 days × 7 periods (09–13, 14–17); the 13:00–14:00 lunch hour is simply **absent** from the grid rather than flagged `is_break=True` |
| `student_enrollments.csv` | 7250 | student_id, course_id, enrollment_type (CORE/OAE/PCE) | (student_id, course_id) | student_id → students, course_id → courses | Individual, not section-level, enrollment — needed for elective conflict checking |
| `elective_groups.csv` | 6 | elective_group_id, group_name, elective_type (OAE/PCE), year, program_scope, minimum/maximum_choices, synchronized | elective_group_id | — | 2 OAE groups (year 3, year 4, open to ALL programs) + 4 PCE groups (one per program, year 4) |
| `elective_group_courses.csv` | 16 | elective_group_id, course_id | (elective_group_id, course_id) | both → respective tables | Which courses satisfy which elective group — **note: some courses appear in more than one group** (see Part I) |
| `fixed_events.csv` | 2 | event_id, event_name, day, start_time, end_time, scope | event_id | — | Weekly faculty meeting (Mon 12–13, ALL_FACULTY) + common lunch (13–14, ALL) |
| `academic_rules.csv` | 9 | rule_id, rule_name, rule_type (HARD/SOFT), value, active | rule_id | — | Global default rule values (max/min hours, simultaneity limits) |
| `academic_rules_candidate.csv` | 16 | same shape | rule_id | — | A superset draft list (looks like the dataset author's own first pass at Part D of this exact exercise) |
| `data_dictionary.csv` | 107 | dataset, field, dtype, required, description | — | — | Field-level documentation for all datasets |
| `validation_report.csv` / `validation_summary.csv` | 16 / 1 | check, actual, expected, status | — | — | The dataset author's **own** self-check — I independently re-ran these checks rather than trusting them at face value (Part C) |

### Relational architecture
```
UNIVERSITY → DEPARTMENT → PROGRAM → SECTION → STUDENT
                                       ↓
COURSE → COURSE_OFFERING (course × section) ← SECTION
   ↓
FACULTY_COURSES (eligibility, many-to-many) → FACULTY
   ↓
FACULTY_AVAILABILITY (faculty × slot)
                                       ↓
STUDENT → STUDENT_ENROLLMENTS (student × course) → ELECTIVE_GROUPS (OAE/PCE)
                                       ↓
COURSE_OFFERING → ROOM (via type/capacity/equipment) → ROOM_AVAILABILITY (room × slot)
                                       ↓
TIME_SLOT ← FIXED_EVENTS (blocks slots institution-wide)
```
Confirmed by direct inspection: **no** course has exactly one eligible faculty baked in as a foreign key — `faculty_courses.csv` is a genuine many-to-many bridge table (mean 12 eligible faculty per course, mean 19 courses per faculty). The "COURSE → ONE PROFESSOR" assumption is correctly absent from this dataset, matching the prompt's instruction.

---

## PART C — DATASET AUDIT (independently re-verified, not taken from `validation_report.csv`)

| # | Check | Result | Status |
|---|---|---|---|
| 1 | Student count | 1000, all unique IDs | PASS |
| 2 | Faculty count | 40, all unique IDs | PASS |
| 3 | Section count | 16 = 4 programs × 4 years, exactly 1 section per (program, year) | PASS |
| 4 | Student → section consistency | `sections.student_count` matches actual `COUNT(students)` per section for all 16 sections | PASS |
| 5 | Section → program/year consistency | Every section's program_id/year is internally consistent with its own student rows | PASS |
| 6 | Course offering → course/section referential integrity | 0 invalid course_id or section_id references in 144 offerings | PASS |
| 7 | Course → eligible faculty | 0 courses with zero eligible faculty (min 3, max 18 per course) | PASS |
| 8 | Multiple faculty per course / faculty teaching multiple courses | Confirmed genuinely many-to-many (mean 12 faculty/course, mean 19 courses/faculty, max 59 for one faculty) | PASS — but see note below |
| 9 | Faculty availability completeness | All 40 faculty have all 35 slot rows (1400 = 40×35); "available=True" ranges from 6 to 35 per faculty | PASS |
| 10 | Room availability completeness | All 29 rooms have all 35 slot rows (1015 = 29×35) | PASS |
| 11 | Room capacity vs offering size | No offering exceeds the capacity of every candidate room of the right type | PASS |
| 12 | Room type compatibility (by `room_type` only) | Every course requiring a specialised room type (LAB/WORKSHOP) has ≥1 room of that exact type with sufficient capacity | PASS |
| 13 | **Equipment requirement matching (by `equipment_required` string)** | **5 of 10 lab courses (C017 DBMS Lab, C024 Digital Electronics Lab, C039 ML Lab, C046 Robotics Lab I, C050 Robotics Lab II) have `equipment_required` values that do not literally appear in ANY room's `equipment` field** (e.g. course asks for `"DATABASE_SYSTEMS"`, `"GPUS"`, `"ROBOTICS"`; rooms are tagged `COMPUTERS,PROJECTOR`, `ROBOT_KITS,3D_PRINTER`, etc.) | **FAIL if `equipment_required` is enforced as a literal hard filter** |
| 14 | Duplicate course_offerings | **16 offering rows are exact duplicates of another offering on the same (course_id, section_id) pair** — affects C054, C055 (4 sections each) and the cross-listed elective courses C058/C060/C061 (1 section each). Same required_sessions/duration/student_count in both copies. | **FAIL** |
| 15 | Elective offering enrollment vs `student_count` field | 16 offerings (exactly the duplicated ones above) show `actual enrolled = 2× student_count`, because enrollments were counted once against a course that has two identical offering rows | **FAIL (consequence of #14)** |
| 16 | CORE enrollment ↔ offering consistency | All 6500 CORE enrollments match an existing offering in the student's own section | PASS |
| 17 | Elective (OAE/PCE) enrollment ↔ offering consistency | All 750 elective enrollments match an offering that exists for the student's own section | PASS |
| 18 | Elective cross-listing | C058, C060, C061 each appear in **both** an OAE group and a PCE group simultaneously (e.g. C061 is in EG01/EG02 OAE year 3/4 *and* EG04 ECE PCE) — same underlying course, different labels for different students | WARNING — must be modeled explicitly, not an error, but easy to mis-handle (see Part I) |
| 19 | Fixed event vs faculty/room availability pre-blocking | `EV001` (Mon 12:00–13:00, scope ALL_FACULTY) overlaps exactly the regular teaching slot `MON_1200`. Yet 32 of 40 faculty and 28 of 29 rooms show `available=True` for `MON_1200` — the fixed event is **not** pre-baked into the availability tables | WARNING — solver must apply `fixed_events.csv` as its own hard filter, cannot rely on availability tables alone |
| 20 | Consecutive-slot contiguity for multi-period sessions | All 10 lab courses need 1 session of 2 consecutive periods/week (`session_duration=2`). Slot grid has a period-number gap that is **not** time-contiguous: `MON_1200` (12:00–13:00, period 4) and `MON_1400` (14:00–15:00, period 5) are adjacent in `period_number` but separated by the 1-hour lunch break in wall-clock time | WARNING — "consecutive" must be defined by actual start/end time adjacency, not by `period_number+1`, or the solver could silently place a 2-hour lab across the lunch gap |
| 21 | Faculty workload aggregate feasibility | Total weekly demand = 411 session-hours across all offerings; total faculty capacity = 676 hours/week (sum of `max_hours_per_week`) | PASS at aggregate level (healthy 1.6× slack) |
| 22 | Restricted-availability faculty | 4 PERMANENT faculty (F004, F016, F017, F023 — all Professor/Assoc. Professor, not guest/visiting) show only 6 of 35 slots available, all on Tue/Thu afternoons | WARNING — unusual for permanent staff but internally consistent (their `min_hours_per_week=2` fits inside 6 slots); flag for confirmation with the university whether this is intentional |
| 23 | Self-reported `validation_summary.csv` vs actual data | The dataset's own summary row claims `rooms=27`; actual unique `room_id` count is **29** | WARNING — the shipped validation artifact is stale/inconsistent with the data it describes; don't trust it as ground truth (this is why independent re-audit was done) |
| 24 | Time slot grid | 35 slots = 5 days × 7 periods; no `is_break=True` row exists (lunch is modeled by omission, not by a flag) | PASS, just noted as a modeling convention |
| 25 | Courses/offerings with zero compatible rooms (by type+capacity) | 0 | PASS |
| 26 | Courses with zero eligible faculty | 0 | PASS |
| 27 | Note on eligibility breadth (from #8) | One faculty is eligible for 59/65 courses — plausible for a synthetic generator but worth a sanity check with a real institution, since real eligibility is usually narrower per individual | INFO / not a data error |

### DATASET STATUS: **NEEDS CORRECTION**
Rationale: two FAIL-level issues (#13 equipment-vocabulary mismatch, #14/#15 duplicate `course_offerings` rows) would either make 5 lab courses spuriously infeasible or silently double-book/double-count sessions for 8 offering pairs if fed to a solver as-is. Recommended fixes, in order of preference:
- **#14/#15 (duplicates):** fix in the dataset — de-duplicate `course_offerings.csv` on (course_id, section_id) before any solving; this is a data-generation bug, not something the solver should "work around."
- **#13 (equipment):** fix in the dataset by aligning `courses.equipment_required` vocabulary with `rooms.equipment` vocabulary, **or** handle in the solver by treating `required_room_type` + `min_room_capacity` as the authoritative hard filter and demoting `equipment_required` to an informational/soft field until the vocabularies are reconciled. I recommend the solver-side fallback for Round 1 so the equipment mismatch doesn't block progress, while flagging it for a data fix.
- Everything else (#18, #19, #20, #22, #23) is a **modeling note**, not a data defect — the solver's constraint logic needs to account for it, but no CSV values need to change.

---

## PART D–G — CANDIDATE CONSTRAINT DISCOVERY

Methodology: every candidate constraint below was derived from (a) an explicit line in the SIH problem statement, (b) a field that exists in the dataset and its `data_dictionary.csv` description, or (c) a cross-file relationship verified in Part C. Nothing below is invented without a traceable source, and each row states which of those it is. Full consolidated tables (with ID/Type/Priority/Rule/Reason/Entities/Required Data/Confidence/Confirmation) are in **Part M** to avoid duplicating the same rows twice — Parts E/F/G below give the narrative grouping the SIH prompt asked for.

### PART E — Hard constraints (narrative)
1. **Faculty collision** — a faculty member cannot be in two sessions at the same slot, *regardless of which programme/year/branch* those sessions belong to (this must be checked globally across all 16 sections at once, not per-year — see Part H).
2. **Room collision** — a room cannot host two sessions at the same slot.
3. **Section collision** — a section's students (as a block, for CORE courses) cannot have two sessions at the same slot.
4. **Student-level collision** — for OAE/PCE/cross-listed courses, the same *individual* student can be pulled from a home section into a different room/group; section-level checking alone is insufficient here (see Part I).
5. **Faculty eligibility** — only faculty present in `faculty_courses.csv` for that `course_id` may be assigned.
6. **Faculty availability** — only slots marked `available=True` in `faculty_availability.csv`.
7. **Room availability** — only slots marked `available=True` in `room_availability.csv`.
8. **Room capacity** — room `capacity` ≥ offering `student_count`.
9. **Room type compatibility** — room `room_type` = course `required_room_type`.
10. **Equipment** — conditionally hard, pending the Part C #13 data-vocabulary fix; recommended interim treatment: soft/informational.
11. **Required weekly sessions** — each offering must receive exactly `required_sessions` sessions of length `session_duration`.
12. **Session duration / consecutive periods** — multi-period sessions must occupy truly time-contiguous slots (see Part C #20 caveat).
13. **Fixed events** — no session may be scheduled where it overlaps a `fixed_events.csv` window for its scope (e.g. all faculty blocked Mon 12–13; everyone blocked 13–14).
14. **Elective requirement fulfilment** — every student's chosen OAE/PCE course must appear, without collision, in that student's personal timetable.
15. **Shared/interdisciplinary courses** — the 18 courses offered to more than one section (including the OAE/PCE cross-listed ones) must be scheduled so that **all** enrolled students across **all** sections can attend without collision; if `synchronized=True`, all sections sharing that elective must get the identical slot(s).
16. **Faculty workload limits** — per-faculty `max_hours_per_day` / `max_hours_per_week` from `faculty.csv` (which overrides the global default in `academic_rules.csv` when they differ — e.g. VISITING/ADJUNCT faculty are capped at 10–12 hrs/week, not 18).

### PART F — Soft constraints (narrative)
Faculty preferred slots (`preference_score` in `faculty_availability.csv`); minimizing student timetable gaps; minimizing faculty idle gaps; balancing faculty workload across the eligible pool (not just meeting the ceiling); avoiding excessive back-to-back sessions; spreading a course's multiple weekly sessions across different days; minimizing room-capacity wastage (don't put a 20-student elective in a 70-seat hall if a right-sized room is free); avoiding undesirable slots (e.g. first/last period) if the university expresses such a preference; reducing timetable fragmentation (prefer contiguous blocks); meeting a faculty's `min_hours_per_week` as a soft workload-fairness target rather than a hard floor (pending confirmation — see A8).

### PART G — Conditional constraints (narrative)
- IF `requires_lab=True` → room must match `required_room_type`.
- IF `session_duration > 1` → must occupy contiguous slots (respecting the lunch-break time-gap, not just period-number adjacency).
- IF a course has multiple eligible faculty → the optimizer may choose among them (decision variable); IF only one is eligible → it is effectively fixed.
- IF a faculty has restricted availability → only their `True` slots are usable, which for 4 faculty in this dataset is just 6 of 35 slots.
- IF a student selects an elective → it must appear in their personal timetable without collision with anything else they're enrolled in.
- IF a course is shared across multiple sections/programmes (18 such courses here) → shared-resource and, where `synchronized=True`, shared-slot constraints apply.
- IF a course is cross-listed in more than one elective group (C058, C060, C061) → the single underlying offering must simultaneously satisfy both groups' non-collision requirements for the different student populations drawing on it.
- IF the equipment vocabulary between a course's requirement and a room's tags cannot be reconciled → fall back to room-type + capacity as the authoritative filter (interim data-quality policy, not a permanent rule).

---

## PART H — Cross-year / cross-branch conflicts

Direct evidence that this must be solved **university-wide, not per year**:
- `faculty_courses.csv` shows real faculty teaching across course pools spanning multiple years/branches (mean 19 courses/faculty; several faculty are eligible for courses belonging to more than one programme's core curriculum).
- 18 of 65 courses are offered to more than one section — these sections span different programmes and, in the OAE/PCE cases, different years (e.g. `EG01` year-3 OAE vs `EG02` year-4 OAE both draw on `C058–C061`).
- Rooms and specialised labs (only 2 electronics labs, 2 robotics labs, 1 physics lab, 2 workshops university-wide) are shared by all four programmes and all four years simultaneously — a robotics lab booked for a Year-3 AR section is unavailable for a Year-4 AR section or a Year-2 interdisciplinary robotics elective at the same slot.
- `fixed_events.csv` scope `ALL_FACULTY` / `ALL` applies uniformly regardless of year/branch.

**Conclusion:** the model must treat faculty-id, room-id, and (for electives) student-id as the true collision keys across the *entire* 16-section, 4-branch, 4-year university simultaneously. Solving year-by-year or branch-by-branch independently would miss exactly the cross-cutting collisions the SIH statement calls out as the central difficulty (shared rooms/labs/faculty, cross-programme electives).

---

## PART I — Student-level conflicts

`student_enrollments.csv` (7250 rows) links individual students, not sections, to courses, with `enrollment_type` = CORE (6500), OAE (500), PCE (250).

- **Section-level collision checking is sufficient for CORE courses**, because every student in a section shares the identical CORE course list (verified: all 6500 CORE enrollments match an offering in the student's own section — no exceptions).
- **Section-level checking is NOT sufficient for OAE/PCE**, because:
  - A student's elective choice draws them into a course whose offering may be shared with other sections/years (e.g. `C058` appears as an OAE option for both year-3 and year-4 students university-wide, and separately as a PCE option for AIML year-4 students specifically — same course, different populations, potentially the same or different scheduled offering).
  - Two electives chosen by the same student could, in principle, be scheduled at the same slot even though neither section-level nor faculty/room-level checks would catch it, because the students pulled into those sessions are not the section's full roster.
- **Recommendation:** run section-level collision checking for CORE offerings (cheap, sufficient) **and** student-level collision checking specifically for the 750 OAE/PCE enrollment rows and any course flagged `course_category ∈ {OAE, PCE, INTERDISCIPLINARY, SKILL}` (8 such courses here). This keeps the model tractable (no need for per-student variables on 6500 CORE rows) while still closing the real collision gap the SIH statement is worried about.

---

## PART J — Faculty assignment: should it be a decision variable?

| | **A. Faculty pre-assigned before solving** | **B. Faculty selected by the optimizer** |
|---|---|---|
| Fits the dataset | No — `faculty_courses.csv` is explicitly a many-to-many eligibility table (mean 12 eligible faculty/course); there is no pre-existing course→faculty assignment column anywhere in the dataset | Yes — this is exactly what the eligibility table is built to support |
| Fits the SIH statement | Partially — the statement doesn't forbid pre-assignment, but its stated goal ("maximise resource utilization", handle shared faculty across 4 programmes) implies the system should be able to pick the best available eligible faculty, not just slot in a fixed name | Yes — directly supports "maximise resource utilization" and workload balancing (Part F) |
| Workload balancing (SC04) | Hard to achieve — a fixed assignment can leave some eligible faculty overloaded and others idle | Natural — the optimizer can distribute load across the pool subject to `max_hours_per_week`/`max_hours_per_day` |
| Feasibility risk | Higher — a bad pre-assignment (e.g. always picking the first eligible faculty) could create unnecessary conflicts against that person's narrow availability (recall: 4 faculty have only 6/35 available slots) | Lower — solver can route around a restricted-availability faculty by choosing someone else eligible |
| Explainability / auditability | Simpler to explain a fixed roster | Needs a report showing *why* a given faculty was picked (e.g. preference_score, workload balance) — an extra deliverable but the SIH statement already asks for "modification suggestions" and dashboards, which implies this is expected anyway |

**Recommendation: B — treat faculty assignment as a decision variable**, constrained to the eligible set (`faculty_courses.csv`) for each offering, subject to availability and workload caps, with `preferred=True`/`preference_score` used as a soft objective term. This matches both the dataset design (`docs_constraint_discovery_prompt.md` explicitly states "Faculty assignment may be a decision variable... A fixed assignment may also exist in a future version") and the SIH goal of maximising resource utilization. Recommend keeping the model flexible enough to accept a partial/fixed pre-assignment as an *optional override* later (e.g. a dean manually pins a specific course to a specific professor), since the dataset's own documentation flags that as a plausible future need.

---

## PART K — Labs and resources

- **7 room types**, very unevenly distributed: CLASSROOM(12), COMPUTER_LAB(6), LECTURE_HALL(4), ELECTRONICS_LAB(2), ROBOTICS_LAB(2), WORKSHOP(2), **PHYSICS_LAB(1)** — the single physics lab is a real bottleneck: every physics-lab session across all 4 programmes' Year-1 cohorts must funnel through one room.
- 10 courses require a lab/workshop, all with `session_duration=2` (a genuine 2-consecutive-period block), `sessions_per_week=1`.
- Room-type + capacity compatibility is fully satisfiable for all 10 (Part C #12), but the literal `equipment_required` string does **not** match any room's `equipment` tags for 5 of them (Part C #13) — this needs a data/vocabulary fix or a policy decision before it can be enforced as a hard filter.
- Multiple sections compete for the same scarce lab pool: e.g. all 4 programmes' Year-1 cohorts need `Physics Lab` against a single `PHYSICS_LAB` room — this alone forces those 4 sections' physics-lab sessions onto 4 different slots (or requires batch-splitting the SIH statement mentions, which this dataset does **not** currently model — sections are single, undivided groups; if batch-splitting labs is required, that's a real gap between the dataset and the stated NEP requirement, worth flagging to the team).
- Consecutive-period booking must respect the lunch-break time gap (Part C #20) — a naive "period_number, period_number+1" pairing would incorrectly allow a lab to span 12:00–13:00 and 14:00–15:00 as if contiguous.

---

## PART L — Infeasibility

**How infeasibility can occur (compounding factors identified in this dataset):**
- A restricted-availability faculty (e.g. F004/F016/F017/F023, 6/35 slots) is the *only* remaining eligible+available choice for an offering after other eligible faculty are consumed elsewhere by the solver — even though aggregate faculty capacity is healthy (676 hrs vs 411 hrs demand), a *local* bottleneck around one scarce person/room can still make a particular assignment infeasible.
- The single `PHYSICS_LAB` room, used by up to 4 sections' Year-1 physics-lab offerings, competing for a small number of mutually-available (faculty ∩ room ∩ student) slots.
- A `synchronized=True` elective group forcing multiple sections' students onto one identical slot, which then has to simultaneously clear every one of those sections' own section-level free time, every eligible faculty's availability, and a compatible room's availability all at once.
- Fixed events (`fixed_events.csv`) removing slots university-wide (Mon 12–13 for all faculty, 13–14 for everyone) on top of individual unavailability.
- The two FAIL-level data issues from Part C (duplicate offerings inflating demand; equipment mismatch spuriously zeroing out room options) would themselves *manufacture* artificial infeasibility if not corrected first.

**How the solver should detect infeasibility:** run CP-SAT (or equivalent) with an explicit **infeasibility/relaxation diagnostic pass** — e.g. an IIS (irreducible inconsistent subsystem) style analysis, or a staged relaxation where soft-convertible constraints are progressively relaxed and re-tried, tagging which constraint's removal restored feasibility.

**What should be shown to the administrator:** which specific offering(s) couldn't be placed; which constraint(s) were the blocker (e.g. "Offering O0107 (C060, S_CSE_3_A): only 1 eligible faculty (F0xx) has 6 available slots, all already consumed by other assignments"); a small number of concrete suggested relaxations (e.g. "increase F0xx's availability" or "add a second qualified faculty for C060").

**Constraints that may be relaxable (with university sign-off):** soft preferences always (Part F, by definition); potentially `min_hours_per_week` (Part A8, flagged as needing confirmation); potentially the exact numeric caps in `academic_rules.csv` if they're defaults rather than binding HR policy (needs confirmation — they are *not* stated in the SIH problem itself).

**Constraints that must never be relaxed:** faculty/room/section/student collision (Parts E1–E4); faculty eligibility (E5); the two availability constraints (E6, E7) — relaxing "availability" without a human decision could double-book a person who has told the system they are genuinely unavailable, which the SIH statement explicitly frames as the exact failure mode ("clashes discovered only after classes begin") the whole project exists to prevent.

---

## PART M — Final consolidated constraint tables

### M-A. HARD constraints

| ID | Name | Priority | Rule | Reason | Entities | Required Data | Confidence | Univ. Confirmation Needed? |
|---|---|---|---|---|---|---|---|---|
| HC01 | No faculty double-booking | Critical | A faculty member occupies at most 1 session per slot, across the whole university | Explicit SIH requirement (conflict-free) | Faculty, Session, Slot | faculty_availability, course_offerings (assigned faculty) | High | No |
| HC02 | No room double-booking | Critical | A room hosts at most 1 session per slot | Explicit SIH requirement | Room, Session, Slot | room_availability, course_offerings | High | No |
| HC03 | No section double-booking | Critical | A section attends at most 1 session per slot (CORE courses) | Explicit SIH requirement | Section, Session, Slot | sections, course_offerings | High | No |
| HC04 | No student-level double-booking (electives) | Critical | An individual student attends at most 1 session per slot, including cross-section OAE/PCE sessions | Strongly implied (NEP electives across programmes); confirmed necessary in Part I | Student, Session, Slot | student_enrollments, course_offerings | High | No |
| HC05 | Faculty–course eligibility | Critical | Assigned faculty must appear in faculty_courses for that course_id | Explicit dataset rule (README: "faculty eligibility separate from offerings") | Faculty, Course | faculty_courses | High | No |
| HC06 | Faculty slot availability | Critical | Session only placed where faculty_availability.available = True | Explicit SIH requirement (guest faculty fixed days) | Faculty, Slot | faculty_availability | High | No |
| HC07 | Room slot availability | Critical | Session only placed where room_availability.available = True | Common practice / dataset field exists | Room, Slot | room_availability | High | No |
| HC08 | Room capacity | Critical | room.capacity ≥ offering.student_count | Explicit dataset field (min_room_capacity) | Room, Offering | rooms, course_offerings | High | No |
| HC09 | Room type compatibility | Critical | room.room_type = course.required_room_type | Explicit dataset field | Room, Course | rooms, courses | High | No |
| HC10 | Equipment compatibility | Conditional-Hard | room.equipment ⊇ course.equipment_required | Dataset field exists, but **currently unmatchable for 5/10 lab courses** (Part C #13) | Room, Course | rooms, courses | Low (data defect) | **Yes — resolve vocabulary before enforcing as hard** |
| HC11 | Required weekly sessions fulfilled | Critical | Exactly `required_sessions` sessions of `session_duration` scheduled per offering | Explicit dataset field | Offering | course_offerings | High | No |
| HC12 | Consecutive-slot contiguity | Critical | Multi-period sessions occupy truly time-contiguous slots (not just adjacent period_number) | Derived from dataset structure (Part C #20); needed for 10 lab courses | Offering, Slot | time_slots (start/end time), course_offerings | High | No |
| HC13 | Fixed institutional events block | Critical | No session may overlap a fixed_events window for its scope | Explicit dataset table; verified NOT pre-baked into availability (Part C #19) | Fixed Event, Faculty/Room/Section | fixed_events | High | No |
| HC14 | Faculty daily/weekly workload cap | Critical | Faculty's scheduled hours ≤ its own `max_hours_per_day`/`max_hours_per_week` (per-row value overrides academic_rules default) | Explicit dataset field, explicit per-faculty override for VISITING/ADJUNCT | Faculty | faculty | High | No |
| HC15 | Elective fulfilment | Critical | Every student's enrolled OAE/PCE course appears without collision in their personal timetable | Explicit SIH requirement (NEP electives) | Student, Course, Session | student_enrollments | High | No |
| HC16 | Shared/synchronized elective scheduling | Critical | Where `elective_groups.synchronized = True`, all sections drawing on that shared offering get the identical slot(s) | Explicit dataset field | Elective Group, Offering, Section | elective_groups, elective_group_courses, course_offerings | Medium | **Yes — confirm synchronization is a real institutional requirement, not just a dataset convenience** |
| HC17 | Single consistent faculty per offering | High | All sessions of one offering are taught by the same assigned faculty (unless university explicitly allows split-teaching) | Common practice; not explicitly stated in SIH text | Offering, Faculty | course_offerings | Medium | **Yes** |
| HC18 | Clean offering data precondition | Critical (pre-solve) | No duplicate (course_id, section_id) offering rows may be fed to the solver | Data defect found in Part C #14/#15 | Offering | course_offerings | High | No — but dataset must be corrected first |

### M-B. SOFT constraints

| ID | Name | Priority | Rule | Reason | Entities | Required Data | Confidence | Univ. Confirmation Needed? |
|---|---|---|---|---|---|---|---|---|
| SC01 | Faculty preferred slots | Medium | Reward placing sessions in slots with high `preference_score` for the assigned faculty | Explicit dataset field | Faculty, Slot | faculty_availability.preference_score | Medium | No |
| SC02 | Minimize student gaps | Medium | Penalize idle periods between a student's/section's sessions on the same day | Common practice, implied by "student convenience" | Student/Section, Slot | course_offerings, time_slots | Medium | No |
| SC03 | Minimize faculty idle gaps | Low-Medium | Penalize idle periods between a faculty's sessions on the same day | Common practice | Faculty, Slot | course_offerings, faculty_availability | Medium | No |
| SC04 | Balance faculty workload | Medium | Distribute teaching hours across eligible faculty rather than concentrating on a few | Supports "maximise resource utilization" | Faculty | course_offerings, faculty | Medium | No |
| SC05 | Avoid excessive consecutive sessions | Low-Medium | Penalize faculty/section back-to-back runs beyond a comfortable threshold | Common practice | Faculty/Section, Slot | course_offerings | Low | **Yes — threshold needs definition** |
| SC06 | Spread multi-session courses across days | Medium | Avoid scheduling 2+ weekly sessions of the same offering on the same day where avoidable | Common practice, pedagogical | Offering | course_offerings | Low | **Yes** |
| SC07 | Minimize room capacity wastage | Low | Prefer a right-sized room over an oversized one when both are free and compatible | Explicit candidate rule in academic_rules.csv (R009) | Room, Offering | rooms, course_offerings | Medium | No |
| SC08 | Avoid undesirable slots | Low | Penalize first/last-period placement if flagged undesirable | Optional preference; no dataset field currently encodes "undesirable" beyond preference_score | Slot | faculty_availability.preference_score | Low | **Yes** |
| SC09 | Reduce timetable fragmentation | Low | Prefer contiguous blocks over scattered single sessions per section per day | Common practice | Section, Slot | course_offerings | Low | No |
| SC10 | Meet faculty minimum weekly hours | Low-Medium | Treat `min_hours_per_week` as a soft target, not a hard floor, pending confirmation | Dataset field exists but purpose (HR policy vs balancing hint) is unconfirmed | Faculty | faculty.min_hours_per_week | Low | **Yes** |
| SC11 | Minimize cross-building/floor movement | Low | Prefer same building/floor for a section's/faculty's back-to-back sessions | Dataset has building/floor fields enabling this, but it's not mentioned anywhere in the SIH text | Room, Section/Faculty | rooms.building, rooms.floor | Low | **Yes** |

### M-C. CONDITIONAL constraints

| ID | Name | Priority | Rule | Reason | Entities | Required Data | Confidence | Univ. Confirmation Needed? |
|---|---|---|---|---|---|---|---|---|
| CC01 | Lab room-type trigger | High | IF course.requires_lab = True THEN room.room_type = course.required_room_type | Explicit dataset field | Course, Room | courses, rooms | High | No |
| CC02 | Multi-slot contiguity trigger | High | IF session_duration > 1 THEN book that many truly time-contiguous slots, same room & faculty | Derived (Part C #20) | Offering, Slot | course_offerings, time_slots | High | No |
| CC03 | Multi-eligible-faculty choice | High | IF >1 eligible faculty THEN solver selects exactly one; IF =1 THEN it is fixed | Explicit dataset design (README, docs_constraint_discovery_prompt.md) | Course, Faculty | faculty_courses | High | No |
| CC04 | Restricted-availability trigger | Medium | IF a faculty has a small True-availability set THEN scheduling for their courses must be pre-screened for feasibility before global solving | Derived (Part C #22 — 4 faculty at 6/35 slots) | Faculty | faculty_availability | Medium | No |
| CC05 | Elective personal-timetable trigger | Critical | IF student enrolled in an elective THEN that session must be collision-free in their personal (not just section) timetable | Explicit SIH requirement; confirmed necessary in Part I | Student, Course | student_enrollments | High | No |
| CC06 | Shared-course multi-section trigger | High | IF an offering/course is drawn on by >1 section (18 such courses) THEN cross-section collision + (if synchronized) identical-slot constraints apply | Derived from Part C #18 / Part H | Course, Section | course_offerings, elective_groups | Medium | **Yes for synchronization scope** |
| CC07 | Cross-listed elective group trigger | Medium | IF a course is listed in more than one elective_group (C058, C060, C061) THEN its single offering must satisfy both groups' student populations simultaneously | Derived from Part C #18 | Course, Elective Group | elective_group_courses | Medium | **Yes** |
| CC08 | Section-level CORE collision (subset of HC03) | Critical | IF two offerings target the same section for CORE courses THEN they can never share a slot | Derived, subsumed by HC03/HC04 | Section, Offering | course_offerings | High | No |
| CC09 | Equipment-vocabulary fallback | High (interim policy) | IF course.equipment_required cannot be matched to any room.equipment string THEN fall back to room_type+capacity as authoritative | Data-quality workaround for Part C #13 | Course, Room | courses, rooms | Medium | **Yes — interim only, needs real fix** |
| CC10 | Pre-solve feasibility screening | Medium | IF a faculty's available-slot count is smaller than a safety margin over their likely required teaching hours THEN flag before the main solve | Best practice given Part C #22/Part L findings | Faculty | faculty_availability, faculty_courses | Medium | No |

---

## Summary: what needs university confirmation before Round 2
1. Whether `academic_rules.csv` numeric values (4 hrs/day, 18 hrs/week defaults) are binding HR policy or just synthetic defaults.
2. Whether `min_hours_per_week` is a hard floor or a soft balancing target (SC10).
3. Whether elective synchronization (`synchronized=True`, HC16/CC06/CC07) is a real institutional rule.
4. Whether one faculty may be split across multiple sessions of a single offering (HC17).
5. Whether lab batch-splitting (mentioned in the SIH text) needs to be added to the data model — it is **not currently represented**; sections are modeled as single undivided groups even for lab courses.
6. Resolution of the equipment vocabulary mismatch (HC10/CC09) — real equipment inventory vs. course requirement wording.
7. Whether the 4 low-availability permanent faculty (Part C #22) reflect real constraints or a data-generation artifact.

## Recommendation for Round 2
Fix the two FAIL-level dataset issues (duplicate offerings; equipment vocabulary — or accept the CC09 fallback), get sign-off on the 7 confirmation items above, and only then proceed to CP-SAT variable/constraint formulation and implementation — per the instruction, no code was written in this round.
