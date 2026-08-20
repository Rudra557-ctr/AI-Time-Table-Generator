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

def add_section_collision(model, Start, offerings, time_slots=None):
    """HC03: No section double-booking – FIXED via next handling."""
    from collections import defaultdict
    if time_slots is None:
        sec_to_sessions = defaultdict(list)
        for o in offerings:
            for s in range(int(o["required_sessions"])):
                sec_to_sessions[o["section_id"]].append((o["offering_id"], s))
        for sec, sess_list in sec_to_sessions.items():
            for (oid1,s1), (oid2,s2) in itertools.combinations(sess_list, 2):
                model.Add(Start[(oid1,s1)] != Start[(oid2,s2)])
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
    for sec, sess_list in sec_to_sessions.items():
        for (oid1,s1,d1), (oid2,s2,d2) in itertools.combinations(sess_list, 2):
            model.Add(Start[(oid1,s1)] != Start[(oid2,s2)])
            if d1==2 and d2==2:
                model.Add(next_Start[(oid1,s1)] != Start[(oid2,s2)])
                model.Add(Start[(oid1,s1)] != next_Start[(oid2,s2)])
                model.Add(next_Start[(oid1,s1)] != next_Start[(oid2,s2)])
            elif d1==2:
                model.Add(next_Start[(oid1,s1)] != Start[(oid2,s2)])
            elif d2==2:
                model.Add(Start[(oid1,s1)] != next_Start[(oid2,s2)])
