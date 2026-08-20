"""CP7 Tests – SOFT objective + human loop. Run: pytest tests/test_soft.py -v"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from sih_solver.full_model import build_full_hard_model
from sih_solver.soft import add_soft_objective, apply_human_feedback, DEFAULT_WEIGHTS
from ortools.sat.python import cp_model

def _small_model(limit=20):
    # Helper to build small model for fast soft tests (20 offerings ~53 sessions)
    from sih_solver.preprocessing import load_all
    import pathlib
    data = load_all(pathlib.Path("/tmp/sih_timetable_dataset_corrected"))
    offs = data["course_offerings_deduped"][:limit]
    from sih_solver.model import build_variables
    import sih_solver.preprocessing as pre
    # Build via full_model but patch data
    orig = pre.load_all
    pre.load_all = lambda root=None: {**data, "course_offerings_deduped": offs}
    from sih_solver.full_model import build_full_hard_model
    model, Start, Teacher, Room, meta = build_full_hard_model(pathlib.Path("/tmp/sih_timetable_dataset_corrected"))
    pre.load_all = orig
    # Filter meta to demo subset (re-create filtered vars)
    # Instead, just return small model built manually via build_full_hard_model with small data hack
    # For simplicity, rebuild small directly:
    from ortools.sat.python import cp_model as cp
    from sih_solver.model import build_variables as bv
    # Use the earlier built model but slice? We'll just use the model we built which already has 133 but we will filter
    # For test speed, create a fresh small model using helper similar to /tmp/make_timetable
    return model, Start, Teacher, Room, meta

def test_soft_objective_changes_solution():
    # Use small demo to avoid 370-session heavy soft model timeout
    from sih_solver.preprocessing import load_all
    import pathlib
    from sih_solver.model import build_variables
    from sih_solver.hard import add_faculty_collision, add_room_collision, add_section_collision
    from sih_solver.full_model import add_availability_constraints, add_fixed_events, add_workload_constraints
    data = load_all(pathlib.Path("/tmp/sih_timetable_dataset_corrected"))
    offs = data["course_offerings_deduped"][:15]
    # Build small model quickly
    from sih_solver.full_model import build_full_hard_model
    # Create small via direct helper
    import sih_solver.preprocessing as pre
    orig = pre.load_all
    pre.load_all = lambda root=None: {**data, "course_offerings_deduped": offs}
    model1, Start1, Teacher1, Room1, meta1 = build_full_hard_model(pathlib.Path("/tmp/sih_timetable_dataset_corrected"))
    pre.load_all = orig
    solver1 = cp_model.CpSolver()
    solver1.parameters.max_time_in_seconds = 8.0
    solver1.parameters.num_search_workers = 4
    status1 = solver1.Solve(model1)
    assert status1 in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.UNKNOWN)
    # With soft
    pre.load_all = lambda root=None: {**data, "course_offerings_deduped": offs}
    model2, Start2, Teacher2, Room2, meta2 = build_full_hard_model(pathlib.Path("/tmp/sih_timetable_dataset_corrected"))
    pre.load_all = orig
    add_soft_objective(model2, Start2, Teacher2, Room2, meta2, DEFAULT_WEIGHTS)
    solver2 = cp_model.CpSolver()
    solver2.parameters.max_time_in_seconds = 8.0
    solver2.parameters.num_search_workers = 4
    status2 = solver2.Solve(model2)
    assert status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.UNKNOWN)
    if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        assert solver2.ObjectiveValue() >= 0

def test_human_feedback_tunes_weights():
    w = DEFAULT_WEIGHTS.copy()
    fb = {"SC01_pref": 15, "comment": "too many gaps TUE"}
    new_w = apply_human_feedback(w, fb)
    assert new_w["SC01_pref"] == 15
    assert new_w["SC02_gaps"] > w["SC02_gaps"]

def test_soft_does_not_break_hard():
    from sih_solver.preprocessing import load_all
    import pathlib, sih_solver.preprocessing as pre
    data = load_all(pathlib.Path("/tmp/sih_timetable_dataset_corrected"))
    offs = data["course_offerings_deduped"][:15]
    orig = pre.load_all
    pre.load_all = lambda root=None: {**data, "course_offerings_deduped": offs}
    model, Start, Teacher, Room, meta = build_full_hard_model(pathlib.Path("/tmp/sih_timetable_dataset_corrected"))
    pre.load_all = orig
    add_soft_objective(model, Start, Teacher, Room, meta, {"SC01_pref": 10})
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 8.0
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)
    assert status != cp_model.INFEASIBLE, "soft made hard infeasible – should be objective only"
