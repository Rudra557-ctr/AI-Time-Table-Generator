"""Phase B tests — validator L1+L2+L3 (sih_solver/validator.py).

Run:  pytest tests/test_validator.py -v
"""
import csv
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sih_solver.validator import validate_all, validate_single_dataset
from sih_solver.schema import template_rows, SCHEMAS


def _load_store(keys=None):
    """Load repo's CSVs into a dict dataset->rows."""
    keys = keys or ["universities","departments","programs","academic_terms","time_slots","sections","students","rooms","courses","faculty","faculty_courses","faculty_availability","room_availability","course_offerings","elective_groups","elective_group_courses","student_enrollments","fixed_events","academic_rules"]
    root = pathlib.Path(__file__).resolve().parents[1]
    data = {}
    for ds in keys:
        p = root / f"{ds}.csv"
        if p.exists():
            with open(p, newline="", encoding="utf-8-sig") as f:
                data[ds] = list(csv.DictReader(f))
        else:
            data[ds] = []
    return data


def test_repo_store_solvable_after_dedup_downgrade():
    """Real synthetic dataset should be solvable (0 blockers) after legacy dedup downgrade."""
    data = _load_store()
    res = validate_all(data)
    assert res["summary"]["can_solve"] is True, f"unexpected blockers: {res['blockers'][:2]}"
    assert res["summary"]["total_blockers"] == 0
    # warnings are the legacy 11+531 duplicates plus ~13 capacity fallbacks
    assert res["summary"]["total_warnings"] >= 540

def test_minimal_template_store_clean():
    data = {ds: template_rows(ds, include_example=True) for ds in SCHEMAS.keys()}
    # prune datasets that template_rows leaves empty? use all 19
    res = validate_all(data)
    assert res["summary"]["can_solve"] is True, res["blockers"][:2]
    assert res["summary"]["total_blockers"] == 0

def test_missing_required_file_is_blocker():
    data = _load_store()
    data.pop("courses")
    res = validate_all(data)
    assert any(i["dataset"] == "courses" and "missing" in i["message"].lower() for i in res["blockers"])

def test_empty_required_file_is_blocker():
    data = _load_store()
    data["course_offerings"] = []
    res = validate_all(data)
    assert any(i["dataset"] == "course_offerings" and "empty" in i["message"].lower() for i in res["blockers"])

def test_fk_missing_is_blocker():
    data = _load_store()
    # inject a faculty_courses row with non-existent faculty
    data["faculty_courses"] = list(data["faculty_courses"])
    data["faculty_courses"].append({"faculty_id": "F999", "course_id": "C001", "qualification_level": "PRIMARY", "preferred": "True"})
    res = validate_all(data)
    assert any(i["dataset"] == "faculty_courses" and "F999" in i["message"] for i in res["blockers"])

def test_fk_offering_course_missing_is_blocker():
    data = _load_store()
    data["course_offerings"] = list(data["course_offerings"])
    data["course_offerings"].append({"offering_id": "O9999", "course_id": "C999", "section_id": "S_CSE_1_A", "required_sessions": "1", "session_duration": "1", "student_count": "60"})
    res = validate_all(data)
    assert any(i["dataset"] == "course_offerings" and "C999" in i["message"] for i in res["blockers"])

def test_no_eligible_faculty_is_blocker():
    # Build minimal clean store then add a course with no faculty_courses entry
    data = {ds: template_rows(ds, include_example=True) for ds in ["departments","programs","time_slots","sections","rooms","courses","faculty","faculty_courses","course_offerings"]}
    # courses template has C001 with eligible faculty F001; add new course C999 with no faculty_courses
    data["courses"].append({"course_id": "C999", "course_code": "TST999", "course_name": "No Faculty Course",
                           "department_id": "D01", "course_type": "THEORY", "course_category": "CORE",
                           "credits": "3", "weekly_hours": "3", "sessions_per_week": "3", "session_duration": "1",
                           "requires_lab": "False", "required_room_type": "CLASSROOM", "min_room_capacity": "30", "equipment_required": ""})
    data["course_offerings"].append({"offering_id": "O9999", "course_id": "C999", "section_id": "S_CSE_1_A",
                                   "required_sessions": "3", "session_duration": "1", "student_count": "60"})
    res = validate_all(data)
    assert any("no eligible faculty" in i["message"].lower() for i in res["blockers"])

def test_incompatible_room_is_warning_not_blocker():
    """Workshop DRAWING_BOARDS case falls back; should be WARNING so solve gate not blocked."""
    data = _load_store()
    # Real data already contains C007 workshop case — check it's reported as warning after downgrade
    res = validate_all(data)
    assert any("C007" in i["message"] for i in res["warnings"])
    assert not any("C007" in i["message"] for i in res["blockers"])

def test_capacity_exceed_is_warning():
    data = _load_store()
    res = validate_all(data)
    # At least one capacity warning should exist (C006 etc.) and none as blocker
    assert any("exceeds largest compatible room capacity" in i["message"] for i in res["warnings"])
    assert not any("exceeds largest compatible room capacity" in i["message"] for i in res["blockers"])

def test_duration2_without_contiguous_is_blocker():
    data = {ds: template_rows(ds, include_example=True) for ds in SCHEMAS.keys()}
    # Make a single isolated slot (no pair) and a duration-2 course
    data["time_slots"] = [{"slot_id": "MON_0900", "day": "MON", "period_number": "1", "start_time": "09:00", "end_time": "10:00", "is_break": "False"}]
    data["courses"][0]["session_duration"] = "2"
    data["courses"][0]["sessions_per_week"] = "1"
    data["courses"][0]["weekly_hours"] = "2"
    data["course_offerings"][0]["session_duration"] = "2"
    data["course_offerings"][0]["required_sessions"] = "1"
    res = validate_all(data)
    assert any("contiguous" in i["message"].lower() for i in res["blockers"])

def test_per_dataset_counts():
    data = _load_store()
    res = validate_all(data)
    assert "course_offerings" in res["per_dataset"]
    assert res["per_dataset"]["course_offerings"]["rows"] == 144
    assert "time_slots" in res["per_dataset"]

def test_validate_single_dataset_strict_duplicate_is_blocker():
    data = {ds: template_rows(ds, include_example=True) for ds in SCHEMAS.keys()}
    rows_dup = [
        {"offering_id": "O1", "course_id": "C001", "section_id": "S_CSE_1_A", "required_sessions": "4", "session_duration": "1", "student_count": "65"},
        {"offering_id": "O2", "course_id": "C001", "section_id": "S_CSE_1_A", "required_sessions": "4", "session_duration": "1", "student_count": "60"},
    ]
    res = validate_single_dataset("course_offerings", rows_dup, whole_store=data)
    assert res["summary"]["total_blockers"] >= 1
    assert any("Duplicate offering" in i["message"] for i in res["blockers"])
    assert res["blockers"][0]["severity"] == "BLOCKER"

def test_validate_single_dataset_fk_flagged():
    data = {ds: template_rows(ds, include_example=True) for ds in SCHEMAS.keys()}
    rows = [{"faculty_id": "F999", "course_id": "C001", "qualification_level": "PRIMARY", "preferred": "True"}]
    res = validate_single_dataset("faculty_courses", rows, whole_store=data)
    assert any("F999" in i["message"] for i in res["blockers"])

def test_l1_unknown_dataset_blocker():
    res = validate_all({"no_such": [{"a": "b"}]})
    assert any("Unknown dataset" in i["message"] for i in res["blockers"])
