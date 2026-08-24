"""Round 3C — independent hard-constraint validator for a generated timetable.

Re-derives violations directly from generated_timetable.csv + the raw input
CSVs, without importing any CP-SAT bookkeeping from hard.py/full_model.py —
an honest second opinion on the solver's own output, not a re-run of the
same code path.

Covers (see CONSTRAINTS.md for the canonical HC list — HC05/08/09/11/15 do
not exist as separate hard constraints in this codebase):
  HC01  faculty no double-booking + daily/weekly cap
  HC02  room no double-booking
  HC03  section no double-booking (skips legitimate elective-alternative pairs;
        also treats section_conflicts.csv pairs — e.g. a parent cohort and its
        lab sub-batches — as one shared cohort, same as hard.py's solver-side
        add_section_collision)
  HC04  student-level OAE/PCE no-overlap (cross-section elective vs core/elective)
  HC06  faculty availability
  HC07  room availability
  HC10  room type + capacity match (equipment mismatch reported as WARNING,
        matching the solver's own known fallback for courses with no
        fully-compatible room)
  HC12  no repeat single-slot session of same course/section on the same day
  HC13  synchronized electives share the same slot across sections
  HC14  fixed-event blocked slots
  HC16  faculty weekly cap (see HC01)

Not independently re-derived here: nothing else — every implemented HC listed
in CONSTRAINTS.md is covered above.

Optional datasets (students.csv, student_enrollments.csv, elective_groups.csv,
elective_group_courses.csv, fixed_events.csv, faculty_availability.csv,
room_availability.csv, section_conflicts.csv, parallel_offerings.csv) default
to empty when absent — the corresponding checks then no-op cleanly, the same
graceful-missing-file behavior preprocessing.py's load_all already has.
"""
import csv
import pathlib
from collections import defaultdict
from datetime import datetime

from .preprocessing import (
    contiguous_slot_sets, synchronized_offering_groups, elective_alternative_pairs,
    blocked_assignments, valid_faculty_slots, valid_room_slots, EQUIPMENT_SYNONYMS,
    section_conflict_pairs, parallel_offering_pairs,
)


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_optional(path):
    try:
        return _read(path)
    except FileNotFoundError:
        return []


def _occupied_periods(day, period, duration):
    if duration == 1:
        return [(day, period)]
    return [(day, period), (day, period + 1)]


def validate(timetable_csv_path, dataset_root, rows=None):
    """rows: optional pre-parsed timetable rows (same shape generated_timetable.csv
    has). When given, timetable_csv_path is not read at all -- lets a caller
    validate a candidate (e.g. a proposed manual edit) without writing it to
    disk first. When omitted, behaves exactly as before (reads the path)."""
    root = pathlib.Path(dataset_root)
    courses = {c["course_id"]: c for c in _read(root / "courses.csv")}
    offerings_raw = _read(root / "course_offerings.csv")
    seen, offerings = set(), []
    for o in offerings_raw:
        k = (o["course_id"], o["section_id"])
        if k in seen:
            continue
        seen.add(k)
        offerings.append(o)
    offering_by_id = {o["offering_id"]: o for o in offerings}
    faculty = {f["faculty_id"]: f for f in _read(root / "faculty.csv")}
    rooms = {r["room_id"]: r for r in _read(root / "rooms.csv")}
    time_slots = _read(root / "time_slots.csv")
    slot_by_id = {s["slot_id"]: s for s in time_slots}
    students = _read_optional(root / "students.csv")
    student_enrollments = _read_optional(root / "student_enrollments.csv")
    elective_groups = _read_optional(root / "elective_groups.csv")
    elective_group_courses = _read_optional(root / "elective_group_courses.csv")

    sync_groups = synchronized_offering_groups(elective_groups, elective_group_courses, offerings)
    alt_pairs = elective_alternative_pairs(elective_groups, elective_group_courses, offerings, student_enrollments)
    conflict_pairs = section_conflict_pairs(_read_optional(root / "section_conflicts.csv"))
    alt_pairs = alt_pairs | parallel_offering_pairs(_read_optional(root / "parallel_offerings.csv"))
    blocked = blocked_assignments(_read_optional(root / "fixed_events.csv"), time_slots)
    vfs = valid_faculty_slots(_read_optional(root / "faculty_availability.csv"))
    vrs = valid_room_slots(_read_optional(root / "room_availability.csv"))

    if rows is None:
        rows = _read(timetable_csv_path)
    violations = []
    warnings = []

    # ---- Reconstruct each session's occupied (day,period) set + metadata ----
    sessions = []  # dicts: offering_id, section_id, course_id, faculty_id, room_id, day, period, duration
    for r in rows:
        if r.get("slot_id") in ("UNASSIGNED", "?", ""):
            warnings.append(f"Row offering={r.get('offering_id')} session={r.get('session')} has no assignment (UNASSIGNED) — solve likely didn't fully succeed.")
            continue
        slot = slot_by_id.get(r["slot_id"])
        if slot is None:
            violations.append(f"HC-domain: slot_id '{r['slot_id']}' (offering {r['offering_id']}) is not in time_slots.csv at all.")
            continue
        course = courses.get(r["course_id"])
        duration = int(course["session_duration"]) if course else 1
        day = slot["day"]
        period = int(slot["period_number"])
        sessions.append({
            "offering_id": r["offering_id"], "section_id": r["section_id"], "course_id": r["course_id"],
            "session": r["session"], "faculty_id": r["faculty_id"], "room_id": r["room_id"],
            "day": day, "period": period, "duration": duration,
            "occ": _occupied_periods(day, period, duration),
        })

    def is_alt(o1, o2):
        return (o1, o2) in alt_pairs or (o2, o1) in alt_pairs

    def is_conflicting_section_pair(sec_a, sec_b):
        return sec_a == sec_b or (sec_a, sec_b) in conflict_pairs or (sec_b, sec_a) in conflict_pairs

    # ---- HC01/HC02/HC03: pairwise collision checks ----
    # Also builds offering_occ (offering_id -> union of its sessions' occupied
    # (day,period) pairs) for HC04 below -- equivalent to per-session overlap
    # checking since any two sessions overlapping implies their offerings'
    # occupied-period unions intersect, and vice versa.
    offering_occ = defaultdict(set)
    for s in sessions:
        offering_occ[s["offering_id"]].update(s["occ"])
    for i in range(len(sessions)):
        for j in range(i + 1, len(sessions)):
            a, b = sessions[i], sessions[j]
            if a["day"] != b["day"]:
                continue
            overlap = set(a["occ"]) & set(b["occ"])
            if not overlap:
                continue
            if a["faculty_id"] == b["faculty_id"]:
                violations.append(f"HC01 faculty double-booking: {a['faculty_id']} has {a['offering_id']}#{a['session']} and {b['offering_id']}#{b['session']} both at {sorted(overlap)}.")
            if a["room_id"] == b["room_id"]:
                violations.append(f"HC02 room double-booking: {a['room_id']} has {a['offering_id']}#{a['session']} and {b['offering_id']}#{b['session']} both at {sorted(overlap)}.")
            if is_conflicting_section_pair(a["section_id"], b["section_id"]) and not is_alt(a["offering_id"], b["offering_id"]):
                violations.append(f"HC03 section double-booking: {a['section_id']} has {a['offering_id']}#{a['session']} and {b['section_id']}'s {b['offering_id']}#{b['session']} both at {sorted(overlap)}.")

    # ---- HC04: student-level OAE/PCE no-overlap (elective vs own-section
    # core, elective vs elective, per student) -- mirrors hard.py:239's
    # add_student_collision rule in pure Python. No-ops (0 violations) when
    # students.csv/student_enrollments.csv are absent, same as the solver's
    # own "if not student_enrollments or not students: return" guard.
    if student_enrollments and students:
        stu_sec = {s["student_id"]: s["section_id"] for s in students}
        oid_sec = {o["offering_id"]: o["section_id"] for o in offerings}
        oid_by_course = defaultdict(list)
        for o in offerings:
            oid_by_course[o["course_id"]].append(o["offering_id"])
        sec_offerings = defaultdict(list)
        for o in offerings:
            sec_offerings[o["section_id"]].append(o["offering_id"])
        reported = set()
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
                if oid_sec.get(eoid) == sec:
                    continue
                for coid in core_oids:
                    key = (stu, tuple(sorted((eoid, coid))))
                    if key in reported:
                        continue
                    if offering_occ.get(eoid, set()) & offering_occ.get(coid, set()):
                        reported.add(key)
                        violations.append(f"HC04 student elective/core collision: student {stu} has elective {eoid} overlapping own-section core offering {coid}.")
            for a_i in range(len(elect_oids)):
                for b_i in range(a_i + 1, len(elect_oids)):
                    eoid_a, eoid_b = elect_oids[a_i], elect_oids[b_i]
                    key = (stu, tuple(sorted((eoid_a, eoid_b))))
                    if key in reported:
                        continue
                    if offering_occ.get(eoid_a, set()) & offering_occ.get(eoid_b, set()):
                        reported.add(key)
                        violations.append(f"HC04 student elective/elective collision: student {stu} has electives {eoid_a} and {eoid_b} overlapping.")

    # ---- HC01/HC16: faculty daily + weekly hour caps ----
    fac_daily = defaultdict(lambda: defaultdict(int))
    fac_weekly = defaultdict(int)
    for s in sessions:
        fac_daily[s["faculty_id"]][s["day"]] += s["duration"]
        fac_weekly[s["faculty_id"]] += s["duration"]
    for fid, days in fac_daily.items():
        frow = faculty.get(fid)
        if not frow:
            continue
        max_daily = int(frow["max_hours_per_day"])
        for day, hrs in days.items():
            if hrs > max_daily:
                violations.append(f"HC01 daily cap: faculty {fid} has {hrs}h on {day} (max {max_daily}).")
    for fid, hrs in fac_weekly.items():
        frow = faculty.get(fid)
        if not frow:
            continue
        max_weekly = int(frow["max_hours_per_week"])
        if hrs > max_weekly:
            violations.append(f"HC16 weekly cap: faculty {fid} has {hrs}h this week (max {max_weekly}).")

    # ---- HC06/HC07: availability ----
    for s in sessions:
        for (day, period) in s["occ"]:
            slot_id = next((sid for sid, sl in slot_by_id.items() if sl["day"] == day and int(sl["period_number"]) == period), None)
            if slot_id is None:
                continue
            fa = vfs.get(s["faculty_id"], set())
            if fa and slot_id not in fa:
                violations.append(f"HC06 faculty availability: {s['faculty_id']} assigned {s['offering_id']}#{s['session']} at {slot_id} but not marked available there.")
            ra = vrs.get(s["room_id"], set())
            if ra and slot_id not in ra:
                violations.append(f"HC07 room availability: {s['room_id']} assigned {s['offering_id']}#{s['session']} at {slot_id} but not marked available there.")

    # ---- HC10: room type / capacity / equipment ----
    # Capacity was never re-derived here before: the solver's own domain
    # construction (model.py's build_variables, via
    # preprocessing.compatible_rooms_for_course) never lets an undersized
    # room reach solver output, so validate() -- built to audit solver
    # output -- had no capacity check. A manual edit bypasses that domain
    # entirely (an admin can pick any room_id), so it's added here too.
    for s in sessions:
        course = courses.get(s["course_id"])
        room = rooms.get(s["room_id"])
        if not course or not room:
            continue
        if room["room_type"] != course["required_room_type"]:
            violations.append(f"HC10 room type: {s['offering_id']}#{s['session']} needs {course['required_room_type']} but got {s['room_id']} ({room['room_type']}).")
            continue
        offering = offering_by_id.get(s["offering_id"])
        min_cap = int(course["min_room_capacity"] or 0)
        student_count = int(offering["student_count"]) if offering and offering.get("student_count") else 0
        effective_cap = max(min_cap, student_count)
        room_cap = int(room["capacity"])
        if room_cap < effective_cap:
            # A genuinely AVOIDABLE undersizing (some room of the right type
            # could have held everyone, but this one wasn't it) is a real
            # violation. If NO room of the required type anywhere in the
            # dataset is big enough, this is the same known, documented
            # fallback preprocessing.py's compatible_rooms_for_course already
            # accepts ("if no room fits max_student, fallback to minCapacity
            # only") -- report it as a warning, matching HC10's own
            # equipment-mismatch precedent just below, not a hard violation
            # for something the dataset made unavoidable.
            any_big_enough = any(r["room_type"] == course["required_room_type"] and int(r["capacity"]) >= effective_cap for r in rooms.values())
            msg = f"HC10 room capacity: {s['offering_id']}#{s['session']} needs capacity {effective_cap} (course min {min_cap}, {student_count} students) but {s['room_id']} only has {room_cap}."
            if any_big_enough:
                violations.append(msg)
            else:
                warnings.append(f"HC10 room capacity (known-fallback case, not a hard violation -- no {course['required_room_type']} room in this dataset has capacity >= {effective_cap}): {msg}")
        equip_req = [EQUIPMENT_SYNONYMS.get(t.strip(), t.strip()) for t in course["equipment_required"].split(",") if t.strip()]
        if equip_req:
            room_equip = set(t.strip() for t in room["equipment"].split(",") if t.strip())
            missing = [t for t in equip_req if t not in room_equip]
            if missing:
                warnings.append(f"HC10 equipment (known-fallback case, not a hard violation): {s['offering_id']}#{s['session']} in {s['room_id']} missing {missing}.")

    # ---- HC12: no repeat single-slot session of same course/section/day ----
    per_sc_day = defaultdict(lambda: defaultdict(int))
    courses_multi = {cid: c for cid, c in courses.items() if int(c["sessions_per_week"]) > 1 and int(c["session_duration"]) == 1}
    for s in sessions:
        if s["course_id"] in courses_multi and s["duration"] == 1:
            per_sc_day[(s["section_id"], s["course_id"])][s["day"]] += 1
    for (sec, cid), by_day in per_sc_day.items():
        for day, cnt in by_day.items():
            if cnt > 1:
                violations.append(f"HC12 repeat same course same day: section {sec} course {cid} has {cnt} sessions on {day}.")

    # ---- HC13: synchronized electives share the same slot ----
    by_offering_session = defaultdict(dict)
    for s in sessions:
        by_offering_session[s["offering_id"]][s["session"]] = (s["day"], s["period"])
    for group in sync_groups:
        oids = sorted(group["offerings"])
        for session_key in set().union(*(by_offering_session.get(o, {}).keys() for o in oids)) if oids else set():
            slots = {o: by_offering_session[o].get(session_key) for o in oids if session_key in by_offering_session.get(o, {})}
            distinct = set(slots.values())
            if len(distinct) > 1:
                violations.append(f"HC13 synchronized electives: group {group['group_id']}/{group['course_id']} session {session_key} not all at the same slot: {slots}.")

    # ---- HC14: fixed-event blocked slots ----
    blocked_day_period = set()
    for fe_id, info in blocked.items():
        for sid in info["slots"]:
            sl = slot_by_id.get(sid)
            if sl:
                blocked_day_period.add((sl["day"], int(sl["period_number"])))
    for s in sessions:
        for occ in s["occ"]:
            if occ in blocked_day_period:
                violations.append(f"HC14 fixed event: {s['offering_id']}#{s['session']} placed at blocked slot {occ}.")

    return {"violations": violations, "warnings": warnings, "sessions_checked": len(sessions)}


def format_report(result, label):
    lines = [f"=== HARD constraint validation: {label} ===",
             f"  Sessions checked: {result['sessions_checked']}",
             f"  Violations: {len(result['violations'])}",
             f"  Warnings: {len(result['warnings'])}"]
    for v in result["violations"][:30]:
        lines.append(f"    VIOLATION: {v}")
    if len(result["violations"]) > 30:
        lines.append(f"    ... and {len(result['violations']) - 30} more")
    for w in result["warnings"][:10]:
        lines.append(f"    warning: {w}")
    if len(result["warnings"]) > 10:
        lines.append(f"    ... and {len(result['warnings']) - 10} more")
    return "\n".join(lines)
