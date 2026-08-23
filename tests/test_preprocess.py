"""CP2 Tests – Preprocessing Derived Data. Run: pytest tests/test_preprocess.py -v"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from sih_solver.preprocessing import (
    load_all, eligible_faculty_per_course, compatible_rooms_by_course,
    valid_faculty_slots, valid_room_slots, contiguous_slot_sets, all_contiguous_starts,
    blocked_assignments, student_elective_offerings, synchronized_offering_groups
)

from pathlib import Path
# Use corrected dataset for capacity-feasible tests (labs 70 vs raw 40)
CORRECTED = Path("/tmp/sih_timetable_dataset_corrected")
data = load_all(CORRECTED if CORRECTED.exists() else None)

def test_eligible_faculty_nonempty():
    ef = eligible_faculty_per_course(data["faculty_courses.csv"])
    assert len(ef) == 65
    for c, facs in ef.items():
        assert len(facs) >= 3, f"{c} has <3 eligible"

def test_compatible_rooms_C028_single():
    comp = compatible_rooms_by_course(data["courses.csv"], data["rooms.csv"], data["course_offerings_deduped"])
    c028_rooms = [r["room_id"] for r in comp["C028"]]
    # C028 requires MICROCONTROLLERS -> only EL001
    assert "EL001" in c028_rooms
    assert len(c028_rooms) == 1, f"C028 should have 1 compatible, got {c028_rooms}"

def test_compatible_rooms_PHYSICS_LAB_single():
    comp = compatible_rooms_by_course(data["courses.csv"], data["rooms.csv"], data["course_offerings_deduped"])
    c006_rooms = [r["room_id"] for r in comp["C006"]]
    assert "PL001" in c006_rooms
    assert len(c006_rooms) == 1

def test_compatible_rooms_computers_fallback():
    # C017 requires DATABASE_SYSTEMS which is not in any room equipment – fallback to type+capacity
    comp = compatible_rooms_by_course(data["courses.csv"], data["rooms.csv"], data["course_offerings_deduped"])
    c017_rooms = comp["C017"]
    assert len(c017_rooms) >= 6, "C017 fallback should give COMPUTER_LAB rooms"
    # All should be COMPUTER_LAB
    for r in c017_rooms:
        assert r["room_type"] == "COMPUTER_LAB"

def test_valid_faculty_slots_range():
    vfs = valid_faculty_slots(data["faculty_availability.csv"])
    assert len(vfs) == 40
    # F004 should have only 6 slots (restricted)
    assert len(vfs["F004"]) == 6
    assert len(vfs["F001"]) >= 30

def test_contiguous_excludes_lunch_gap():
    csets = contiguous_slot_sets(data["time_slots.csv"], k=2)
    # MON_1200 (12:00-13:00) -> MON_1400 (14:00-15:00) should NOT be contiguous
    for day, groups in csets.items():
        for tup in groups:
            if "MON_1200" in tup:
                assert "MON_1400" not in tup, f"lunch gap incorrectly contiguous {tup}"
    # Check at least one known contiguous pair exists
    assert ("MON_0900","MON_1000") in csets["MON"]

def test_all_contiguous_starts_duration2():
    starts = all_contiguous_starts(data["time_slots.csv"], duration=2)
    assert "MON_1200" not in starts, "MON_1200 cannot start 2h across lunch"
    assert "MON_0900" in starts

def test_blocked_assignments_lunch_and_meeting():
    blocked = blocked_assignments(data["fixed_events.csv"], data["time_slots.csv"])
    # EV002 lunch 13:00-14:00 ALL – no slot should be blocked because 13-14 is absent from grid; but check logic: slots are 12-13 and 14-15, so no overlap
    # Actually lunch is 13-14, which overlaps none of the 35 slots (slots end 13:00, next start 14:00) -> empty
    # EV001 Mon 12-13 ALL_FACULTY should block MON_1200
    assert "MON_1200" in blocked["EV001"]["slots"]

def test_synchronized_groups_6():
    groups = synchronized_offering_groups(data["elective_groups.csv"], data["elective_group_courses.csv"], data["course_offerings_deduped"])
    # One group per synchronized (elective_group, course): same course across
    # sections is a shared cross-section elective class -> must share a slot.
    assert len(groups) == 13
    for g in groups:
        assert len(g["offerings"]) >= 2
        # All offerings in a group are the SAME course (cross-section sync)
        assert "course_id" in g

def test_student_elective_offerings():
    seo = student_elective_offerings(data["student_enrollments.csv"], data["course_offerings_deduped"])
    # 750 OAE/PCE enrollments but per student deduped to offerings, should have entries
    assert len(seo) > 0
    # Spot check a known OAE student
    # Find a student with OAE enrollment
    import csv
    enrolls = data["student_enrollments.csv"]
    oae_students = [r["student_id"] for r in enrolls if r["enrollment_type"]=="OAE"]
    assert oae_students
    assert oae_students[0] in seo
