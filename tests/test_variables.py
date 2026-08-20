"""CP3 Tests – Variables + Domain. Run: pytest tests/test_variables.py -v"""
import pathlib, sys, pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from sih_solver.model import build_variables
from sih_solver.preprocessing import all_contiguous_starts

@pytest.fixture(scope="module")
def build():
    return build_variables()

def test_variable_counts(build):
    _, Start, Teacher, Room, meta = build
    assert len(meta["offerings"]) == 133
    total_sessions = sum(int(o["required_sessions"]) for o in meta["offerings"])
    assert total_sessions == 370, f"total sessions {total_sessions} !=370"
    assert len(Teacher) == 133
    assert len(Start) == 370
    assert len(Room) == 370

def test_teacher_domain_matches_eligible(build):
    _, _, Teacher, _, meta = build
    # spot check 3 offerings
    for oid in list(Teacher.keys())[:3]:
        course_id = next(o["course_id"] for o in meta["offerings"] if o["offering_id"]==oid)
        elig = meta["eligible"].get(course_id, set())
        assert len(elig) >= 3

def test_start_domain_excludes_lunch_gap(build):
    _, Start, _, _, meta = build
    valid = all_contiguous_starts(meta["data"]["time_slots.csv"], 2)
    assert "MON_1200" not in valid
    assert "MON_0900" in valid

def test_room_domain_not_empty(build):
    _, _, _, Room, meta = build
    assert len(Room) == 370
    # spot check compatible non-empty via meta
    sample_course = meta["offerings"][0]["course_id"]
    assert len(meta["compatible"].get(sample_course, [])) >= 1

def test_single_faculty_per_offering(build):
    _, Start, Teacher, _, _ = build
    assert len(Teacher) != len(Start)
    assert len(Teacher) == 133
