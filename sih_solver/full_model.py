"""CP5 Full HARD model (HC01-16) assembly.

Combines CP3 variables + CP4 collisions + availability + fixed events + workload.
Used for CP5 feasibility test.
"""
from ortools.sat.python import cp_model
from .preprocessing import load_all, eligible_faculty_per_course, compatible_rooms_by_course, valid_faculty_slots, valid_room_slots, blocked_assignments, occupied_chain_map
from .model import build_variables
from .hard import add_faculty_collision, add_room_collision, add_section_collision, add_student_collision, add_synchronized_constraints

def add_availability_constraints(model, Start, Teacher, Room, meta):
    """HC06 faculty availability, HC07 room availability via AllowedAssignments.

    BUG FIX (found by independent post-solve validation, 2026-08-23): a
    duration>1 session occupies `duration` consecutive clock-contiguous
    slots starting at Start, not just the starting slot. The previous
    version only checked availability of the starting slot, so a 2-hour lab
    could be scheduled with a faculty/room that was available for the first
    hour but explicitly marked unavailable for the second — a real violation
    that CP-SAT reported as part of an "OPTIMAL" solution because the model
    itself under-constrained it. hard.py's HC01-03 collision constraints
    already handled multi-slot sessions correctly via a next_Start lookup;
    this mirrors that, generalized to any duration (not hardcoded to 2) via
    contiguous_slot_sets(..., k=duration): a start slot is only allowed if
    EVERY slot the session would occupy is available.
    """
    data = meta["data"]
    vfs = valid_faculty_slots(data["faculty_availability.csv"])
    vrs = valid_room_slots(data["room_availability.csv"])
    slot_to_idx = meta["slot_to_idx"]
    fac_to_idx = meta["fac_to_idx"]
    room_to_idx = meta["room_to_idx"]

    # start slot_id -> full tuple of slot_ids the session would occupy,
    # computed once per distinct duration actually present in the dataset.
    durations = sorted({int(o["session_duration"]) for o in meta["offerings"]})
    occupied_chain = {d: occupied_chain_map(data["time_slots.csv"], d) for d in durations}

    # Faculty availability: (Teacher, Start) allowed pairs
    for o in meta["offerings"]:
        oid = o["offering_id"]
        elig = meta["eligible"][o["course_id"]]
        chain = occupied_chain[int(o["session_duration"])]
        # Build allowed tuples for this offering: for each eligible fac, for each
        # valid start slot where the fac is available for the WHOLE occupied chain
        allowed = []
        for fac in elig:
            f_idx = fac_to_idx[fac]
            valid_slots = vfs.get(fac, set())
            for sid in valid_slots:
                occ = chain.get(sid)
                if occ is not None and all(s in valid_slots for s in occ):
                    allowed.append((f_idx, slot_to_idx[sid]))
        if not allowed:
            # No allowed slot for this offering -> infeasible
            continue
        for s in range(int(o["required_sessions"])):
            model.AddAllowedAssignments([Teacher[oid], Start[(oid,s)]], allowed)
    # Room availability similarly
    for o in meta["offerings"]:
        oid = o["offering_id"]
        comp_rooms = meta["compatible"].get(o["course_id"], [])
        chain = occupied_chain[int(o["session_duration"])]
        allowed_r = []
        for r in comp_rooms:
            rid = r["room_id"]
            r_idx = room_to_idx[rid]
            valid_slots = vrs.get(rid, set())
            for sid in valid_slots:
                occ = chain.get(sid)
                if occ is not None and all(s in valid_slots for s in occ):
                    allowed_r.append((r_idx, slot_to_idx[sid]))
        for s in range(int(o["required_sessions"])):
            if allowed_r:
                model.AddAllowedAssignments([Room[(oid,s)], Start[(oid,s)]], allowed_r)

def add_fixed_events(model, Start, meta):
    """HC14: block fixed event slots.

    BUG FIX (found by independent post-solve validation, 2026-08-23): same
    duration>1 gap as HC06/HC07 (see add_availability_constraints above) --
    this only ever forbade Start itself from being a blocked slot, so a
    duration-2 session starting one slot before a blocked event could still
    occupy it via its second hour (e.g. a 2-hour lab starting 11:00 quietly
    running through a 12:00-13:00 blocked faculty-meeting slot). Now forbids
    any start slot whose full occupied chain (occupied_chain_map, any
    duration) intersects the blocked slots, not just an exact-match start.
    """
    blocked = blocked_assignments(meta["data"]["fixed_events.csv"], meta["data"]["time_slots.csv"])
    slot_to_idx = meta["slot_to_idx"]
    data = meta["data"]
    durations = sorted({int(o["session_duration"]) for o in meta["offerings"]})
    chains_by_duration = {d: occupied_chain_map(data["time_slots.csv"], d) for d in durations}
    for fe_id, info in blocked.items():
        scope = info["scope"]
        slots = info["slots"]
        if not slots or scope not in ("ALL", "ALL_FACULTY"):
            # Room-specific scope not present in this dataset.
            continue
        for o in meta["offerings"]:
            oid = o["offering_id"]
            chain = chains_by_duration[int(o["session_duration"])]
            forbidden_starts = [start_sid for start_sid, occ in chain.items() if any(sid in slots for sid in occ)]
            forbidden_indices = [slot_to_idx[sid] for sid in forbidden_starts if sid in slot_to_idx]
            if not forbidden_indices:
                continue
            for s in range(int(o["required_sessions"])):
                for b_idx in forbidden_indices:
                    model.Add(Start[(oid, s)] != b_idx)

def add_workload_constraints(model, Start, Teacher, meta):
    """HC16: max daily/weekly hours per faculty – FIXED daily cap per R001 (efficient shared is_in_day)."""
    if not meta.get("slot_to_idx"):
        return
    day_order = {"MON":0,"TUE":1,"WED":2,"THU":3,"FRI":4}
    day_names = ["MON","TUE","WED","THU","FRI"]
    max_slot_idx = max(meta["slot_to_idx"].values())
    day_by_slot = [0]*(max_slot_idx+1)
    for s in meta["data"]["time_slots.csv"]:
        day_by_slot[meta["slot_to_idx"][s["slot_id"]]] = day_order[s["day"]]
    # day_var per session (shared)
    day_var = {}
    for o in meta["offerings"]:
        for s in range(int(o["required_sessions"])):
            oid = o["offering_id"]
            dv = model.NewIntVar(0, 4, f"day_{oid}_{s}")
            model.AddElement(Start[(oid,s)], day_by_slot, dv)
            day_var[(oid,s)] = dv
    # is_in_day shared per session per day (1850 vars)
    is_in_day_shared = {}
    for o in meta["offerings"]:
        for s in range(int(o["required_sessions"])):
            oid = o["offering_id"]
            for day in day_names:
                day_idx = day_order[day]
                b = model.NewBoolVar(f"in_{oid}_{s}_{day}")
                model.Add(day_var[(oid,s)] == day_idx).OnlyEnforceIf(b)
                model.Add(day_var[(oid,s)] != day_idx).OnlyEnforceIf(b.Not())
                is_in_day_shared[(oid,s,day)] = b
    fac_to_idx = meta["fac_to_idx"]
    faculty_rows = {r["faculty_id"]: r for r in meta["data"]["faculty.csv"]}
    for fac_id, fac_idx in fac_to_idx.items():
        max_weekly = int(faculty_rows[fac_id]["max_hours_per_week"])
        max_daily = int(faculty_rows[fac_id]["max_hours_per_day"])
        weekly_terms = []
        daily_terms = {d: [] for d in day_names}
        for o in meta["offerings"]:
            if fac_id not in meta["eligible"].get(o["course_id"], set()):
                continue
            oid = o["offering_id"]
            dur = int(o["session_duration"])
            for s in range(int(o["required_sessions"])):
                is_assigned = model.NewBoolVar(f"is_{oid}_{s}_fac{fac_id}")
                model.Add(Teacher[oid] == fac_idx).OnlyEnforceIf(is_assigned)
                model.Add(Teacher[oid] != fac_idx).OnlyEnforceIf(is_assigned.Not())
                weekly_terms.append(dur * is_assigned)
                for day in day_names:
                    is_in_day = is_in_day_shared[(oid,s,day)]
                    is_on_day = model.NewBoolVar(f"on_{oid}_{s}_{day}_{fac_id}")
                    model.AddImplication(is_on_day, is_assigned)
                    model.AddImplication(is_on_day, is_in_day)
                    model.AddBoolOr([is_assigned.Not(), is_in_day.Not(), is_on_day])
                    daily_terms[day].append(dur * is_on_day)
        if weekly_terms:
            model.Add(sum(weekly_terms) <= max_weekly)
        for day in day_names:
            if daily_terms[day]:
                model.Add(sum(daily_terms[day]) <= max_daily)

def add_no_repeat_same_course_same_day(model, Start, meta):
    """HC12 FIX: at most 1 single-slot session of same course per section per day.
    Applies only where sessions_per_week>1 and session_duration==1.
    """
    from collections import defaultdict
    # Group offerings by (section_id, course_id) where course meets criteria
    courses_by_id = {c["course_id"]: c for c in meta["data"]["courses.csv"]}
    # Map (section,course) -> list of (oid, session_idx)
    groups = defaultdict(list)
    for o in meta["offerings"]:
        c = courses_by_id[o["course_id"]]
        if int(c["sessions_per_week"]) > 1 and int(c["session_duration"]) == 1:
            sec = o["section_id"]
            cid = o["course_id"]
            # Courses offered to multiple sections? Keep per section
            for s in range(int(o["required_sessions"])):
                groups[(sec, cid)].append((o["offering_id"], s))
    # For each group, at most 1 per day
    slot_to_day = {s["slot_id"]: s["day"] for s in meta["data"]["time_slots.csv"]}
    idx_to_slot = meta["idx_to_slot"]
    slot_to_idx = meta["slot_to_idx"]
    day_to_indices = {d: [slot_to_idx[s["slot_id"]] for s in meta["data"]["time_slots.csv"] if s["day"]==d] for d in ["MON","TUE","WED","THU","FRI"]}
    for (sec, cid), sess_list in groups.items():
        if len(sess_list) <= 1:
            continue
        # For each day, at most 1 of these sessions can be on that day
        for day in ["MON","TUE","WED","THU","FRI"]:
            day_slots = set(day_to_indices[day])
            # Create bools is_on_day per session
            bools = []
            for (oid, s) in sess_list:
                is_on_day = model.NewBoolVar(f"hc12_{sec}_{cid}_{oid}_{s}_{day}")
                # is_on_day => Start in day_slots
                model.AddAllowedAssignments([Start[(oid,s)]], [(v,) for v in day_slots]).OnlyEnforceIf(is_on_day)
                # not is_on_day => Start not in day_slots
                not_day = [v for v in slot_to_idx.values() if v not in day_slots]
                if not_day:
                    model.AddAllowedAssignments([Start[(oid,s)]], [(v,) for v in not_day]).OnlyEnforceIf(is_on_day.Not())
                bools.append(is_on_day)
            # At most 1
            model.Add(sum(bools) <= 1)

def build_full_hard_model(root=None, limit_offerings=None):
    """Build model with all HARDS (CP5). limit_offerings for testing."""
    model, Start, Teacher, Room, meta = build_variables(root)
    if limit_offerings is not None:
        offs = meta["offerings"][:limit_offerings]
        pass
    # Add core collisions – FIXED to handle duration 2 via occupied sets
    from .preprocessing import (synchronized_offering_groups, elective_alternative_pairs,
                                 parallel_offering_pairs, section_conflict_pairs)
    sync_groups = synchronized_offering_groups(meta["data"]["elective_groups.csv"],
                                               meta["data"]["elective_group_courses.csv"],
                                               meta["offerings"])
    alt_pairs = elective_alternative_pairs(meta["data"]["elective_groups.csv"],
                                           meta["data"]["elective_group_courses.csv"],
                                           meta["offerings"],
                                           meta["data"]["student_enrollments.csv"])
    # Extra alternative pairs the dataset's own pipeline already flagged
    # (parallel_offerings.csv, optional) -- union in, same exemption as elective alt_pairs.
    alt_pairs = alt_pairs | parallel_offering_pairs(meta["data"]["parallel_offerings.csv"])
    # Cross-section conflicts the dataset's own pipeline already flagged
    # (section_conflicts.csv, optional) -- e.g. a parent cohort and its
    # lab/tutorial sub-batches, which have distinct section_ids so HC03's
    # same-section-id grouping alone can't see they share physical students.
    conflict_pairs = section_conflict_pairs(meta["data"]["section_conflicts.csv"])
    add_faculty_collision(model, Start, Teacher, meta["offerings"], meta["data"]["time_slots.csv"])
    add_room_collision(model, Start, Room, meta["offerings"], meta["data"]["time_slots.csv"])
    add_section_collision(model, Start, meta["offerings"], meta["data"]["time_slots.csv"], sync_groups, alt_pairs,
                           conflict_pairs)
    # HC12 no repeat same course same day
    add_no_repeat_same_course_same_day(model, Start, meta)
    # HC04 student-level elective collision
    add_student_collision(model, Start, meta["offerings"], meta["data"]["time_slots.csv"],
                          meta["data"]["student_enrollments.csv"], meta["data"]["students.csv"])
    # HC13 synchronized electives
    add_synchronized_constraints(model, Start, meta["offerings"], meta["data"]["time_slots.csv"], sync_groups)
    # Add availability and fixed
    add_availability_constraints(model, Start, Teacher, Room, meta)
    add_fixed_events(model, Start, meta)
    # Workload weekly only
    add_workload_constraints(model, Start, Teacher, meta)
    return model, Start, Teacher, Room, meta
