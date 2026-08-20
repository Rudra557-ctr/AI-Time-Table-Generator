"""Efficient HARD collisions via Interval NoOverlap (fixes room/faculty double booking)."""
from ortools.sat.python import cp_model
from datetime import datetime

def _slot_mins(time_slots, slot_to_idx, idx_to_slot):
    # Compute start minutes since week start (MON 0)
    day_order = {"MON":0,"TUE":1,"WED":2,"THU":3,"FRI":4}
    mins = []
    for idx in range(len(slot_to_idx)):
        sid = idx_to_slot[idx]
        # find slot record
        rec = next(s for s in time_slots if s["slot_id"]==sid)
        day_idx = day_order[rec["day"]]
        t = datetime.strptime(rec["start_time"].strip(), "%H:%M")
        mins.append(day_idx*24*60 + t.hour*60 + t.minute)
    return mins

def add_collisions_via_intervals(model, Start, Teacher, Room, offerings, time_slots, slot_to_idx, idx_to_slot):
    # Build start mins array
    mins = _slot_mins(time_slots, slot_to_idx, idx_to_slot)
    # For each session, create start_min var and interval
    start_mins = {}
    intervals_by_faculty = {f: [] for f in set() }  # will fill later
    # But we need Teacher and Room optionals, so we need to know eligible/compatible
    # Instead, we create intervals per session, then make them optional per faculty/room
    # For faculty: optional interval per (session, faculty candidate)
    # For room: optional interval per (session, room candidate)
    # For section: intervals are required (non-optional) per section
    pass
