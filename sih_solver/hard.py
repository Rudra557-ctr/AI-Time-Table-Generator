"""CP4/CP5 – HARD constraints (Round2 Part 9) – FIXED.

Implements HC01 faculty / HC02 room / HC03 section collisions correctly for
multi-slot (duration 2) labs via occupied-slot sets.

Uses pairwise reified allowed assignments so that same faculty/room =>
occupied sets must be disjoint, not just starts differ.
"""
from ortools.sat.python import cp_model
from .preprocessing import contiguous_slot_sets
from datetime import datetime
import itertools

def _parse_time(t):
    return datetime.strptime(t.strip(), "%H:%M")

def _build_slot_maps(time_slots):
    """Return slot_to_idx, idx_to_slot, slot_next for duration 2, and occupied map per slot_id per duration."""
    all_slots = [s["slot_id"] for s in time_slots]
    slot_to_idx = {sid:i for i,sid in enumerate(all_slots)}
    idx_to_slot = {i:sid for sid,i in slot_to_idx.items()}
    # next map for duration 2
    slot_next={}
    csets = contiguous_slot_sets(time_slots, k=2)
    for day, groups in csets.items():
        for tup in groups:
            slot_next[tup[0]] = tup[1]
    return slot_to_idx, idx_to_slot, slot_next

def _occupied_set(slot_id, duration, slot_next):
    if duration==1:
        return (slot_id,)
    nxt = slot_next.get(slot_id)
    if nxt:
        return (slot_id, nxt)
    return (slot_id,)

def _non_overlapping_pairs(duration1, duration2, valid_starts1, valid_starts2, slot_next):
    """Return list of (start1, start2) idx pairs where occupied sets are disjoint."""
    # Convert slot_id to idx via global map? We'll compute using slot_ids then map to idx
    # valid_starts are sets of slot_id strings
    pairs=[]
    for s1 in valid_starts1:
        occ1 = set(_occupied_set(s1, duration1, slot_next))
        for s2 in valid_starts2:
            occ2 = set(_occupied_set(s2, duration2, slot_next))
            if occ1.isdisjoint(occ2):
                pairs.append((s1,s2))
    return pairs

def add_faculty_collision(model, Start, Teacher, offerings, time_slots):
    """HC01: No faculty double-booking – FIXED via next-slot handling (efficient)."""
    slot_to_idx, idx_to_slot, slot_next = _build_slot_maps(time_slots)
    all_slots = [s["slot_id"] for s in time_slots]
    next_idx_arr = [slot_to_idx[slot_next[sid]] if sid in slot_next else -1 for sid in all_slots]
    sessions = [(o["offering_id"], s, int(o["session_duration"])) for o in offerings for s in range(int(o["required_sessions"]))]
    next_Start = {}
    for (oid,s,d) in sessions:
        if d==2:
            nxt_var = model.NewIntVar(-1, len(all_slots)-1, f"next_{oid}_{s}")
            model.AddElement(Start[(oid,s)], next_idx_arr, nxt_var)
            next_Start[(oid,s)] = nxt_var
    for (oid1,s1,d1), (oid2,s2,d2) in itertools.combinations(sessions, 2):
        if oid1==oid2:
            model.Add(Start[(oid1,s1)] != Start[(oid2,s2)])
            if d1==2 and d2==2:
                model.Add(next_Start[(oid1,s1)] != Start[(oid2,s2)])
                model.Add(Start[(oid1,s1)] != next_Start[(oid2,s2)])
                model.Add(next_Start[(oid1,s1)] != next_Start[(oid2,s2)])
            elif d1==2:
                model.Add(next_Start[(oid1,s1)] != Start[(oid2,s2)])
            elif d2==2:
                model.Add(Start[(oid1,s1)] != next_Start[(oid2,s2)])
            continue
        b = model.NewBoolVar(f"same_fac_{oid1}_{s1}_{oid2}_{s2}")
        model.Add(Teacher[oid1] == Teacher[oid2]).OnlyEnforceIf(b)
        model.Add(Teacher[oid1] != Teacher[oid2]).OnlyEnforceIf(b.Not())
        model.Add(Start[(oid1,s1)] != Start[(oid2,s2)]).OnlyEnforceIf(b)
        if d1==2 and d2==2:
            model.Add(next_Start[(oid1,s1)] != Start[(oid2,s2)]).OnlyEnforceIf(b)
            model.Add(Start[(oid1,s1)] != next_Start[(oid2,s2)]).OnlyEnforceIf(b)
            model.Add(next_Start[(oid1,s1)] != next_Start[(oid2,s2)]).OnlyEnforceIf(b)
        elif d1==2:
            model.Add(next_Start[(oid1,s1)] != Start[(oid2,s2)]).OnlyEnforceIf(b)
        elif d2==2:
            model.Add(Start[(oid1,s1)] != next_Start[(oid2,s2)]).OnlyEnforceIf(b)

def add_room_collision(model, Start, Room, offerings, time_slots=None):
    """HC02: No room double-booking – FIXED via next-slot handling (efficient)."""
    if time_slots is None:
        import itertools
        sessions = [(o["offering_id"], s) for o in offerings for s in range(int(o["required_sessions"]))]
        for (oid1,s1), (oid2,s2) in itertools.combinations(sessions, 2):
            b = model.NewBoolVar(f"same_room_{oid1}_{s1}_{oid2}_{s2}")
            model.Add(Room[(oid1,s1)] == Room[(oid2,s2)]).OnlyEnforceIf(b)
            model.Add(Room[(oid1,s1)] != Room[(oid2,s2)]).OnlyEnforceIf(b.Not())
            model.Add(Start[(oid1,s1)] != Start[(oid2,s2)]).OnlyEnforceIf(b)
        return
    import itertools
    slot_to_idx, idx_to_slot, slot_next = _build_slot_maps(time_slots)
    all_slots = [s["slot_id"] for s in time_slots]
    next_idx_arr = [slot_to_idx[slot_next[sid]] if sid in slot_next else -1 for sid in all_slots]
    sessions = [(o["offering_id"], s, int(o["session_duration"])) for o in offerings for s in range(int(o["required_sessions"]))]
    next_Start = {}
    for (oid,s,d) in sessions:
        if d==2:
            nxt_var = model.NewIntVar(-1, len(all_slots)-1, f"nextR_{oid}_{s}")
            model.AddElement(Start[(oid,s)], next_idx_arr, nxt_var)
            next_Start[(oid,s)] = nxt_var
    for (oid1,s1,d1), (oid2,s2,d2) in itertools.combinations(sessions, 2):
        b = model.NewBoolVar(f"same_room_{oid1}_{s1}_{oid2}_{s2}")
        model.Add(Room[(oid1,s1)] == Room[(oid2,s2)]).OnlyEnforceIf(b)
        model.Add(Room[(oid1,s1)] != Room[(oid2,s2)]).OnlyEnforceIf(b.Not())
        model.Add(Start[(oid1,s1)] != Start[(oid2,s2)]).OnlyEnforceIf(b)
        if d1==2 and d2==2:
            model.Add(next_Start[(oid1,s1)] != Start[(oid2,s2)]).OnlyEnforceIf(b)
            model.Add(Start[(oid1,s1)] != next_Start[(oid2,s2)]).OnlyEnforceIf(b)
            model.Add(next_Start[(oid1,s1)] != next_Start[(oid2,s2)]).OnlyEnforceIf(b)
        elif d1==2:
            model.Add(next_Start[(oid1,s1)] != Start[(oid2,s2)]).OnlyEnforceIf(b)
        elif d2==2:
            model.Add(Start[(oid1,s1)] != next_Start[(oid2,s2)]).OnlyEnforceIf(b)

def _next_start_map(model, Start, sessions, time_slots, tag):
    """Build next_Start for duration-2 sessions (shared helper)."""
    slot_to_idx, idx_to_slot, slot_next = _build_slot_maps(time_slots)
    all_slots = [s["slot_id"] for s in time_slots]
    next_idx_arr = [slot_to_idx[slot_next[sid]] if sid in slot_next else -1 for sid in all_slots]
    next_Start = {}
    for (oid, s, d) in sessions:
        if d == 2:
            nxt = model.NewIntVar(-1, len(all_slots)-1, f"{tag}_{oid}_{s}")
            model.AddElement(Start[(oid, s)], next_idx_arr, nxt)
            next_Start[(oid, s)] = nxt
    return next_Start

def _add_disjoint_pair(model, Start, next_Start, a, b):
    """Enforce occupied sets of two sessions (a,b) disjoint."""
    (oid1, s1, d1), (oid2, s2, d2) = a, b
    model.Add(Start[(oid1, s1)] != Start[(oid2, s2)])
    if d1 == 2 and d2 == 2:
        if (oid1, s1) in next_Start and (oid2, s2) in next_Start:
            model.Add(next_Start[(oid1, s1)] != Start[(oid2, s2)])
            model.Add(Start[(oid1, s1)] != next_Start[(oid2, s2)])
            model.Add(next_Start[(oid1, s1)] != next_Start[(oid2, s2)])
    elif d1 == 2:
        if (oid1, s1) in next_Start:
            model.Add(next_Start[(oid1, s1)] != Start[(oid2, s2)])
    elif d2 == 2:
        if (oid2, s2) in next_Start:
            model.Add(Start[(oid1, s1)] != next_Start[(oid2, s2)])

def add_section_collision(model, Start, offerings, time_slots=None, sync_groups=None, alt_pairs=None,
                           conflict_pairs=None):
    """HC03: No section double-booking – FIXED via next handling.
    Alternative offerings in the same synchronized elective group (same section)
    are skipped (a student attends only one).

    conflict_pairs: optional set of (section_id_a, section_id_b) pairs whose
    sections physically share the same students despite having distinct
    section_ids (e.g. a parent cohort and its lab/tutorial sub-batches, from
    section_conflicts.csv). Sessions under section_id_a are forbidden from
    coinciding with sessions under section_id_b, same as within-section HC03.
    """
    from collections import defaultdict
    if alt_pairs is None:
        alt_pairs = set()
        if sync_groups:
            for g in sync_groups:
                oids = sorted(g["offerings"])
                for i in range(len(oids)):
                    for j in range(i+1, len(oids)):
                        alt_pairs.add((oids[i], oids[j]))
    def is_alt(o1, o2):
        return (o1, o2) in alt_pairs or (o2, o1) in alt_pairs
    if time_slots is None:
        sec_to_sessions = defaultdict(list)
        for o in offerings:
            for s in range(int(o["required_sessions"])):
                sec_to_sessions[o["section_id"]].append((o["offering_id"], s))
        def _no_overlap(pairs):
            for (oid1,s1), (oid2,s2) in pairs:
                if is_alt(oid1, oid2):
                    continue
                model.Add(Start[(oid1,s1)] != Start[(oid2,s2)])
        for sec, sess_list in sec_to_sessions.items():
            _no_overlap(itertools.combinations(sess_list, 2))
        for (sec_a, sec_b) in (conflict_pairs or ()):
            _no_overlap(itertools.product(sec_to_sessions.get(sec_a, []), sec_to_sessions.get(sec_b, [])))
        return
    slot_to_idx, idx_to_slot, slot_next = _build_slot_maps(time_slots)
    all_slots = [s["slot_id"] for s in time_slots]
    next_idx_arr = [slot_to_idx[slot_next[sid]] if sid in slot_next else -1 for sid in all_slots]
    next_Start = {}
    for o in offerings:
        for s in range(int(o["required_sessions"])):
            oid = o["offering_id"]
            d = int(o["session_duration"])
            if d==2:
                nxt_var = model.NewIntVar(-1, len(all_slots)-1, f"nextS_{oid}_{s}")
                model.AddElement(Start[(oid,s)], next_idx_arr, nxt_var)
                next_Start[(oid,s)] = nxt_var
    sec_to_sessions = defaultdict(list)
    for o in offerings:
        d = int(o["session_duration"])
        for s in range(int(o["required_sessions"])):
            sec_to_sessions[o["section_id"]].append((o["offering_id"], s, d))
    def _no_overlap(pairs):
        for (oid1,s1,d1), (oid2,s2,d2) in pairs:
            if is_alt(oid1, oid2):
                continue
            model.Add(Start[(oid1,s1)] != Start[(oid2,s2)])
            if d1==2 and d2==2:
                model.Add(next_Start[(oid1,s1)] != Start[(oid2,s2)])
                model.Add(Start[(oid1,s1)] != next_Start[(oid2,s2)])
                model.Add(next_Start[(oid1,s1)] != next_Start[(oid2,s2)])
            elif d1==2:
                model.Add(next_Start[(oid1,s1)] != Start[(oid2,s2)])
            elif d2==2:
                model.Add(Start[(oid1,s1)] != next_Start[(oid2,s2)])
    for sec, sess_list in sec_to_sessions.items():
        _no_overlap(itertools.combinations(sess_list, 2))
    for (sec_a, sec_b) in (conflict_pairs or ()):
        _no_overlap(itertools.product(sec_to_sessions.get(sec_a, []), sec_to_sessions.get(sec_b, [])))


def _req(offerings, oid):
    for o in offerings:
        if o["offering_id"] == oid:
            return o["required_sessions"]
    return 0

def _dur(offerings, oid):
    for o in offerings:
        if o["offering_id"] == oid:
            return o["session_duration"]
    return "1"

def add_student_collision(model, Start, offerings, time_slots, student_enrollments, students):
    """HC04: No student double-booking for OAE/PCE electives.
    Enforces that a student's elective offering(s) do not collide with their
    own section's CORE offerings or with a second elective offering.
    Same-section pairs are already handled by HC03, so we only add constraints
    for cross-section electives + elective-vs-core per student.
    """
    from collections import defaultdict
    if not student_enrollments or not students:
        return
    stu_sec = {s["student_id"]: s["section_id"] for s in students}
    oid_sec = {o["offering_id"]: o["section_id"] for o in offerings}
    oid_by_course = defaultdict(list)
    for o in offerings:
        oid_by_course[o["course_id"]].append(o["offering_id"])
    sec_offerings = defaultdict(list)
    for o in offerings:
        sec_offerings[o["section_id"]].append(o["offering_id"])
    all_sessions = [(o["offering_id"], s, int(o["session_duration"]))
                    for o in offerings for s in range(int(o["required_sessions"]))]
    next_Start = _next_start_map(model, Start, all_sessions, time_slots, "nextStu")
    for e in student_enrollments:
        if e["enrollment_type"] not in ("OAE", "PCE"):
            continue
        stu = e["student_id"]
        sec = stu_sec.get(stu)
        if not sec:
            continue
        cands = oid_by_course.get(e["course_id"], [])
        if not cands:
            continue
        elect_oids = [oid for oid in cands if oid_sec.get(oid) == sec] or cands
        core_oids = [oid for oid in sec_offerings.get(sec, []) if oid not in elect_oids]
        for eoid in elect_oids:
            if oid_sec.get(eoid) != sec:
                for coid in core_oids:
                    for s1 in range(int(_req(offerings, eoid))):
                        for s2 in range(int(_req(offerings, coid))):
                            _add_disjoint_pair(
                                model, Start, next_Start,
                                (eoid, s1, int(_dur(offerings, eoid))),
                                (coid, s2, int(_dur(offerings, coid))))
        for a_i in range(len(elect_oids)):
            for b_i in range(a_i + 1, len(elect_oids)):
                a, b = elect_oids[a_i], elect_oids[b_i]
                if a == b:
                    continue
                for s1 in range(int(_req(offerings, a))):
                    for s2 in range(int(_req(offerings, b))):
                        _add_disjoint_pair(
                            model, Start, next_Start,
                            (a, s1, int(_dur(offerings, a))),
                            (b, s2, int(_dur(offerings, b))))

def add_synchronized_constraints(model, Start, offerings, time_slots, sync_groups):
    """HC13: Synchronized electives must share the same slot per session idx.
    Each group contains offerings of the SAME course across sections (a shared
    cross-section elective class) -> all must run at the same slot.
    """
    from collections import defaultdict
    if not sync_groups:
        return
    for group in sync_groups:
        oids = sorted(group["offerings"])
        if len(oids) < 2:
            continue
        by_req = defaultdict(list)
        for oid in oids:
            by_req[int(_req(offerings, oid))].append(oid)
        for req, req_members in by_req.items():
            base = req_members[0]
            for oid in req_members[1:]:
                for s in range(req):
                    model.Add(Start[(base, s)] == Start[(oid, s)])
