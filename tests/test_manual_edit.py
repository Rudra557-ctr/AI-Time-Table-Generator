"""Tests for admin manual timetable editing (sih_solver/manual_edit.py).

Uses the synthetic dataset (fast to solve), same fixture pattern as
test_incremental_resolve.py: solve once for a baseline generated_timetable
(as an in-memory row list, matching what backend/app.py reads from
generated_timetable.csv), then exercise manual_edit.py's functions directly
against it -- a valid move, each hard-constraint violation type forced
individually, alternative-slot/room search, undo, and a full re-validation
after several sequential edits.

Every accept/reject decision manual_edit.py makes routes through
validate_output.validate() -- these tests are really checking that pipe
end-to-end, not re-implementing the rules a second time.
"""
import csv
import pathlib
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sih_solver.full_model import build_full_hard_model
from sih_solver import manual_edit as me
from sih_solver.validate_output import validate
from ortools.sat.python import cp_model

SYNTHETIC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "synthetic_data"


def _require_synthetic():
    if not SYNTHETIC_ROOT.exists():
        pytest.skip("run scripts/generate_synthetic_dataset.py first")


def _solve_baseline(root):
    model, Start, Teacher, Room, meta = build_full_hard_model(root)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), f"baseline solve failed: {status}"
    slots = {s["slot_id"]: s for s in meta["data"]["time_slots.csv"]}
    rows = []
    for o in meta["offerings"]:
        oid = o["offering_id"]
        fac = meta["idx_to_fac"][solver.Value(Teacher[oid])]
        for s in range(int(o["required_sessions"])):
            slot_id = meta["idx_to_slot"][solver.Value(Start[(oid, s)])]
            room_id = meta["idx_to_room"][solver.Value(Room[(oid, s)])]
            sl = slots[slot_id]
            rows.append({
                "offering_id": oid, "course_id": o["course_id"], "section_id": o["section_id"],
                "session": str(s + 1), "slot_id": slot_id, "day": sl["day"],
                "start_time": sl["start_time"], "end_time": sl["end_time"],
                "room_id": room_id, "faculty_id": fac,
            })
    return rows


@pytest.fixture(scope="module")
def baseline():
    _require_synthetic()
    rows = _solve_baseline(SYNTHETIC_ROOT)
    vres = validate(None, SYNTHETIC_ROOT, rows=rows)
    assert vres["violations"] == [], f"baseline itself isn't clean: {vres['violations']}"
    return rows


@pytest.fixture()
def ctx():
    return me.load_edit_context(SYNTHETIC_ROOT)


def test_apply_edit_to_rows_never_changes_row_count(baseline, ctx):
    row = baseline[0]
    edit = {"offering_id": row["offering_id"], "session": row["session"], "new_slot_id": row["slot_id"]}
    out = me.apply_edit_to_rows(baseline, edit, ctx)
    assert len(out) == len(baseline)


def test_unknown_offering_raises_valueerror(baseline, ctx):
    with pytest.raises(ValueError):
        me.apply_edit_to_rows(baseline, {"offering_id": "NOPE", "session": "1", "new_slot_id": "MON_0900"}, ctx)


def test_noop_edit_is_valid(baseline, ctx):
    row = baseline[10]
    edit = {"offering_id": row["offering_id"], "session": row["session"], "new_slot_id": row["slot_id"]}
    result = me.check_edit(SYNTHETIC_ROOT, baseline, edit, ctx=ctx)
    assert result["valid"], result["new_violations"]
    assert all(c["ok"] for c in result["checks"])


def test_valid_move_found_by_alternative_search_is_accepted(baseline, ctx):
    row = baseline[5]
    alts = me.find_alternative_slots(SYNTHETIC_ROOT, baseline, row["offering_id"], row["session"], max_results=1)
    assert alts, "expected at least one valid alternative in this dataset"
    a = alts[0]
    edit = {"offering_id": row["offering_id"], "session": row["session"], "new_slot_id": a["slot_id"], "new_room_id": a["room_id"]}
    result = me.check_edit(SYNTHETIC_ROOT, baseline, edit, ctx=ctx)
    assert result["valid"], result["new_violations"]


def test_forced_faculty_conflict_is_rejected(baseline, ctx):
    row = baseline[0]
    other = next(r for r in baseline if r["faculty_id"] == row["faculty_id"] and r["offering_id"] != row["offering_id"])
    edit = {"offering_id": row["offering_id"], "session": row["session"], "new_slot_id": other["slot_id"], "new_room_id": row["room_id"]}
    result = me.check_edit(SYNTHETIC_ROOT, baseline, edit, ctx=ctx)
    assert not result["valid"]
    assert any(v.startswith("HC01 faculty double-booking") for v in result["new_violations"])
    fail_labels = {c["label"] for c in result["checks"] if not c["ok"]}
    assert "No faculty conflict" in fail_labels


def test_forced_room_conflict_is_rejected(baseline, ctx):
    # Find any (room, day) pair shared by two different offerings in this
    # dataset -- not assuming baseline[0]'s own room happens to qualify.
    row = other = None
    for a in baseline:
        for b in baseline:
            if a["room_id"] == b["room_id"] and a["day"] == b["day"] and a["offering_id"] != b["offering_id"]:
                row, other = a, b
                break
        if row:
            break
    if row is None:
        pytest.skip("no two offerings share a (room, day) pair to force this case from")
    edit = {"offering_id": row["offering_id"], "session": row["session"], "new_slot_id": other["slot_id"], "new_room_id": row["room_id"], "new_faculty_id": row["faculty_id"]}
    result = me.check_edit(SYNTHETIC_ROOT, baseline, edit, ctx=ctx)
    assert not result["valid"]
    assert any(v.startswith("HC02 room double-booking") for v in result["new_violations"])


def test_forced_section_conflict_is_rejected(baseline, ctx):
    row = baseline[0]
    other = next(
        r for r in baseline
        if r["section_id"] == row["section_id"] and r["offering_id"] != row["offering_id"]
    )
    edit = {"offering_id": row["offering_id"], "session": row["session"], "new_slot_id": other["slot_id"]}
    result = me.check_edit(SYNTHETIC_ROOT, baseline, edit, ctx=ctx)
    assert not result["valid"]
    assert any(v.startswith("HC03 section double-booking") for v in result["new_violations"])


def test_invalid_room_type_is_rejected(baseline, ctx):
    row = baseline[0]
    course = ctx["courses"][ctx["offering_by_id"][row["offering_id"]]["course_id"]]
    wrong_type_room = next(r for r in ctx["rooms"].values() if r["room_type"] != course["required_room_type"])
    edit = {"offering_id": row["offering_id"], "session": row["session"], "new_room_id": wrong_type_room["room_id"]}
    result = me.check_edit(SYNTHETIC_ROOT, baseline, edit, ctx=ctx)
    assert not result["valid"]
    assert any(v.startswith("HC10 room type") for v in result["new_violations"])
    fail_labels = {c["label"] for c in result["checks"] if not c["ok"]}
    assert "Room type compatible" in fail_labels


def test_room_capacity_violation_is_rejected(baseline, ctx):
    row = baseline[0]
    offering = ctx["offering_by_id"][row["offering_id"]]
    course = ctx["courses"][offering["course_id"]]
    student_count = int(offering["student_count"])
    tiny_room = min(
        (r for r in ctx["rooms"].values() if r["room_type"] == course["required_room_type"]),
        key=lambda r: int(r["capacity"]),
    )
    if int(tiny_room["capacity"]) >= student_count:
        pytest.skip("no undersized room of the right type exists in this dataset to force this case")
    edit = {"offering_id": row["offering_id"], "session": row["session"], "new_room_id": tiny_room["room_id"]}
    result = me.check_edit(SYNTHETIC_ROOT, baseline, edit, ctx=ctx)
    assert not result["valid"]
    assert any(v.startswith("HC10 room capacity") for v in result["new_violations"])


def test_faculty_unavailable_is_rejected(baseline):
    _require_synthetic()
    tmp = pathlib.Path(tempfile.mkdtemp())
    changed_root = tmp / "changed_dataset"
    shutil.copytree(SYNTHETIC_ROOT, changed_root)
    row = baseline[3]
    target_slot = next(r["slot_id"] for r in baseline if r["offering_id"] != row["offering_id"] and r["day"] != row["day"])
    fa_path = changed_root / "faculty_availability.csv"
    fa_rows = list(csv.DictReader(open(fa_path)))
    for r in fa_rows:
        if r["faculty_id"] == row["faculty_id"] and r["slot_id"] == target_slot:
            r["available"] = "False"
    with open(fa_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fa_rows[0].keys())
        w.writeheader()
        w.writerows(fa_rows)
    ctx = me.load_edit_context(changed_root)
    edit = {"offering_id": row["offering_id"], "session": row["session"], "new_slot_id": target_slot}
    result = me.check_edit(changed_root, baseline, edit, ctx=ctx)
    assert not result["valid"]
    assert any(v.startswith("HC06 faculty availability") for v in result["new_violations"])


def test_room_unavailable_is_rejected(baseline):
    _require_synthetic()
    tmp = pathlib.Path(tempfile.mkdtemp())
    changed_root = tmp / "changed_dataset"
    shutil.copytree(SYNTHETIC_ROOT, changed_root)
    row = baseline[3]
    target_slot = next(r["slot_id"] for r in baseline if r["room_id"] == row["room_id"] and r["day"] != row["day"])
    ra_path = changed_root / "room_availability.csv"
    ra_rows = list(csv.DictReader(open(ra_path)))
    for r in ra_rows:
        if r["room_id"] == row["room_id"] and r["slot_id"] == target_slot:
            r["available"] = "False"
    with open(ra_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ra_rows[0].keys())
        w.writeheader()
        w.writerows(ra_rows)
    ctx = me.load_edit_context(changed_root)
    edit = {"offering_id": row["offering_id"], "session": row["session"], "new_slot_id": target_slot, "new_room_id": row["room_id"]}
    result = me.check_edit(changed_root, baseline, edit, ctx=ctx)
    assert not result["valid"]
    assert any(v.startswith("HC07 room availability") for v in result["new_violations"])


def test_alternative_slot_search_returns_only_valid(baseline, ctx):
    row = baseline[2]
    alts = me.find_alternative_slots(SYNTHETIC_ROOT, baseline, row["offering_id"], row["session"], max_results=5)
    for a in alts:
        edit = {"offering_id": row["offering_id"], "session": row["session"], "new_slot_id": a["slot_id"], "new_room_id": a["room_id"]}
        result = me.check_edit(SYNTHETIC_ROOT, baseline, edit, ctx=ctx)
        assert result["valid"], f"alternative search returned an invalid candidate: {a} -> {result['new_violations']}"


def test_room_alternatives_flags_incompatible_with_reason(baseline, ctx):
    row = baseline[1]
    result = me.find_room_alternatives(SYNTHETIC_ROOT, baseline, row["offering_id"], row["session"])
    assert result, "expected at least one room in the dataset"
    for r in result:
        if not r["valid"]:
            assert r["reason"], "an invalid room alternative must carry a human-readable reason"


def test_undo_reverts_exactly(baseline, ctx):
    row = baseline[7]
    alts = me.find_alternative_slots(SYNTHETIC_ROOT, baseline, row["offering_id"], row["session"], max_results=1)
    assert alts
    a = alts[0]
    forward = {"offering_id": row["offering_id"], "session": row["session"], "new_slot_id": a["slot_id"], "new_room_id": a["room_id"]}
    applied = me.apply_edit_to_rows(baseline, forward, ctx)

    undo_edit = {"offering_id": row["offering_id"], "session": row["session"], "new_slot_id": row["slot_id"], "new_room_id": row["room_id"]}
    undo_check = me.check_edit(SYNTHETIC_ROOT, applied, undo_edit, ctx=ctx)
    assert undo_check["valid"], undo_check["new_violations"]
    reverted = undo_check["candidate_rows"]
    reverted_row = me._find_row(reverted, row["offering_id"], row["session"])
    assert reverted_row["slot_id"] == row["slot_id"]
    assert reverted_row["room_id"] == row["room_id"]


def test_full_validate_after_multiple_sequential_edits_stays_clean(baseline, ctx):
    rows = baseline
    for i in (4, 9, 15):
        row = rows[i]
        alts = me.find_alternative_slots(SYNTHETIC_ROOT, rows, row["offering_id"], row["session"], max_results=1)
        if not alts:
            continue
        a = alts[0]
        edit = {"offering_id": row["offering_id"], "session": row["session"], "new_slot_id": a["slot_id"], "new_room_id": a["room_id"]}
        result = me.check_edit(SYNTHETIC_ROOT, rows, edit, ctx=ctx)
        assert result["valid"], result["new_violations"]
        rows = result["candidate_rows"]
    vres = validate(None, SYNTHETIC_ROOT, rows=rows)
    assert vres["violations"] == [], vres["violations"]
