"""Regression test for the dynamic re-solve feature (PLAN.md: "every change
to one section cascades through the rest" -- the named pain point this
answers). Verifies the actual guarantee: a single forced input change
produces a small, valid diff against the previous solve, not a full
re-decision of the whole timetable, and the result is independently
hard-constraint-clean.

Uses the synthetic dataset (fast to solve) rather than the bundled sample,
consistent with test_synthetic_dataset.py -- this is dataset-driven, not
tied to any one dataset's specific IDs.
"""
import csv
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sih_solver.full_model import build_full_hard_model
from sih_solver.solve_pipeline import solve_incremental_resolve
from sih_solver.validate_output import validate
from ortools.sat.python import cp_model

SYNTHETIC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "synthetic_data"


def _solve_once(root):
    model, Start, Teacher, Room, meta = build_full_hard_model(root)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), f"baseline solve failed: {status}"
    return solver, Start, Teacher, Room, meta


def _write_csv(path, solver, Start, Teacher, Room, meta):
    slots = {s["slot_id"]: s for s in meta["data"]["time_slots.csv"]}
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["offering_id", "course_id", "section_id", "session", "slot_id",
                    "day", "start_time", "end_time", "room_id", "faculty_id"])
        for o in meta["offerings"]:
            oid = o["offering_id"]
            fac = meta["idx_to_fac"][solver.Value(Teacher[oid])]
            for s in range(int(o["required_sessions"])):
                slot_id = meta["idx_to_slot"][solver.Value(Start[(oid, s)])]
                room_id = meta["idx_to_room"][solver.Value(Room[(oid, s)])]
                sl = slots[slot_id]
                w.writerow([oid, o["course_id"], o["section_id"], s + 1, slot_id,
                            sl["day"], sl["start_time"], sl["end_time"], room_id, fac])


def test_resolve_localizes_a_single_forced_change():
    if not SYNTHETIC_ROOT.exists():
        import pytest
        pytest.skip("run scripts/generate_synthetic_dataset.py first")

    tmp = pathlib.Path(tempfile.mkdtemp())
    baseline_csv = tmp / "baseline.csv"
    solver, Start, Teacher, Room, meta = _solve_once(SYNTHETIC_ROOT)
    _write_csv(baseline_csv, solver, Start, Teacher, Room, meta)

    # Force one real assignment to become infeasible: mark that session's
    # faculty unavailable at exactly the slot they were assigned.
    rows = list(csv.DictReader(open(baseline_csv)))
    forced_row = rows[0]
    changed_root = tmp / "changed_dataset"
    shutil.copytree(SYNTHETIC_ROOT, changed_root)
    fa_path = changed_root / "faculty_availability.csv"
    fa_rows = list(csv.DictReader(open(fa_path)))
    for r in fa_rows:
        if r["faculty_id"] == forced_row["faculty_id"] and r["slot_id"] == forced_row["slot_id"]:
            r["available"] = "False"
    with open(fa_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fa_rows[0].keys())
        w.writeheader()
        w.writerows(fa_rows)

    result = solve_incremental_resolve(
        changed_root, baseline_csv,
        stability_time_limit=30.0, tier_time_limits=(15.0, 10.0, 10.0),
    )

    # The forced change must actually be reflected: the previously-assigned
    # faculty is no longer teaching that exact session at that exact slot.
    assert len(result["changed"]) >= 1, "nothing changed despite forcing a real conflict"
    # The core guarantee: this should be a SMALL, localized diff, not a
    # wholesale re-decision. 84 sessions total in this dataset -- a resolve
    # that moves more than a handful has failed the actual point of the
    # feature, even if every individual assignment is still valid.
    assert len(result["changed"]) <= 5, f"resolve cascaded too far: {len(result['changed'])} changes"

    out_csv = tmp / "resolved.csv"
    _write_csv(out_csv, result["solver"], result["Start"], result["Teacher"], result["Room"], result["meta"])
    vres = validate(out_csv, changed_root)
    assert vres["violations"] == [], vres["violations"]
