# SIH Smart Timetable — Mathematical CP-SAT Model Specification (Round 2)

Source of truth used throughout: **"SIH Smart Timetable — Final Consolidated Constraint Specification"** (Round 1, approved) and the **corrected dataset** (133 offerings, 65 courses, 40 faculty, 29 rooms, 35 slots, 16 sections, 1000 students, 6750 enrollments). No production Python, no FastAPI, no frontend, no database code appears below — this is model design only, expressed as sets, parameters, variables, and constraint logic in prose/pseudo-math.

---

## PART 1 — MODELING OVERVIEW

**What is being assigned:** each required *session* of each *course offering* must be assigned a starting time slot, a room, and (once per offering, per HC-15) a faculty member.

**What the solver decides:**
1. *When* each session happens (which slot(s) it occupies).
2. *Where* it happens (which room).
3. *Who* teaches it (which eligible faculty, chosen once per offering).

**What is fixed by the dataset (not decided):** the set of offerings and how many sessions/what duration each needs (`course_offerings.csv`); which faculty are even eligible for a course (`faculty_courses.csv`); which slots exist and their clock times (`time_slots.csv`); which rooms exist, their type/capacity/equipment (`rooms.csv`); who is enrolled in what (`student_enrollments.csv`); which electives are grouped/synchronized (`elective_groups.csv`); and institution-wide blocked windows (`fixed_events.csv`).

**What the solver is allowed to choose:** slot(s), room, and faculty for every session — subject to every applicable HARD/CONDITIONAL constraint from the approved specification — plus (only if a solution exists at all) the choices that best satisfy the SOFT objective terms.

**Feasibility:** a solution is feasible if and only if every HARD constraint (HC-01…HC-16) and every activated CONDITIONAL constraint (CC-01…CC-08) holds simultaneously for every scheduled session, for all 133 offerings, across the whole university at once (not per-section, per Part H/6 of Round 1).

**Optimality:** among all feasible solutions, the model prefers the one minimizing a weighted sum of soft-constraint penalty terms (SC-01…SC-09), as detailed in Part 15–16. Feasibility is never traded for a better objective value — this is enforced structurally (soft terms only ever appear in the objective, never as hard bounds), not by weighting alone.

**High-level architecture:**
```
RAW DATA (CSV files, corrected dataset)
     ↓
PREPROCESSING / DERIVED DATA  (Part 4)
     — eligible faculty per course
     — compatible rooms per course (type+capacity+equipment)
     — valid (faculty,slot) and (room,slot) pairs
     — valid contiguous-slot pairs (respecting the lunch gap)
     — student/section → offering membership
     — synchronized elective offering groups
     — fixed-event blocked (entity,slot) pairs
     ↓
CP-SAT MODEL
     — decision variables (Part 5)
     — hard + conditional constraints (Parts 9–10)
     — soft objective terms (Part 15–16)
     ↓
SOLVE
     ↓
SOLUTION EXTRACTION (Part 18) or INFEASIBILITY DIAGNOSIS (Part 17)
```

---

## PART 2 — SETS

Only sets actually needed by the constraints in the approved specification are defined — no speculative sets.

| Set | Represents | Source table | Example element |
|---|---|---|---|
| `F` — Faculty | All faculty members | `faculty.csv` | `F004` |
| `R` — Rooms | All rooms/resources | `rooms.csv` | `EL001` |
| `D` — Days | Days of the academic week | `time_slots.csv` (distinct `day`) | `MON` |
| `T` — Time slots | Every schedulable slot (day+period, with real clock time) | `time_slots.csv` | `MON_1200` |
| `O` — Offerings | Course-offering instances (course × section), the actual unit the solver schedules | `course_offerings.csv` | `O0053` |
| `S` — Sessions | The individual weekly session occurrences a given offering needs (index 1…`required_sessions`) — **not a standalone file**, this set is *derived* per offering from `course_offerings.required_sessions` | derived from `course_offerings.csv` | session 2 of `O0053` |
| `C` — Courses | Course catalog | `courses.csv` | `C017` |
| `SEC` — Sections | Program×year cohorts | `sections.csv` | `S_CSE_3_A` |
| `ST` — Students | Individual students | `students.csv` | `STU0819` |
| `EG` — Elective groups | OAE/PCE groups | `elective_groups.csv` | `EG01` |
| `FE` — Fixed events | Institution-wide blocked windows | `fixed_events.csv` | `EV001` |

**Sets deliberately NOT created**, and why:
- No standalone `Programs` or `Years`/`Branches` sets are needed as *modeling* sets — they exist only as attributes of `Section` and are used for readability/reporting (Part 18), not as independent solver dimensions; every constraint that matters operates at Faculty/Room/Section/Student/Slot granularity, never at "program" or "year" granularity directly (this is the same reasoning as Round 1 Part H: solve university-wide, not year-by-year — introducing a Year set would invite the mistake of partitioning by it).
- No standalone `Room Types` or `Equipment` sets — these are *attributes* of Rooms and Courses, consumed during preprocessing (Part 4) to derive room-compatibility, not iterated over directly by any constraint.
- No standalone `Departments` set — not referenced by any approved constraint.

---

## PART 3 — PARAMETERS

All parameters are read directly from the corrected dataset; none are invented. "Derived" parameters (computed once from raw fields, not independently authored) are marked as such and are elaborated in Part 4.

| Parameter | Source file | Field | Meaning | Type |
|---|---|---|---|---|
| `reqSessions[o]` | course_offerings.csv | required_sessions | # weekly sessions offering `o` needs | integer, per offering |
| `duration[o]` | course_offerings.csv | session_duration | # consecutive slots each session of `o` occupies | integer, per offering |
| `studentCount[o]` | course_offerings.csv | student_count | # students to seat for offering `o` | integer, per offering |
| `courseOf[o]` | course_offerings.csv | course_id | which course an offering instantiates | categorical |
| `sectionOf[o]` | course_offerings.csv | section_id | which section an offering serves | categorical |
| `requiresLab[c]` | courses.csv | requires_lab | whether course `c` needs a specialised room | boolean, per course |
| `reqRoomType[c]` | courses.csv | required_room_type | room type needed | categorical |
| `minCapacity[c]` | courses.csv | min_room_capacity | minimum room size for course `c` | integer |
| `equipReq[c]` | courses.csv | equipment_required | equipment tag(s) needed (blank for C024/C039 per HC-11's documented fallback) | string/set, may be empty |
| `roomType[r]` | rooms.csv | room_type | type of room `r` | categorical |
| `capacity[r]` | rooms.csv | capacity | seating capacity of room `r` | integer |
| `roomEquip[r]` | rooms.csv | equipment | equipment tags room `r` has | set of strings |
| `roomAvail[r,t]` | room_availability.csv | available | whether room `r` is usable at slot `t` | boolean |
| `eligible[f,c]` | faculty_courses.csv | (existence of row) | whether faculty `f` may teach course `c` | boolean |
| `facAvail[f,t]` | faculty_availability.csv | available | whether faculty `f` is usable at slot `t` | boolean |
| `facPref[f,t]` | faculty_availability.csv | preference_score | how much faculty `f` prefers slot `t` (0–5) | integer |
| `maxDaily[f]` | faculty.csv | max_hours_per_day | HC-16 daily cap for faculty `f` | integer (SYNTHETIC PROTOTYPE ASSUMPTION per Round 1) |
| `maxWeekly[f]` | faculty.csv | max_hours_per_week | HC-16 weekly cap for faculty `f` | integer (SYNTHETIC PROTOTYPE ASSUMPTION) |
| `minWeekly[f]` | faculty.csv | min_hours_per_week | SC-09 soft target for faculty `f` | integer (SYNTHETIC PROTOTYPE ASSUMPTION) |
| `enrolled[st,c]` | student_enrollments.csv | (existence of row) | whether student `st` is enrolled in course `c`, and with what `enrollment_type` | boolean + categorical |
| `groupOf[c]` | elective_group_courses.csv | elective_group_id | which elective group(s) course `c` belongs to (0, 1, or 2 per HC-13's cross-listing note) | set of categorical |
| `synchronized[eg]` | elective_groups.csv | synchronized | whether group `eg` requires identical-slot scheduling | boolean |
| `slotDay[t]`, `slotStart[t]`, `slotEnd[t]` | time_slots.csv | day, start_time, end_time | clock-time identity of slot `t` | categorical / time |
| `eventWindow[fe]` | fixed_events.csv | day, start_time, end_time | blocked time window | time range |
| `eventScope[fe]` | fixed_events.csv | scope | who/what the event blocks (ALL, ALL_FACULTY, etc.) | categorical |

No parameter above was invented beyond what a named dataset field directly provides; all "derived" quantities (e.g. compatible-room lists) are treated as **preprocessing outputs**, not raw parameters — see Part 4.

---

## PART 4 — DERIVED DATA / PREPROCESSING

Computed once, before the CP-SAT model is built, from the raw parameters above. This is data preparation, not modeling — none of these computations are decision variables, and none of them are themselves constraints (per the Round 1 instruction not to conflate preprocessing with constraints).

| Derived quantity | Computed from | Definition |
|---|---|---|
| `EligibleFaculty(c)` | faculty_courses.csv | `{ f ∈ F : eligible[f,c] }` — for the corrected dataset, non-empty for all 65 courses (mean 12/course) |
| `CompatibleRoomsByType(c)` | courses.csv, rooms.csv | `{ r ∈ R : roomType[r] = reqRoomType[c] AND capacity[r] ≥ max(minCapacity[c], studentCount[o]) }` for offerings `o` of course `c` |
| `CompatibleRoomsByEquipment(c)` | courses.csv, rooms.csv | If `equipReq[c]` is non-empty: `{ r ∈ CompatibleRoomsByType(c) : equipReq[c] ⊆ roomEquip[r] }`. If `equipReq[c]` is empty (C024, C039 — HC-11's documented fallback): equals `CompatibleRoomsByType(c)` unfiltered. |
| `ValidFacultySlots(f)` | faculty_availability.csv | `{ t ∈ T : facAvail[f,t] = True }` |
| `ValidRoomSlots(r)` | room_availability.csv | `{ t ∈ T : roomAvail[r,t] = True }` |
| `ContiguousSlotSets(d, k)` | time_slots.csv | For duration `k`, all ordered tuples of `k` slots on day `d` whose clock times are back-to-back with **zero gap** (`slotEnd[tᵢ] = slotStart[tᵢ₊₁]`) — this explicitly excludes the `MON_1200 → MON_1400` pairing (there's a 1-hour gap) even though their `period_number`s are adjacent. This is the one preprocessing step Part 8/HC-12 depends on entirely. |
| `SectionOfferings(sec)` | course_offerings.csv | `{ o ∈ O : sectionOf[o] = sec }` |
| `StudentCoreOfferings(st)` | students.csv, course_offerings.csv | Derived once: since every student in a section shares the identical CORE list (re-confirmed, Round 1 Part 7), this equals `SectionOfferings(section_of(st))` restricted to CORE courses — **not** computed per-student, computed once per section and reused, exactly the optimization Round 1 justified. |
| `StudentElectiveOfferings(st)` | student_enrollments.csv, course_offerings.csv | `{ o ∈ O : courseOf[o] = c for some c with enrolled[st,c]=True and enrollment_type ∈ {OAE,PCE} }` — genuinely computed per student (750 enrollment rows), because this is where section-level shortcutting is *not* valid (Part 7/Part 11 below). |
| `SynchronizedOfferingGroups` | elective_groups.csv, elective_group_courses.csv, course_offerings.csv | For every `eg` with `synchronized[eg]=True`, the set of offerings `{o : courseOf[o] ∈ groupOf⁻¹(eg)}` that must share a slot (Part 12) |
| `BlockedAssignments(fe)` | fixed_events.csv, time_slots.csv | For each fixed event, the set of slots `t` whose clock window overlaps `eventWindow[fe]`, paired with the scope-appropriate entities (Part 13) |
| `SessionIndex(o)` | course_offerings.csv | `{1, …, reqSessions[o]}` — the derived Session set `S` from Part 2, materialized per offering |

**Explicit distinction (per instruction):**
- **RAW DATA** = every field listed in Part 3, read as-is from the corrected CSVs.
- **DERIVED DATA** = every row in the table above — computed once, deterministically, before solving; changing them does not require re-solving logic, only re-running preprocessing.
- **DECISION VARIABLES** (Part 5) = the *only* things CP-SAT actually searches over. `CompatibleRoomsByEquipment(c)`, for instance, is not a variable — it's a fixed input set that *constrains the domain* of a room-assignment variable.

---

## PART 5 — DECISION VARIABLES

Minimum variable set to represent the five required decisions, avoiding redundancy.

### 1. Session placement: `Start[o, s]`
- **Indexes:** offering `o ∈ O`, session index `s ∈ SessionIndex(o)`.
- **Domain:** a slot `t ∈ T` such that `t` is the *first* slot of a valid contiguous block of length `duration[o]` on some day (i.e. `t` must be the start of some tuple in `ContiguousSlotSets(day(t), duration[o])`).
- **Meaning:** the slot at which session `s` of offering `o` begins. The remaining `duration[o]-1` slots it occupies are *implied*, not separately decided — this is why only a "start slot" variable is needed rather than one boolean per (offering, session, slot) pair, avoiding a redundant per-slot occupancy variable when duration/contiguity can instead constrain the domain of a single start variable directly.
- **Why required:** this is the core "when" decision (Part 1).

### 2. Faculty assignment: `Teacher[o]`
- **Indexes:** offering `o ∈ O` only — **not** per session, per HC-15 (Round 1: one consistent faculty per offering).
- **Domain:** `f ∈ EligibleFaculty(courseOf[o])`.
- **Meaning:** which eligible faculty member teaches every session of offering `o`.
- **Why one variable per offering, not per course:** because a course can have multiple offerings (across sections), and HC-15/Round 1 Part 6 explicitly allows different offerings of the *same* course to be taught by different eligible faculty — so the variable must be indexed by offering, not by course.

### 3. Room assignment: `Room[o, s]`
- **Indexes:** offering `o ∈ O`, session index `s ∈ SessionIndex(o)`.
- **Domain:** `r ∈ CompatibleRoomsByEquipment(courseOf[o])`.
- **Meaning:** which room hosts session `s` of offering `o`. Indexed per session (not just per offering) because nothing in the approved spec requires all sessions of one offering to share a room (unlike faculty, where HC-15 explicitly does), and in practice a 3-sessions/week theory offering might reasonably use different classrooms on different days.

### 4. (Implied, not a separate variable) Occupied slots
- The full set of slots occupied by session `(o,s)` is `{Start[o,s], Start[o,s]+1, …, Start[o,s]+duration[o]-1}` (within the same contiguous block by construction of the domain in #1). No separate variable is created for this — it is read off `Start[o,s]` deterministically, keeping the model minimal.

### 5. Elective/synchronization support: no new variable needed
- Synchronization (HC-13) is enforced by **equating** `Start[o,s]` variables across the offerings in a `SynchronizedOfferingGroups` entry (Part 12) — this is a constraint on existing variables, not a new variable.
- Student-level elective conflict checking (HC-04 elective branch) is enforced by constraints over the existing `Start[o,·]` variables of the specific offerings a student is enrolled in (Part 11) — again, no new variable.

**Variables deliberately NOT created:**
- No `Assigned[o,s,t]` boolean per (offering,session,slot) — redundant with `Start[o,s]`'s domain once contiguity is baked into the domain construction.
- No separate CORE-level student variable — Part 4/Part 11 establish section-level suffices.
- No per-slot faculty-occupancy boolean separate from what's derivable from `Start` and `Teacher` — collision constraints (Part 9) are expressed directly over `Start`/`Teacher`/`Room` using CP-SAT's native interval/no-overlap machinery (see HC-01/02 below), not extra boolean grids.

This gives **three core decision variables** — `Start[o,s]`, `Teacher[o]`, `Room[o,s]` — sufficient to represent every decision named in Part 5's five numbered items.

---

## PART 6 — FACULTY ASSIGNMENT MODEL (formalized)

`Course → EligibleFaculty(course) → Teacher[o]` for each offering `o` of that course.

- **Multiple eligible faculty per course:** `Teacher[o]`'s domain is exactly `EligibleFaculty(courseOf[o])`, which for the corrected dataset has ≥3 members for every course (min 3, mean 12) — the solver genuinely chooses.
- **Same faculty teaching multiple courses:** unconstrained by construction — `Teacher[o₁]=f` and `Teacher[o₂]=f` for different offerings `o₁≠o₂` of different courses is allowed as long as HC-01/HC-16 (below) aren't violated by the resulting schedule.
- **Faculty across years/branches:** since `Teacher` is indexed by offering (not by course-and-section jointly restricted to one year), and `EligibleFaculty(c)` is drawn from the university-wide `faculty_courses.csv` without any year/branch filter, a faculty member eligible for a Year-1 core course and a Year-4 elective can legally be assigned to both — HC-01 (Part 9) then enforces non-collision across *all* such assignments simultaneously, university-wide, exactly matching Round 1 Part H's requirement to never partition by year.
- **Availability:** `Teacher[o]=f` combined with `Start[o,s]` choices must respect `facAvail[f, t]` for every occupied slot `t` (HC-06, Part 9).
- **Daily/weekly workload:** aggregated over every session `Teacher` has been assigned to, across every offering (HC-16, Part 14).
- **Preference scores:** contribute to the objective (SC-01), not to feasibility.

**Per-offering, not per-session:** confirmed as the correct granularity — `Teacher[o]` has no session index, directly encoding HC-15 (one consistent faculty per offering) as a *structural* property of the variable itself rather than as an extra equality constraint that could be forgotten or violated.

---

## PART 7 — ROOM ASSIGNMENT MODEL (formalized)

`Room[o,s]`'s domain is `CompatibleRoomsByEquipment(courseOf[o])`, itself built from `CompatibleRoomsByType` filtered by capacity and (where meaningful) equipment (Part 4).

- **Capacity/type/equipment** are enforced entirely through **domain construction**, not through explicit constraints — an infeasible room simply never appears in `Room[o,s]`'s domain, which is both correct and computationally preferable to filtering after the fact.
- **Availability:** `roomAvail[Room[o,s], t]` must hold for every slot `t` the session occupies (HC-07).
- **Simultaneous usage (HC-02):** enforced across *all* offerings/sessions sharing a room value at overlapping time — via CP-SAT interval/no-overlap constraints per room (Part 9).
- **C028's single compatible electronics room:** the model does **not** special-case C028. `CompatibleRoomsByEquipment('C028')` is computed generically from Part 4's formula and, for the corrected dataset, happens to evaluate to a 1-element set (`{EL001}`, since only EL001 carries the `MICROCONTROLLERS` tag `C028` requires). The domain-construction mechanism handles this automatically — it simply produces a smaller domain for `Room[o,s]` on C028's offerings, which in turn means those specific decisions have less scheduling flexibility (this shows up naturally as tighter propagation during search, and as a likely infeasibility hotspot per Part 17 if that one room's slots get contested — no special code path required).
- **The single PHYSICS_LAB bottleneck:** likewise not hard-coded. `CompatibleRoomsByType('C006')` evaluates generically to `{PL001}` because the dataset has exactly one `PHYSICS_LAB` room; every offering of C006 (across however many sections) draws from that same 1-element domain, and HC-02 (no two offerings using the same room at overlapping time) then automatically forces those offerings' `Start` variables apart. The bottleneck is an *emergent property* of generic domain construction plus generic collision constraints, not a modeled special case — exactly as the instruction requires.

---

## PART 8 — TIME MODEL

- **Days (`D`):** 5 distinct values from `time_slots.day` (MON…FRI).
- **Time slots (`T`):** 35 rows in `time_slots.csv`, each with a `day`, `period_number`, `start_time`, `end_time`.
- **Slot ordering:** slots are ordered **by clock time within a day** (`start_time`), not by `period_number` alone — this distinction matters precisely because of the lunch gap.
- **The lunch gap, explicitly:** `MON_1200` ends at 13:00; the next slot on Monday, `MON_1400`, starts at 14:00. Their `period_number`s are 4 and 5 (numerically adjacent), but `slotEnd[MON_1200] ≠ slotStart[MON_1400]` (13:00 ≠ 14:00). **The model must never treat `period_number+1` as proof of contiguity.** `ContiguousSlotSets(d,k)` (Part 4) is defined strictly on `start_time`/`end_time` equality, which correctly excludes this pairing and correctly includes true back-to-back pairs like `MON_0900`→`MON_1000` (assuming those are truly adjacent in the raw data, verified during preprocessing, not assumed).
- **Session duration / multi-slot sessions:** a session with `duration[o]=2` (the 10 lab/workshop courses, all `session_duration=2`) is represented by a single `Start[o,s]` variable whose **domain is restricted to only those slots that are the first element of some valid 2-slot contiguous tuple** in `ContiguousSlotSets(day, 2)` — so an infeasible placement (e.g. starting at `MON_1200`, which has no valid 2-contiguous continuation across the lunch gap) is simply never in the domain, again handled by domain construction rather than a runtime constraint check.
- **Representing a 2-slot lab session concretely:** if `Start[o,s] = MON_0900` and `MON_0900→MON_1000` are verified truly contiguous, the session occupies exactly `{MON_0900, MON_1000}`; the room, faculty, and all collision constraints (Part 9) apply to *both* slots identically, derived from the single `Start` value plus `duration[o]`.

---

## PART 9 — HARD CONSTRAINT FORMULATION (HC-01 … HC-16)

| ID | Name | Mathematical logic | CP-SAT implementation idea | Input data | What it prevents |
|---|---|---|---|---|---|
| HC-01 | Faculty collision | For all pairs of sessions `(o₁,s₁) ≠ (o₂,s₂)` with `Teacher[o₁]=Teacher[o₂]`, their occupied-slot sets must not overlap | Build one `IntervalVar` per (offering,session) keyed by `Start[o,s]` and `duration[o]`; group intervals by `Teacher[o]` value (via `AddNoOverlap` per faculty, using channeling/reified equality since `Teacher` is itself a variable) — practically: use `AddNoOverlap` over intervals conditioned on `Teacher[o]=f` for each faculty `f`, or model via optional intervals per (offering,session,candidate-faculty) | Start, Teacher, duration | Same faculty double-booked at overlapping times, across any year/branch |
| HC-02 | Room collision | For all pairs of sessions with `Room[o₁,s₁]=Room[o₂,s₂]`, occupied-slot sets must not overlap | `AddNoOverlap` per room, analogous to HC-01, using optional intervals conditioned on `Room[o,s]=r` | Start, Room, duration | Two offerings sharing a room at overlapping time |
| HC-03 | Section collision (CORE) | For all pairs of CORE offerings `o₁≠o₂` with `sectionOf[o₁]=sectionOf[o₂]`, occupied-slot sets must not overlap | `AddNoOverlap` per section, restricted to `SectionOfferings(sec)` filtered to CORE courses | Start, duration, sectionOf | A section's students double-booked for two CORE classes |
| HC-04 | Student-level collision (merged) | CORE portion = HC-03 (section-level, exact). Elective portion: for every student `st`, for all pairs `o₁≠o₂ ∈ StudentElectiveOfferings(st) ∪ StudentCoreOfferings(st)`, occupied-slot sets must not overlap | For the ~750-enrollment elective population: per-student `AddNoOverlap` over the union of their CORE offering (one, from the section) and their specific elective offerings | Start, duration, student_enrollments, StudentElectiveOfferings | A specific student's elective clashing with another elective or with their own CORE schedule |
| HC-05 | Faculty eligibility | `Teacher[o] ∈ EligibleFaculty(courseOf[o])` | Enforced by **domain construction** on `Teacher[o]` — not a runtime constraint | faculty_courses.csv | Assigning an unqualified faculty member |
| HC-06 | Faculty availability | For every occupied slot `t` of every session taught by `f=Teacher[o]`: `facAvail[f,t]=True` | Reified constraint: `Teacher[o]=f ⟹ Start[o,s]` domain restricted to slots where `f` is available for that duration-block — implemented as a per-(offering,session,candidate-faculty) domain restriction or a table/allowed-assignments constraint | faculty_availability.csv | Scheduling a faculty member when they've stated unavailability |
| HC-07 | Room availability | For every occupied slot `t` of session `(o,s)`: `roomAvail[Room[o,s], t]=True` | Domain restriction on `Room[o,s]` combined with `Start[o,s]`, or an allowed-assignments table constraint over (room, start-slot) pairs | room_availability.csv | Scheduling into a blocked/unavailable room |
| HC-08 | Room capacity | `capacity[Room[o,s]] ≥ studentCount[o]` | Enforced by domain construction: `Room[o,s]` domain restricted to `CompatibleRoomsByEquipment(courseOf[o])`, which already filters on capacity (Part 4) | rooms.csv, course_offerings.csv | Overcrowding a room |
| HC-09 | Room type compatibility | `roomType[Room[o,s]] = reqRoomType[courseOf[o]]` | Domain construction (same mechanism as HC-08) | courses.csv, rooms.csv | Scheduling a lab course into a plain classroom |
| HC-10 | Required sessions & duration fulfilled | `|SessionIndex(o)| = reqSessions[o]`; each session's occupied-slot count `= duration[o]` | Structural: `SessionIndex(o)` is materialized with exactly `reqSessions[o]` elements at model-build time; each `Start[o,s]`'s domain only contains starts of duration-`duration[o]` contiguous blocks | course_offerings.csv | Under/over-delivering an offering's weekly session count |
| HC-11 | Equipment compatibility (two-tier) | For 8/10 lab courses: `equipReq[c] ⊆ roomEquip[Room[o,s]]`. For C024/C039: no equipment filter, only HC-09/HC-08 apply | Domain construction (Part 4's `CompatibleRoomsByEquipment`), which already branches on whether `equipReq[c]` is empty | courses.csv, rooms.csv | Scheduling an equipment-requiring course into a room lacking it (for the 8 courses where a real match exists) |
| HC-12 | Consecutive multi-slot sessions | `Start[o,s]` domain restricted to slots that begin a true `duration[o]`-length contiguous (clock-time) block | Domain construction via `ContiguousSlotSets` (Part 4/8) — explicitly excludes the lunch-gap pairing | time_slots.csv (start/end times) | A 2-hour lab silently split across the lunch break |
| HC-13 | Elective/OAE-PCE fulfilment & synchronization | Fulfilment = HC-04's elective branch. Synchronization: for every group `G ∈ SynchronizedOfferingGroups`, all `o ∈ G`: `Start[o,·]` equal (same slot, matched by session index for multi-session electives) | Equality constraints between `Start` variables of offerings in the same synchronized group | elective_groups.csv, elective_group_courses.csv | An elective's sections meeting at different times when the university requires identical timing; a student's elective missing from their schedule |
| HC-14 | Fixed institutional events | For every fixed event `fe` and every entity in its scope, no session may occupy a slot in `BlockedAssignments(fe)` | Domain restriction: remove blocked slots from the relevant `Start[o,s]` domains (scope=ALL → all offerings; scope=ALL_FACULTY → restrict via `Teacher`-conditioned availability, same mechanism as HC-06) | fixed_events.csv | Scheduling into the weekly faculty meeting or lunch window |
| HC-15 | Single consistent faculty per offering | Structural — `Teacher[o]` has no session index | N/A — enforced by variable design (Part 5/6), not a runtime constraint | course_offerings.csv | An offering's sessions taught by different faculty without explicit authorization |
| HC-16 | Faculty daily/weekly workload cap | For faculty `f`: `Σ (hours of sessions where Teacher[o]=f, grouped by day) ≤ maxDaily[f]`; `Σ (all such hours per week) ≤ maxWeekly[f]` | Reified sum constraints: for each faculty `f` and day `d`, sum `duration[o,s]` over sessions with `Teacher[o]=f` and `day(Start[o,s])=d`, bounded by `maxDaily[f]`; analogous weekly sum bounded by `maxWeekly[f]` | faculty.csv (SYNTHETIC PROTOTYPE ASSUMPTION per Round 1) | Overloading a faculty member beyond their (prototype) cap |

---

## PART 10 — CONDITIONAL CONSTRAINT FORMULATION (CC-01 … CC-08)

| ID | Condition (activation) | Activated rule | Formulation |
|---|---|---|---|
| CC-01 | `requiresLab[courseOf[o]] = True` | `Room[o,s]` domain restricted to `CompatibleRoomsByEquipment` | Purely a domain-construction branch in Part 4 — for non-lab courses the same formula naturally reduces to `CompatibleRoomsByType` filtered only by the (usually CLASSROOM/LECTURE_HALL) type, so no separate code path is needed, just consistent use of the general formula |
| CC-02 | `courseOf[o]` is WORKSHOP type | Same mechanism as CC-01, `reqRoomType='WORKSHOP'` | Subsumed by the same generic domain formula |
| CC-03 | `duration[o] > 1` | `Start[o,s]` domain restricted to true contiguous-block starts | If `duration[o]=1`, `ContiguousSlotSets(d,1)` trivially equals all slots on `d` — the same formula handles both cases without branching logic, it's just that the constraint is vacuous when `duration=1` |
| CC-04 | `|EligibleFaculty(courseOf[o])| > 1` | `Teacher[o]` is a genuine decision variable with a multi-element domain | If `|EligibleFaculty(c)|=1` (does not currently occur in the corrected dataset, min is 3), `Teacher[o]`'s domain collapses to a singleton automatically — same variable, same mechanism, no special "fixed assignment" code path needed |
| CC-05 | Faculty `f` has `|ValidFacultySlots(f)| < 35` (restricted availability, e.g. 4 faculty at 6/35 in the corrected data) | Only slots in `ValidFacultySlots(f)` are reachable when `Teacher[o]=f` | Same domain-restriction mechanism as HC-06 — CC-05 is not a separate constraint from HC-06, it is HC-06's *effect* being pronounced for these specific faculty; no additional formulation beyond HC-06 is required, this row exists to document that the *searcher* will naturally feel this as a tighter sub-domain, which matters for Part 17's infeasibility-risk discussion |
| CC-06 | `enrolled[st, courseOf[o]] = True` with `enrollment_type ∈ {OAE,PCE}` | `o ∈ StudentElectiveOfferings(st)`, activating HC-04's per-student collision check | Set-membership trigger during preprocessing (Part 4) — determines which offerings enter the per-student `AddNoOverlap` group |
| CC-07 | `|{o' ∈ O : courseOf[o']=courseOf[o]}| > 1` (course offered to >1 section — 18/65 courses in the corrected data) | HC-03/HC-04 apply per-section as normal (no special handling needed, since those constraints already operate per-offering); additionally, if the course's `groupOf` includes a `synchronized=True` group, HC-13's equality constraints activate across those offerings | The offering-count check is a preprocessing classification (Part 4), not itself a new constraint — it determines *whether* HC-13's equality constraints get generated for that course's offerings |
| CC-08 | `equipReq[courseOf[o]]` is empty (C024, C039 specifically) | `Room[o,s]` domain uses `CompatibleRoomsByType` unfiltered by equipment | Branch already built into the `CompatibleRoomsByEquipment` formula (Part 4) — evaluates generically per course, not hard-coded to C024/C039 by name; it happens to select those two because their `equipment_required` field is blank in the corrected `courses.csv` |

---

## PART 11 — STUDENT CONFLICT MODEL (formalized)

**CORE:** section-level. For a student `st` with `section_of(st) = sec`, their CORE schedule is *by construction* identical to every other student in `sec` (re-verified on the corrected dataset — 0 exceptions). The solver therefore only needs one `AddNoOverlap` group per section over `SectionOfferings(sec) ∩ CORE`, applied once (HC-03) — **not** one group per student. This is mathematically equivalent to full per-student CORE checking because the enrollment relation is constant across a section; expanding it would add 1000 redundant copies of a 16-way check for zero additional correctness.

**OAE/PCE/interdisciplinary/skill:** student-level. For each student `st`, `StudentElectiveOfferings(st)` (built once during preprocessing, Part 4, directly from the 750 elective enrollment rows) plus their single CORE offering per relevant slot form one `AddNoOverlap` group per student. This is where individual student-level checking is *necessary*, not optional (Round 1 Part 7/I): the enrolled population for an elective offering is a cross-section subset, so section-level checking would miss genuine collisions.

**Concretely, how the solver "knows" Student S001 can't have Course A at 10:00 and Course B at 10:00:** during preprocessing, `StudentElectiveOfferings('S001')` is built from `student_enrollments.csv` rows where `student_id='S001'` and `enrollment_type ∈ {OAE,PCE}`; if both Course A's offering and Course B's offering appear in that set, an `AddNoOverlap` (or equivalent pairwise "occupied-slot sets must not intersect") constraint is generated over their `Start[o,·]` variables as part of HC-04's elective branch — this is a direct, mechanical consequence of the enrollment data, not a hand-authored rule about "S001" specifically. No student is named in the model definition; the constraint-generation loop iterates over `ST` generically and happens to produce this particular pairing because that's what the corrected `student_enrollments.csv` contains.

---

## PART 12 — ELECTIVE SYNCHRONIZATION (HC-13, formalized)

**Which offerings belong to a synchronized group:** derived generically, not hard-coded. For each `eg ∈ EG` with `synchronized[eg]=True`: take `groupOf⁻¹(eg)` = the courses listed against `eg` in `elective_group_courses.csv`; then take every offering `o ∈ O` with `courseOf[o]` in that course set. This produces one `SynchronizedOfferingGroups` entry per synchronized elective group — for the corrected dataset, 6 groups, but the model iterates over however many rows `elective_groups.csv` contains, with no assumption about the number 6.

**How synchronization is enforced:** for every pair of offerings `o₁,o₂` in the same group entry, add `Start[o₁,s]=Start[o₂,s]` for matching session indices `s` (session 1 of one synced to session 1 of the other, etc., assuming equal `reqSessions` within a synchronized group — an implicit data expectation worth a preprocessing sanity check, not itself a new constraint type).

**Interaction with student conflicts:** synchronization constrains *offerings* to share a slot; HC-04's per-student check then operates on top of that shared slot exactly as it would for any other elective offering — a synchronized elective still has to clear every enrolled student's individual non-collision requirement (Part 11), synchronization doesn't relax that, it just removes cross-section slot choice for that specific course.

**What changes if `synchronized` is later set `False` for a group:** the equality constraints for that group's offerings are simply not generated (the preprocessing step in Part 4 checks the flag per-group) — each section's offering of that elective becomes an independently-scheduled offering subject only to the normal HC-03/HC-04/HC-13-fulfilment rules, with no code change required, only a data change. This is the direct payoff of deriving synchronization from the dataset rather than encoding it structurally.

---

## PART 13 — FIXED EVENTS (HC-14, formalized as a generic mechanism)

```
FIXED EVENT (fe ∈ FE, from fixed_events.csv)
     ↓
SCOPE (eventScope[fe]: ALL | ALL_FACULTY | ROOM:<room_id> | FACULTY:<faculty_id> | SECTION:<section_id> | ...)
     ↓
TIME WINDOW (eventWindow[fe]: day + start_time + end_time, converted to the set of overlapping T-slots)
     ↓
BLOCKED ASSIGNMENTS: for every entity matched by the scope, every T-slot overlapping the window is removed from that entity's usable-slot set
```

- **scope=ALL** (e.g. `EV002` lunch): every offering's `Start[o,s]` domain excludes the blocked slots, regardless of room/faculty/section.
- **scope=ALL_FACULTY** (e.g. `EV001` weekly meeting): every faculty member's `ValidFacultySlots(f)` (Part 4) has the blocked slots removed before `Teacher`-conditioned domain restrictions (HC-06) are built — so any offering taught by *any* faculty is blocked from that window, mechanically via the same channel as ordinary unavailability.
- **room-specific scope** (not present in the corrected dataset's 2 current rows, but the mechanism must support it): would remove the blocked slots from that specific room's `ValidRoomSlots(r)` only.
- **faculty-specific scope:** would remove blocked slots from that one faculty's `ValidFacultySlots(f)` only.
- **section-specific scope:** would remove blocked slots from that section's offerings' `Start` domains only.
- **Future/unknown scopes:** the mechanism is a lookup — "scope string → which entity-availability table to intersect against" — so adding a new scope value only requires adding one more branch to that lookup, not new constraint types. This satisfies the requirement to build a generic mechanism rather than hard-coding the two current events (which the corrected dataset happens to have) by name or time.

This directly implements Round 1's HC-14/A03 finding that the 2 current rows are not asserted to be complete — the mechanism supports arbitrarily many future events of arbitrary scope without modification.

---

## PART 14 — FACULTY WORKLOAD (HC-16, formalized)

- **`maxDaily[f]` vs `maxWeekly[f]`:** two separate aggregate-sum constraints per faculty (Part 9's HC-16 row) — daily sums are computed per (faculty, day) pair over the 5 days, weekly sums once per faculty over the whole week. They are not the same constraint at different scopes merely by convention; a faculty member could satisfy the weekly cap while violating a daily cap on one heavy day, so both must be checked independently.
- **How multi-slot sessions contribute:** a 2-slot lab session taught by `f` contributes `duration[o]=2` hours (not 1) to both `f`'s daily sum for that day and `f`'s weekly sum — the hour-counting must use `duration[o]`, not session-count, or multi-slot labs would be systematically undercounted against the cap.
- **Visiting/adjunct faculty:** no special-casing needed — `maxDaily[f]` and `maxWeekly[f]` are read per-faculty directly from `faculty.csv`, and the corrected dataset already encodes the VISITING/ADJUNCT-vs-PERMANENT distinction as different per-row values (10–12 vs 18 weekly) rather than as a separate rule keyed on `employment_type` — the constraint formulation in Part 9 is oblivious to `employment_type` entirely, it just reads whatever number is in that faculty's row, which is the correct generic behavior.
- **Reminder (per Round 1 and the critical rules for this round):** `maxDaily`/`maxWeekly`/`minWeekly` are **SYNTHETIC PROTOTYPE ASSUMPTIONS** (Table A: HC-16's source). They are formalized as HARD bounds here so the prototype solver has an actual number to enforce, but this document does not assert they represent confirmed university HR policy — see Round 1 Table E, U01.

---

## PART 15 — SOFT CONSTRAINTS → OBJECTIVE TERMS

| ID | What is minimized/maximized | Violation measure | Direction | Normalized? | Suggested relative weight |
|---|---|---|---|---|---|
| SC-01 | Maximize faculty preference satisfaction | `Σ over scheduled sessions of (5 − facPref[Teacher[o], Start[o,s]])` (penalty = distance from max preference 5) | Lower penalty better | Yes — `facPref` is already 0–5, so the term is naturally bounded per session | High (this is the most directly dataset-grounded soft signal — a real field, `academic_rules.csv` tags it SOFT explicitly) |
| SC-02 | Minimize student/section gaps | For each section-day, sum of idle-slot counts between first and last scheduled slot that day | Lower better | Needs normalization (divide by max possible gap per day) since gap-count scales differently for busy vs light days | Medium |
| SC-03 | Minimize faculty idle gaps | Same idea as SC-02, computed per faculty-day using `Teacher`/`Start` | Lower better | Same normalization approach | Low-Medium |
| SC-04 | Balance faculty workload | Variance (or max-minus-min) of total assigned hours across `EligibleFaculty` pools, or simpler: sum of squared deviation from each faculty's own midpoint between `minWeekly` and `maxWeekly` | Lower better | Needs normalization (hours are on different scales per faculty due to differing caps) | Medium |
| SC-05 | Minimize room capacity wastage | `Σ over scheduled sessions of (capacity[Room[o,s]] − studentCount[o])` | Lower better | Needs normalization by room size range | Low |
| SC-06 | Avoid excessive consecutive classes | Penalty per faculty/section-day exceeding a chosen comfort threshold — **cannot be precisely defined**, since no dataset field specifies a threshold (Round 1 U06) | Lower better | N/A until a threshold is confirmed | Low-Medium, and **only includable once U06 is answered** — until then this term should be omitted rather than given an invented threshold |
| SC-07 | Spread multi-session courses across days | Penalty if two sessions of the same offering fall on the same day | Lower better | Naturally bounded (0 or 1 per offering-pair) | Medium |
| SC-08 | Reduce timetable fragmentation | Penalty for non-contiguous session blocks per section-day (related to but distinct from SC-02 — SC-02 counts idle time, SC-08 counts the number of separate contiguous "runs") | Lower better | Needs normalization | Low |
| SC-09 | Meet faculty minimum weekly hours | `Σ over faculty of max(0, minWeekly[f] − actualWeeklyHours[f])` | Lower better | Needs normalization by `minWeekly[f]` itself (relative shortfall) | Low-Medium |

**Weighted-sum vs. lexicographic:** a **weighted-sum objective is preferable** here, not a strict lexicographic ordering, for two reasons grounded in the actual constraint set: (1) several soft terms (SC-02/SC-03 gaps, SC-05 wastage, SC-08 fragmentation) are genuinely comparable trade-offs rather than a strict priority chain — e.g. a slightly worse room-fit to achieve meaningfully better faculty preference satisfaction is a reasonable trade a real administrator would want available, which lexicographic ordering forecloses; (2) a strict lexicographic ordering over 8–9 terms would require solving up to 8–9 sequential optimization passes (fixing each higher-priority term's optimal value before moving to the next), which is far more expensive and is not justified by anything in the approved specification, which never states one soft goal must dominate another absolutely. Weights should be treated as configurable (not hard-coded as final), since no source document specifies their exact relative importance — this itself belongs in a future confirmation item, not invented here as settled.

---

## PART 16 — OBJECTIVE FUNCTION

**Hierarchy (never violated):**
1. **Feasibility / HARD + activated CONDITIONAL constraints** — these are structural constraints on the CP-SAT model (Parts 9–10), not objective terms. No soft term ever appears as a constraint bound, and no soft weight can ever cause a HARD constraint to be dropped — this is enforced by construction (soft terms live exclusively in the `Minimize(...)` expression; HARD/CONDITIONAL constraints live exclusively in `Add(...)` calls), not by making the weights very large. A model where hard constraints are just heavily-weighted soft terms would risk being violated under objective pressure — that is explicitly avoided.
2. Within the objective, once feasibility is fixed, the SOFT terms (Part 15) are combined into one weighted sum: `Minimize( w1·SC01_penalty + w2·SC02_penalty + ... + w9·SC09_penalty )`, with each term normalized (where noted in Part 15) before weighting, so that weights reflect genuine priority rather than accidentally reflecting differing raw scales.
3. The prompt's requested priority order (faculty/student convenience → faculty preference → workload balance → room utilization → timetable quality) maps onto the weights `w1..w9` as **relative** emphasis (e.g. SC-01 preference and SC-02/SC-03 convenience terms weighted higher than SC-05 room-utilization or SC-08 fragmentation) — but this document does not assign specific numeric weight values, since the approved specification provides no numeric priority ordering to derive them from (only a qualitative list in the Round 2 instructions) and inventing precise numbers here would violate the "do not invent university rules" / "do not choose arbitrary weights without explanation" instructions. **Recommendation for the implementation phase:** expose weights as configurable parameters with the *relative* ordering above as the documented default, tunable once real stakeholders can react to sample outputs — this is an implementation-roadmap item (Part 20), not a modeling gap.

---

## PART 17 — INFEASIBILITY STRATEGY

- **What CP-SAT returns:** `INFEASIBLE` (or `UNKNOWN` if it times out before proving either feasibility or infeasibility — a distinction the diagnostic layer must not conflate).
- **Identifying problematic offerings:** systematically relax constraint groups (e.g. temporarily drop HC-16's workload cap, or widen one faculty's `ValidFacultySlots`) and re-solve; whichever relaxation restores feasibility identifies the binding constraint. This is most tractable per-offering by first attempting to solve a reduced model containing only that offering's own hard constraints plus the university-wide collision constraints already fixed by other offerings, to localize which offering is unplaceable rather than treating the whole 133-offering model as an opaque single failure.
- **Identifying bottleneck faculty/rooms:** cross-reference `EligibleFaculty(c)` ∩ currently-uncommitted faculty-slot pairs, and `CompatibleRoomsByEquipment(c)` ∩ currently-uncommitted room-slot pairs, for the offering(s) implicated above — this directly surfaces cases like C028's single equipment-matching room or the single PHYSICS_LAB room (Part 7) as the diagnosed cause, generically, not by name-matching those courses.
- **Relaxation diagnostics:** an IIS-style (irreducible inconsistent subsystem) search, or a simpler staged approach — attempt the solve with each *individually relaxable* constraint family (see below) turned off one at a time (or via CP-SAT's built-in assumption/soft-constraint infeasibility-explanation support, if used), reporting the smallest set whose removal restores feasibility.
- **Constraints that may be relaxed (with explicit sign-off, never silently):** HC-16 (workload caps — flagged SYNTHETIC PROTOTYPE ASSUMPTION), HC-13's identical-slot synchronization requirement (flagged U03), and any/all SC-* soft terms (which are not hard bounds to begin with, so "relaxing" them just means accepting a worse objective, not a validity change).
- **Constraints that can never be relaxed:** HC-01, HC-02, HC-04 (collision family), HC-05 (eligibility), HC-06/HC-07 (availability), HC-08/HC-09 (capacity/type), HC-11 (equipment, within its documented two-tier scope), HC-12 (contiguity), HC-14 (fixed events) — identical to the Round 1 "never relaxable" list, carried forward unchanged, since nothing in Round 2's modeling work provides new grounds to revisit that classification.
- **Design goal for the eventual API:** return which specific offering(s) failed to place, which specific constraint(s) were binding, and 1–3 concrete, human-actionable suggestions (e.g. "faculty F0xx has only 6/35 available slots and is the sole eligible+available choice for 2 offerings — consider widening their availability or adding a second eligible faculty") — never a bare "Timetable generation failed."

---

## PART 18 — SOLVER OUTPUT

**Per scheduled session** (one row per `(o,s)` in the solution):

| Field | Derived from |
|---|---|
| timetable ID | generation-run identifier (not a solver output per se — assigned by the orchestrating layer) |
| offering ID | `o` |
| course ID | `courseOf[o]` |
| course name | lookup in `courses.csv` |
| section | `sectionOf[o]` |
| year, branch | lookup via `sections.csv` → `programs.csv` (reporting-only attributes, per Part 2's note that these aren't modeling sets) |
| faculty | `Teacher[o]` |
| room | `Room[o,s]` |
| day | `slotDay[Start[o,s]]` |
| start time | `slotStart[Start[o,s]]` |
| end time | computed from `slotStart[Start[o,s]] + duration[o]` slots' worth of clock time (i.e. the end time of the *last* occupied slot) |
| duration | `duration[o]` |
| session number | `s` |

**Also defined:**
- **Solver status:** OPTIMAL / FEASIBLE (time-limited) / INFEASIBLE / UNKNOWN.
- **Objective value:** the achieved weighted-sum value from Part 16.
- **Hard constraint violations:** should be **zero** in any returned solution by construction (Part 16's hierarchy) — this field exists as a sanity-check/assertion in the extraction layer, not as an expected non-zero report.
- **Soft constraint scores:** the individual (un-weighted, and separately weighted) per-SC-ID penalty values from Part 15, so an administrator can see *which* soft goals were sacrificed, not just the aggregate.
- **Generation time:** wall-clock solve duration.
- **Infeasibility diagnostics:** per Part 17, only populated when status is INFEASIBLE.

---

## PART 19 — MODEL COMPLEXITY (from the actual corrected dataset — no invented figures)

| Quantity | Value (corrected dataset) |
|---|---|
| Offerings (`|O|`) | 133 |
| Total required sessions across all offerings (`Σ reqSessions[o]`) | 370 |
| Offerings/sessions requiring multi-slot (duration=2) contiguity (HC-12/CC-03 active) | 16 offering rows (all 10 lab/workshop courses × their sections) |
| Faculty (`|F|`) | 40 |
| Rooms (`|R|`) | 29 |
| Time slots (`|T|`) | 35 (5 days × 7 periods) |
| Faculty-course eligibility pairs (avg `Teacher[o]` domain size) | 777 pairs total; mean 12 eligible faculty per course (min 3, max 18) |
| Sections | 16 |
| Students | 1000 |
| CORE enrollments (handled at section-level, not expanded per-student) | 6000 |
| OAE/PCE enrollments (handled at student-level) | 750 |
| Elective groups requiring synchronization equality constraints | 6 |
| Fixed events | 2 |
| Core decision variables | `Start[o,s]` — 370 (one per session instance); `Teacher[o]` — 133 (one per offering); `Room[o,s]` — 370 (one per session instance). **Total ≈ 873 primary decision variables**, before any CP-SAT-internal auxiliary/interval/boolean variables the solver itself introduces during model-building (e.g. one interval variable per session per no-overlap grouping, and reification booleans for the conditional domain restrictions in Parts 9–10) |
| Major constraint families | HC-01/02/03/04 (collision, via NoOverlap groups — roughly one group per faculty (40), per room (29), per section (16), plus ~1000 potential per-student groups but only the ~750-enrollment subset genuinely need one, since CORE is handled at section granularity) ≈ 40+29+16+(≤1000, effectively far fewer once limited to students with elective enrollments — 750 enrollment rows across at most 1000 students) groups; HC-06/07/14 (availability/fixed-event domain restrictions, applied per variable at build time, not separate runtime constraints); HC-13 (6 synchronization equality-constraint groups); HC-16 (40 faculty × 6 aggregate-sum constraints (5 daily + 1 weekly) = 240 sum constraints) |

**What is likely to dominate solver complexity:**
1. **The faculty/room/section NoOverlap constraint families** — these are the classic scheduling bottleneck in any CP-SAT timetabling model, and here they interact with *variable* (not fixed) `Teacher`/`Room` assignments, meaning the no-overlap groupings themselves depend on other decision variables (reified/optional intervals), which is more expensive to propagate than a model where faculty/room were pre-assigned.
2. **The scarce-resource offerings** (PHYSICS_LAB's 1 room, C028's 1 equipment-matching room, the 4 faculty with 6/35 availability) — small domains individually reduce search space locally, but they create tight global coupling: many offerings competing for very few valid (room,slot) or (faculty,slot) combinations tends to slow propagation and is the most probable source of both long solve times and genuine infeasibility (Part 17), more than the raw variable count would suggest.
3. **The elective/synchronization layer** — while only 6 groups and ~750 enrollment rows, the per-student NoOverlap groups plus the cross-offering equality constraints from HC-13 interact with the shared-room/shared-faculty constraints for the 18 multi-section courses, creating a denser sub-graph of interacting constraints than the CORE-only portion of the model, disproportionate to its smaller row count.

The overall problem size (≈873 primary variables, 133 offerings, 370 sessions) is **modest** for CP-SAT in absolute terms; the complexity risk here is structural (tight bottleneck resources, variable-indexed no-overlap groupings) rather than raw scale.

---

## PART 20 — IMPLEMENTATION ROADMAP (non-code, forward-looking only)

1. Build the preprocessing layer (Part 4) exactly as specified, over the corrected dataset, and unit-verify its outputs (e.g. confirm `ContiguousSlotSets` genuinely excludes the lunch-gap pairing) before any CP-SAT code is written.
2. Build the three core decision variables (Part 5) with domains constructed directly from Part 4's derived data.
3. Add HC-01…HC-16 in the order given in Part 9, verifying after each addition that the model remains satisfiable on a small manual test case.
4. Add CC-01…CC-08 (Part 10) — largely already implied by domain construction, so this step is mostly about confirming, not adding, code.
5. Add the soft objective terms (Part 15) with normalization, leaving weights as named constants pending stakeholder input (Part 16) — explicitly **not** to be finalized without the confirmation items from Round 1 Table E and this round's SC-06 caveat (U06).
6. Build the infeasibility diagnostic layer (Part 17) as a first-class feature, not an afterthought, given the SIH problem statement's explicit complaint about the manual process's failure mode.
7. Build the solution-extraction layer (Part 18).
8. Only then — outside Round 2's scope entirely — begin FastAPI/database/frontend work.

---

## ROUND 2 STATUS:

# READY FOR IMPLEMENTATION

All 16 HARD constraints, all 8 CONDITIONAL constraints, and all 9 SOFT constraints from the approved Round 1 specification have a precise mathematical/CP-SAT formulation above, grounded in the corrected dataset with no invented parameters. Three items remain genuinely open and are correctly *not* silently resolved here:
- **SC-06** (avoid excessive consecutive classes) cannot be given a concrete threshold — no dataset field exists (Round 1 U06) — and should be omitted from the initial objective until answered, rather than shipped with an invented number.
- **Objective weights** (Part 16) are deliberately left as configurable parameters, not fixed values, since no source document specifies their numeric relative priority.
- **Lab batch-splitting** (A07/U09) remains explicitly out of scope for this model, as instructed — the corrected dataset has no batching structure to model against.

None of these three block starting implementation of the 16+8+9 constraints that *are* fully specified; they should be tracked as explicit open items carried into the implementation phase rather than blockers to beginning it.
