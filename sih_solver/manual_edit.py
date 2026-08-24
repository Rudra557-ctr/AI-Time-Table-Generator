"""Admin manual timetable editing (PLAN.md "Admin Manual Timetable Editing").

Validated moves/room-changes/faculty-reassignment on an already-generated
timetable, layered on top of the existing pipeline without touching the
solver, its hard constraints, or the dataset schema:

  Dataset -> CP-SAT generate -> Admin edit -> Re-validate -> Final timetable

Pure functions over already-loaded CSV rows -- no FastAPI, no CP-SAT --
same shape as preprocessing.py/gap_stats.py, so they're independently
testable and reusable from any caller (backend/app.py's /api/edit/* routes
today).

Correctness contract: every accept/reject decision for a single proposed
edit or for the "Validate Final Timetable" action routes through
validate_output.validate() -- the SAME independent hard-constraint validator
the rest of the project already trusts -- never a second, separately
maintained rule set. The only genuinely new logic here is (a) building a
candidate row set from a proposed edit, (b) turning validate()'s violation
strings into a labeled checklist, (c) a soft-quality delta over the terms
cheaply computable without the solver, and (d) a two-tier alternative-slot
search: a fast structural screen (`_screen_candidate`, O(existing sessions)
per candidate, not the O(n^2) whole-file validate()) narrows a large search
space, then the top-scoring finalists each get one full validate() as the
final, authoritative confirmation before being returned.
"""
import csv
import pathlib
from collections import defaultdict

from .validate_output import validate
from .preprocessing import (
    all_contiguous_starts, occupied_chain_map, compatible_rooms_for_course,
    valid_faculty_slots, valid_room_slots, blocked_assignments,
    section_conflict_pairs, parallel_offering_pairs,
    synchronized_offering_groups, elective_alternative_pairs,
)
from .gap_stats import _period_map, _segments
from .soft import DEFAULT_WEIGHTS


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_optional(path):
    try:
        return _read(path)
    except FileNotFoundError:
        return []


def load_edit_context(root):
    """Everything check_edit/apply_edit_to_rows/find_* need, loaded once per
    request (small dataset, cheap -- same read pattern
    validate_output.validate() already re-does per call). Callers that make
    several calls in one request (check -> soft delta -> alternatives) should
    load this once and pass it through via the `ctx` parameter."""
    root = pathlib.Path(root)
    courses = {c["course_id"]: c for c in _read(root / "courses.csv")}
    offerings_raw = _read(root / "course_offerings.csv")
    offering_by_id = {o["offering_id"]: o for o in offerings_raw}
    rooms = {r["room_id"]: r for r in _read(root / "rooms.csv")}
    time_slots = _read(root / "time_slots.csv")
    faculty = {f["faculty_id"]: f for f in _read(root / "faculty.csv")}
    fixed_events = _read_optional(root / "fixed_events.csv")
    elective_groups = _read_optional(root / "elective_groups.csv")
    elective_group_courses = _read_optional(root / "elective_group_courses.csv")
    student_enrollments = _read_optional(root / "student_enrollments.csv")
    seen, offerings_deduped = set(), []
    for o in offerings_raw:
        k = (o["course_id"], o["section_id"])
        if k in seen:
            continue
        seen.add(k)
        offerings_deduped.append(o)
    sync_groups = synchronized_offering_groups(elective_groups, elective_group_courses, offerings_deduped)
    alt_pairs = elective_alternative_pairs(elective_groups, elective_group_courses, offerings_deduped, student_enrollments)
    alt_pairs = alt_pairs | parallel_offering_pairs(_read_optional(root / "parallel_offerings.csv"))
    conflict_pairs = section_conflict_pairs(_read_optional(root / "section_conflicts.csv"))
    return {
        "root": root, "courses": courses, "offering_by_id": offering_by_id,
        "rooms": rooms, "time_slots": time_slots, "faculty": faculty,
        "blocked": blocked_assignments(fixed_events, time_slots),
        "vfs": valid_faculty_slots(_read_optional(root / "faculty_availability.csv")),
        "vrs": valid_room_slots(_read_optional(root / "room_availability.csv")),
        "alt_pairs": alt_pairs, "conflict_pairs": conflict_pairs,
    }


def _is_lunch_event(raw_event):
    return "lunch" in (raw_event.get("event_name") or "").lower()


def _is_alt(ctx, o1, o2):
    return (o1, o2) in ctx["alt_pairs"] or (o2, o1) in ctx["alt_pairs"]


def _is_conflicting_section_pair(ctx, sec_a, sec_b):
    if sec_a == sec_b:
        return True
    return (sec_a, sec_b) in ctx["conflict_pairs"] or (sec_b, sec_a) in ctx["conflict_pairs"]


def _find_row(rows, offering_id, session):
    return next((r for r in rows if r["offering_id"] == offering_id and str(r["session"]) == str(session)), None)


def apply_edit_to_rows(rows, edit, ctx):
    """Pure: returns a NEW row list with exactly one row's slot_id/room_id/
    faculty_id mutated (whichever `edit` specifies), day/start_time/end_time
    recomputed from time_slots.csv. Never adds/removes rows -- preserves
    session-count completeness by construction. Raises ValueError with a
    human-readable message on a structurally invalid edit (unknown ids, no
    matching session, or a slot that isn't even a legal start for the
    course's session_duration -- e.g. it would span the lunch gap)."""
    offering_id = edit["offering_id"]
    session = str(edit["session"])
    offering = ctx["offering_by_id"].get(offering_id)
    if offering is None:
        raise ValueError(f"Unknown offering_id '{offering_id}'.")
    course = ctx["courses"].get(offering["course_id"])
    duration = int(course["session_duration"]) if course else 1
    slot_by_id = {s["slot_id"]: s for s in ctx["time_slots"]}

    new_slot = None
    if edit.get("new_slot_id"):
        new_slot = slot_by_id.get(edit["new_slot_id"])
        if new_slot is None:
            raise ValueError(f"Unknown slot_id '{edit['new_slot_id']}'.")
        if duration > 1 and edit["new_slot_id"] not in all_contiguous_starts(ctx["time_slots"], duration):
            raise ValueError(
                f"Slot '{edit['new_slot_id']}' cannot start a {duration}-hour session "
                f"(no clock-contiguous run of {duration} slots begins there -- "
                f"it would cross a break or the end of the day)."
            )
    new_room_id = edit.get("new_room_id") or None
    if new_room_id and new_room_id not in ctx["rooms"]:
        raise ValueError(f"Unknown room_id '{new_room_id}'.")
    new_faculty_id = edit.get("new_faculty_id") or None
    if new_faculty_id and new_faculty_id not in ctx["faculty"]:
        raise ValueError(f"Unknown faculty_id '{new_faculty_id}'.")

    new_rows = []
    matched = False
    for r in rows:
        if r["offering_id"] == offering_id and str(r["session"]) == session:
            matched = True
            nr = dict(r)
            if new_slot is not None:
                nr["slot_id"] = new_slot["slot_id"]
                nr["day"] = new_slot["day"]
                nr["start_time"] = new_slot["start_time"]
                nr["end_time"] = new_slot["end_time"]
            if new_room_id:
                nr["room_id"] = new_room_id
            if new_faculty_id:
                nr["faculty_id"] = new_faculty_id
            new_rows.append(nr)
        else:
            new_rows.append(dict(r))
    if not matched:
        raise ValueError(f"No session found for offering_id={offering_id} session={session}.")
    assert len(new_rows) == len(rows), "apply_edit_to_rows must never add/remove rows"
    return new_rows


# Ordered, human-readable checklist -- each entry's `ok` is derived by
# pattern-matching validate()'s own violation-string prefixes (never a
# second rule engine). "__lunch__" is handled specially since it's called
# out as its own line item in the admin-facing checklist rather than folded
# into the generic fixed-event check.
CHECK_DEFINITIONS = [
    ("Section available", ("HC03",)),
    ("No faculty conflict", ("HC01 faculty double-booking",)),
    ("No room conflict", ("HC02",)),
    ("Faculty available", ("HC06",)),
    ("Room available", ("HC07",)),
    ("Room type compatible", ("HC10 room type",)),
    ("Room capacity valid", ("HC10 room capacity",)),
    ("Faculty workload within limits", ("HC01 daily cap", "HC16")),
    ("Lunch break respected", ("__lunch__",)),
    ("No fixed-event conflict", ("HC14",)),
    ("Elective / student constraints respected", ("HC04", "HC13")),
    ("No duplicate same-day session", ("HC12",)),
]


def _lunch_ok(ctx, candidate_rows, offering_id, session):
    row = _find_row(candidate_rows, offering_id, session)
    if row is None or row.get("slot_id") in ("UNASSIGNED", "", None):
        return True
    lunch_slot_ids = set()
    for info in ctx["blocked"].values():
        if _is_lunch_event(info["raw"]):
            lunch_slot_ids |= info["slots"]
    if not lunch_slot_ids:
        return True
    offering = ctx["offering_by_id"].get(offering_id)
    course = ctx["courses"].get(offering["course_id"]) if offering else None
    duration = int(course["session_duration"]) if course else 1
    chain = occupied_chain_map(ctx["time_slots"], duration).get(row["slot_id"], (row["slot_id"],))
    return not (set(chain) & lunch_slot_ids)


def check_edit(root, rows, edit, ctx=None):
    """Applies `edit` to `rows` and validates the result. Judges validity by
    NEW violations the edit introduces, not the whole file's absolute state
    -- on a large real timetable that already has unrelated pre-existing
    violations elsewhere (e.g. from a prior solve/optimize pass), an admin
    moving one unrelated class should see that their edit is fine, not be
    blocked by corruption they didn't cause and can't see. ("Validate Final
    Timetable" / validate_all_edits below is the separate, whole-file-honest
    check for req. #12 -- this function answers "did my edit break
    something," not "is everything currently clean.")

    Returns {"valid": bool, "checks": [{"label","ok"}], "new_violations":
    [...], "preexisting_violations": [...], "warnings": [...],
    "candidate_rows": [...]}. Raises ValueError only for a structurally
    malformed edit (unknown ids) -- everything else becomes a checklist item
    instead of an exception, since a rejected-but-well-formed edit is the
    normal, expected outcome here, not an error."""
    ctx = ctx or load_edit_context(root)
    candidate_rows = apply_edit_to_rows(rows, edit, ctx)
    before = validate(None, ctx["root"], rows=rows)
    after = validate(None, ctx["root"], rows=candidate_rows)
    before_set = set(before["violations"])
    new_violations = [v for v in after["violations"] if v not in before_set]
    preexisting_violations = [v for v in after["violations"] if v in before_set]
    checks = []
    for label, prefixes in CHECK_DEFINITIONS:
        if prefixes == ("__lunch__",):
            ok = _lunch_ok(ctx, candidate_rows, edit["offering_id"], edit["session"])
        else:
            ok = not any(any(v.startswith(p) for p in prefixes) for v in new_violations)
        checks.append({"label": label, "ok": ok})
    return {
        "valid": len(new_violations) == 0,
        "checks": checks,
        "new_violations": new_violations,
        "preexisting_violations": preexisting_violations,
        "warnings": after["warnings"],
        "candidate_rows": candidate_rows,
    }


def _section_faculty_day(rows, offering_id, session):
    row = _find_row(rows, offering_id, session)
    if row is None:
        return None
    return row["section_id"], row["faculty_id"], row["day"]


def compute_soft_delta(root, before_rows, after_rows, edit, weights=None, ctx=None):
    """Itemized soft-quality delta for a single edit, scoped to just the
    touched (section,day)/(faculty,day) pairs -- reuses gap_stats.py's pure
    `_segments` computation (the same building block solve_pipeline.py's
    `_rank_sections_by_gap_score` already uses incrementally for its LNS
    gap-repair loop), not a full solver re-run. Only the soft terms cheaply
    computable this way are reported (SC02 gaps, SC_isolated, SC_facgaps,
    SC03 room wastage) -- SC01/05/06/08/09 aren't, and are honestly omitted
    rather than guessed. Returns itemized before/after/delta per term plus
    one weighted-sum `weighted_delta` over just these terms, using the job's
    own weights (falling back to soft.DEFAULT_WEIGHTS) -- explicitly a
    partial figure, never a fabricated 0-100 "quality score"."""
    ctx = ctx or load_edit_context(root)
    weights = weights or DEFAULT_WEIGHTS
    slot_to_period, day_periods = _period_map(ctx["time_slots"])

    before_loc = _section_faculty_day(before_rows, edit["offering_id"], edit["session"])
    after_loc = _section_faculty_day(after_rows, edit["offering_id"], edit["session"])

    def seg_for(rows, key_field, entity, day):
        periods = set()
        for r in rows:
            if r.get(key_field) == entity and r.get("day") == day:
                p = slot_to_period.get(r.get("slot_id"))
                if p is not None:
                    periods.add(p)
        return _segments(periods, day_periods.get(day, []))

    touched = set()
    for loc in (before_loc, after_loc):
        if loc:
            touched.add(("section_id", loc[0], loc[2]))
            touched.add(("faculty_id", loc[1], loc[2]))

    sec_gaps_b = sec_gaps_a = sec_iso_b = sec_iso_a = 0
    fac_gaps_b = fac_gaps_a = fac_iso_b = fac_iso_a = 0
    for key_field, entity, day in touched:
        b = seg_for(before_rows, key_field, entity, day)
        a = seg_for(after_rows, key_field, entity, day)
        bg, ag = (b["gaps"] if b else 0), (a["gaps"] if a else 0)
        bi, ai = (b["isolated_runs"] if b else 0), (a["isolated_runs"] if a else 0)
        if key_field == "section_id":
            sec_gaps_b += bg; sec_gaps_a += ag
            sec_iso_b += bi; sec_iso_a += ai
        else:
            fac_gaps_b += bg; fac_gaps_a += ag
            fac_iso_b += bi; fac_iso_a += ai

    def wastage(rows):
        row = _find_row(rows, edit["offering_id"], edit["session"])
        if row is None:
            return 0
        room = ctx["rooms"].get(row["room_id"])
        offering = ctx["offering_by_id"].get(edit["offering_id"])
        if not room or not offering:
            return 0
        return max(0, int(room["capacity"]) - int(offering.get("student_count") or 0))
    w_b, w_a = wastage(before_rows), wastage(after_rows)

    items = {
        "section_gaps": {"before": sec_gaps_b, "after": sec_gaps_a, "delta": sec_gaps_a - sec_gaps_b},
        "section_isolated": {"before": sec_iso_b, "after": sec_iso_a, "delta": sec_iso_a - sec_iso_b},
        "faculty_gaps": {"before": fac_gaps_b, "after": fac_gaps_a, "delta": fac_gaps_a - fac_gaps_b},
        "faculty_isolated": {"before": fac_iso_b, "after": fac_iso_a, "delta": fac_iso_a - fac_iso_b},
        "room_wastage": {"before": w_b, "after": w_a, "delta": w_a - w_b},
    }
    weighted_delta = (
        weights.get("SC02_gaps", 0) * items["section_gaps"]["delta"]
        + weights.get("SC_isolated", 0) * items["section_isolated"]["delta"]
        + weights.get("SC_facgaps", 0) * items["faculty_gaps"]["delta"]
        + weights.get("SC03_wastage", 0) * items["room_wastage"]["delta"]
    )
    return {"items": items, "weighted_delta": weighted_delta}


def _screen_candidate(rows, ctx, offering_id, session, new_slot_id=None, new_room_id=None, new_faculty_id=None):
    """Fast, scoped hard-constraint pre-screen for ONE candidate -- O(existing
    sessions), not the O(n^2) whole-file validate(). Used to narrow a large
    search space (find_alternative_slots/find_room_alternatives) before a
    handful of finalists get one full check_edit() confirmation. A screen
    "ok" is never trusted as the final answer -- only as a filter to decide
    which candidates are worth the full check. Conservative in one direction
    only: it does not apply the alt_pairs/HC13 exemptions full validate()
    does, so it can occasionally screen out a candidate that's actually
    fine (fewer alternatives surfaced) but never lets an invalid one through
    (the full check_edit() on finalists is the actual safety backstop)."""
    offering = ctx["offering_by_id"].get(offering_id)
    if offering is None:
        return False, "Unknown offering."
    course = ctx["courses"].get(offering["course_id"])
    duration = int(course["session_duration"]) if course else 1
    current = _find_row(rows, offering_id, session)
    if current is None:
        return False, "Session not found."
    slot_id = new_slot_id or current["slot_id"]
    room_id = new_room_id or current["room_id"]
    faculty_id = new_faculty_id or current["faculty_id"]

    if duration > 1 and slot_id not in all_contiguous_starts(ctx["time_slots"], duration):
        return False, f"Not a valid start for a {duration}-hour session."

    chain_set = set(occupied_chain_map(ctx["time_slots"], duration).get(slot_id, (slot_id,)))

    fa = ctx["vfs"].get(faculty_id, set())
    if fa and not chain_set <= fa:
        return False, "Faculty not available at this time."
    ra = ctx["vrs"].get(room_id, set())
    if ra and not chain_set <= ra:
        return False, "Room not available at this time."

    room = ctx["rooms"].get(room_id)
    if room is None:
        return False, "Unknown room."
    if course and room["room_type"] != course["required_room_type"]:
        return False, f"Room type {room['room_type']} incompatible (needs {course['required_room_type']})."
    min_cap = int(course["min_room_capacity"] or 0) if course else 0
    effective_cap = max(min_cap, int(offering.get("student_count") or 0))
    if int(room["capacity"]) < effective_cap:
        return False, f"Room capacity {room['capacity']} < required {effective_cap}."

    for info in ctx["blocked"].values():
        if info["slots"] & chain_set:
            label = "lunch break" if _is_lunch_event(info["raw"]) else "a fixed event"
            return False, f"Conflicts with {label}."

    slot_by_id = {s["slot_id"]: s for s in ctx["time_slots"]}
    day = slot_by_id.get(slot_id, {}).get("day")

    # HC12: a multi-session-per-week, single-slot course can't have two of
    # its own sessions land on the same day (mirrors full_model.py's
    # add_no_repeat_same_course_same_day gating exactly).
    if course and duration == 1 and int(course.get("sessions_per_week", 1) or 1) > 1:
        for r in rows:
            if r["offering_id"] != offering_id or str(r["session"]) == str(session):
                continue
            if r.get("day") == day:
                return False, f"Same course already scheduled on {day} ({r['offering_id']}#{r['session']})."

    for r in rows:
        if r["offering_id"] == offering_id and str(r["session"]) == str(session):
            continue
        if r.get("day") != day or r.get("slot_id") in ("UNASSIGNED", "", None):
            continue
        r_offering = ctx["offering_by_id"].get(r["offering_id"])
        r_course = ctx["courses"].get(r_offering["course_id"]) if r_offering else None
        r_duration = int(r_course["session_duration"]) if r_course else 1
        r_chain = set(occupied_chain_map(ctx["time_slots"], r_duration).get(r["slot_id"], (r["slot_id"],)))
        if not (r_chain & chain_set):
            continue
        if _is_alt(ctx, offering_id, r["offering_id"]):
            continue
        if r["faculty_id"] == faculty_id:
            return False, f"Faculty double-booked with {r['offering_id']}#{r['session']}."
        if r["room_id"] == room_id:
            return False, f"Room double-booked with {r['offering_id']}#{r['session']}."
        if _is_conflicting_section_pair(ctx, r["section_id"], offering["section_id"]):
            return False, f"Section double-booked with {r['offering_id']}#{r['session']}."
    return True, None


def find_alternative_slots(root, rows, offering_id, session, weights=None, max_results=5, screen_limit=40):
    """Two-tier search for req. #7: screen every (slot, compatible room)
    combination with the fast `_screen_candidate` (cheap, O(sessions) each),
    rank the screened-valid ones by soft-quality impact using the SAME
    weighted-sum `compute_soft_delta` uses (no invented percentages), then
    confirm only the top `max_results` with one full check_edit() each
    before returning -- catches any whole-file-only interaction (HC13/HC04)
    the scoped screen can't see, on just a handful of candidates instead of
    every one screened."""
    ctx = load_edit_context(root)
    weights = weights or DEFAULT_WEIGHTS
    current = _find_row(rows, offering_id, session)
    if current is None:
        raise ValueError(f"No session found for offering_id={offering_id} session={session}.")
    offering = ctx["offering_by_id"][offering_id]
    course = ctx["courses"].get(offering["course_id"])
    duration = int(course["session_duration"]) if course else 1
    starts = all_contiguous_starts(ctx["time_slots"], duration) if duration > 1 else {s["slot_id"] for s in ctx["time_slots"]}

    student_count = int(offering.get("student_count") or 0)
    min_cap = int(course["min_room_capacity"] or 0) if course else 0
    effective_cap = max(min_cap, student_count)
    all_rooms = list(ctx["rooms"].values())
    compatible_rooms = compatible_rooms_for_course(course, all_rooms, [offering]) if course else all_rooms
    strict_rooms = [r for r in compatible_rooms if int(r["capacity"]) >= effective_cap]
    compatible_rooms = strict_rooms or compatible_rooms  # never silently accept an undersized room

    screened = []
    for slot_id in sorted(starts):
        if slot_id == current["slot_id"]:
            continue
        for room in compatible_rooms:
            ok, _reason = _screen_candidate(rows, ctx, offering_id, session, new_slot_id=slot_id, new_room_id=room["room_id"])
            if ok:
                screened.append({"slot_id": slot_id, "room_id": room["room_id"]})
        if len(screened) >= screen_limit:
            break

    scored = []
    for cand in screened:
        edit = {"offering_id": offering_id, "session": session, "new_slot_id": cand["slot_id"], "new_room_id": cand["room_id"]}
        after_rows = apply_edit_to_rows(rows, edit, ctx)
        delta = compute_soft_delta(root, rows, after_rows, edit, weights=weights, ctx=ctx)
        scored.append({**cand, "weighted_delta": delta["weighted_delta"], "soft_delta": delta["items"]})
    scored.sort(key=lambda c: c["weighted_delta"])

    slot_by_id = {s["slot_id"]: s for s in ctx["time_slots"]}
    results = []
    for cand in scored[: max_results * 2]:  # a few extra in case some finalists fail full check
        if len(results) >= max_results:
            break
        edit = {"offering_id": offering_id, "session": session, "new_slot_id": cand["slot_id"], "new_room_id": cand["room_id"]}
        check = check_edit(root, rows, edit, ctx=ctx)
        if not check["valid"]:
            continue
        slot = slot_by_id[cand["slot_id"]]
        results.append({
            "slot_id": cand["slot_id"], "day": slot["day"], "start_time": slot["start_time"],
            "room_id": cand["room_id"], "valid": True,
            "soft_delta": cand["soft_delta"], "weighted_delta": cand["weighted_delta"],
        })
    return results


def find_room_alternatives(root, rows, offering_id, session):
    """For req. #8: every room of the compatible type, flagged valid/invalid
    with the specific reason via `_screen_candidate`'s same building
    blocks -- day/slot/faculty held fixed, only the room changes."""
    ctx = load_edit_context(root)
    current = _find_row(rows, offering_id, session)
    if current is None:
        raise ValueError(f"No session found for offering_id={offering_id} session={session}.")
    offering = ctx["offering_by_id"][offering_id]
    course = ctx["courses"].get(offering["course_id"])
    req_type = course["required_room_type"] if course else None

    results = []
    for room in ctx["rooms"].values():
        if room["room_id"] == current["room_id"]:
            continue
        if req_type and room["room_type"] != req_type:
            results.append({
                "room_id": room["room_id"], "capacity": int(room["capacity"]), "valid": False,
                "reason": f"Wrong room type ({room['room_type']}, needs {req_type}).",
            })
            continue
        ok, reason = _screen_candidate(rows, ctx, offering_id, session, new_room_id=room["room_id"])
        results.append({"room_id": room["room_id"], "capacity": int(room["capacity"]), "valid": ok, "reason": reason})
    results.sort(key=lambda r: (not r["valid"], r["room_id"]))
    return results
