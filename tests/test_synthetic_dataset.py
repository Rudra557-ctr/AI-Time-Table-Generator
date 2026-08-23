"""Regression test for the synthetic dataset (scripts/generate_synthetic_dataset.py,
synthetic_data/) -- a second, independently-built dataset (different
institution/departments/courses/IDs/scale, same schema) that the pipeline
must handle without any dataset-specific code. See PLAN.md: this is the
first real evidence for the pipeline's genericity claims beyond the one
bundled sample dataset every other test uses.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sih_solver.dataset import quick_solvability_check
from sih_solver.full_model import build_full_hard_model
from sih_solver.validate_output import validate
from ortools.sat.python import cp_model

SYNTHETIC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "synthetic_data"


def test_synthetic_dataset_exists():
    assert SYNTHETIC_ROOT.exists(), "run scripts/generate_synthetic_dataset.py first"
    for fname in ("courses.csv", "course_offerings.csv", "faculty.csv", "rooms.csv",
                  "time_slots.csv", "sections.csv"):
        assert (SYNTHETIC_ROOT / fname).exists(), f"missing {fname}"


def test_synthetic_dataset_passes_quick_solvability_check():
    result = quick_solvability_check(SYNTHETIC_ROOT)
    assert result["blockers"] == [], result["blockers"]


def test_synthetic_dataset_solves_and_validates_clean():
    model, Start, Teacher, Room, meta = build_full_hard_model(SYNTHETIC_ROOT)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), \
        f"expected a solution within 30s on this small synthetic dataset, got {status}"

    import csv
    slots = {s["slot_id"]: s for s in meta["data"]["time_slots.csv"]}
    out_path = SYNTHETIC_ROOT / "sample_solved_timetable.csv"
    with open(out_path, "w", newline="") as f:
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

    vres = validate(out_path, SYNTHETIC_ROOT)
    assert vres["violations"] == [], vres["violations"]
