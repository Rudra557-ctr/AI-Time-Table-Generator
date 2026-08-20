"""CP4 Tests – Core HARD collisions HC01-03 on toy data.

Each test builds a tiny 3-offering model and verifies solver respects no-overlap.
Run: pytest tests/test_hard_core.py -v
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ortools.sat.python import cp_model
from sih_solver.model import build_variables
from sih_solver.hard import add_faculty_collision, add_room_collision, add_section_collision
from sih_solver.preprocessing import load_all

def _toy_offerings():
    # 3 offerings, use first 3 deduped (may have multiple sessions each)
    data = load_all()
    offs = data["course_offerings_deduped"][:3]
    return offs, data["time_slots.csv"]

def test_faculty_collision_toy():
    offs, time_slots = _toy_offerings()
    # Use only 1 session per offering for toy to keep domain small and avoid HC12 interference
    offs = offs[:3]
    model = cp_model.CpModel()
    Start = {}
    Teacher = {}
    for o in offs:
        oid = o["offering_id"]
        Start[(oid,0)] = model.NewIntVar(0, 4, f"Start_{oid}_0")
        Teacher[oid] = model.NewIntVar(0, 1, f"Teacher_{oid}")
    # Create simplified offerings list with 1 session each for collision logic
    offs_single = [{**o, "required_sessions": "1"} for o in offs]
    add_faculty_collision(model, Start, Teacher, offs_single, time_slots[:5] if len(time_slots)>=5 else time_slots)
    model.Add(Teacher[offs[0]["offering_id"]] == Teacher[offs[1]["offering_id"]])
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), f"solver failed {status}"
    s0 = solver.Value(Start[(offs[0]["offering_id"],0)])
    s1 = solver.Value(Start[(offs[1]["offering_id"],0)])
    assert s0 != s1, f"faculty collision violated: both at {s0}"

def test_room_collision_toy():
    offs, _ = _toy_offerings()
    offs = offs[:3]
    model = cp_model.CpModel()
    Start = {}
    Room = {}
    for o in offs:
        oid = o["offering_id"]
        Start[(oid,0)] = model.NewIntVar(0, 4, f"Start_{oid}_0")
        Room[(oid,0)] = model.NewIntVar(0, 1, f"Room_{oid}_0")
    offs_single = [{**o, "required_sessions": "1"} for o in offs]
    add_room_collision(model, Start, Room, offs_single)
    model.Add(Room[(offs[0]["offering_id"],0)] == Room[(offs[1]["offering_id"],0)])
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    s0 = solver.Value(Start[(offs[0]["offering_id"],0)])
    s1 = solver.Value(Start[(offs[1]["offering_id"],0)])
    assert s0 != s1

def test_section_collision_toy():
    data = load_all()
    from collections import defaultdict
    sec_map = defaultdict(list)
    for o in data["course_offerings_deduped"]:
        sec_map[o["section_id"]].append(o)
    sec, offs_list = next((k,v) for k,v in sec_map.items() if len(v)>=2)
    offs = offs_list[:2]
    model = cp_model.CpModel()
    Start = {}
    for o in offs:
        oid = o["offering_id"]
        rs = int(o["required_sessions"])
        for s in range(rs):
            Start[(oid,s)] = model.NewIntVar(0, 34, f"Start_{oid}_{s}")
    add_section_collision(model, Start, offs)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), f"status {status} infeasible due to tiny domain"
    # Check all sessions of the two offerings are pairwise distinct within same section
    for (oid1,s1) in [(offs[0]["offering_id"],0),(offs[0]["offering_id"],1)]:
        if (oid1,s1) not in Start: continue
        for (oid2,s2) in [(offs[1]["offering_id"],0)]:
            if solver.Value(Start[(oid1,s1)]) == solver.Value(Start[(oid2,s2)]):
                assert False, f"section collision {oid1}:{s1} == {oid2}:{s2}"

def test_full_cp4_small_feasible():
    data = load_all()
    offs = data["course_offerings_deduped"][:5]
    small_data = load_all()
    small_data["course_offerings_deduped"] = offs
    model2 = cp_model.CpModel()
    Start2 = {}
    Teacher2 = {}
    Room2 = {}
    for o in offs:
        oid = o["offering_id"]
        for s in range(int(o["required_sessions"])):
            Start2[(oid,s)] = model2.NewIntVar(0, 34, f"S_{oid}_{s}")
            Room2[(oid,s)] = model2.NewIntVar(0, 5, f"R_{oid}_{s}")
        Teacher2[oid] = model2.NewIntVar(0, 5, f"T_{oid}")
    add_faculty_collision(model2, Start2, Teacher2, offs, small_data["time_slots.csv"])
    add_room_collision(model2, Start2, Room2, offs)
    add_section_collision(model2, Start2, offs)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model2)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), f"small feasible failed {status}"
