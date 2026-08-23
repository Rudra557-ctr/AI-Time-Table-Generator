"""Phase A tests — schema single source of truth (sih_solver/schema.py).

Run:  pytest tests/test_schema.py -v
"""
import io, csv, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sih_solver.schema import (
    SCHEMAS, CANONICAL, EXAMPLES, list_datasets, get_schema, get_field,
    validate_rows, template_csv, template_rows, required_datasets, optional_datasets,
)


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

def test_all_datasets_present():
    assert set(list_datasets()) == set(SCHEMAS.keys())
    assert len(list_datasets()) == 19

def test_required_and_optional_partition():
    req = required_datasets()
    opt = optional_datasets()
    assert set(req) | set(opt) == set(SCHEMAS.keys())
    assert set(req) & set(opt) == set()
    # departments/programs are required too: faculty/courses.department_id and
    # sections.program_id are FK fields that must resolve once those (required)
    # datasets have rows, so leaving them "optional" broke can_solve (see schema.py).
    assert set(req) == {"time_slots", "rooms", "faculty", "courses", "faculty_courses", "course_offerings",
                         "sections", "departments", "programs"}

def test_canonical_alias_matches_headers():
    for ds, fields in SCHEMAS.items():
        assert CANONICAL[ds] == [f["name"] for f in fields]

def test_example_rows_have_required_fields():
    for ds in list_datasets():
        fields = get_schema(ds)
        ex = EXAMPLES.get(ds, {})
        for f in fields:
            if f["required"]:
                assert f["name"] in ex, f"{ds}.{f['name']} missing in EXAMPLES"
                assert str(ex[f["name"]]).strip() != "", f"{ds}.{f['name']} example is blank"

def test_template_csv_headers_match_canonical():
    for ds in list_datasets():
        csv_str = template_csv(ds)
        reader = csv.DictReader(io.StringIO(csv_str))
        assert reader.fieldnames == CANONICAL[ds]

def test_template_csv_includes_all_canonical_columns():
    """User requirement: templates contain ALL relevant columns."""
    for ds in list_datasets():
        csv_str = template_csv(ds)
        header = csv_str.splitlines()[0].split(",")
        assert header == CANONICAL[ds], f"{ds} template missing columns"

def test_template_example_row_validates_clean():
    """Each example row should pass L1 validation (no BLOCKERs)."""
    for ds in list_datasets():
        rows = template_rows(ds, include_example=True)
        issues = validate_rows(ds, rows)
        assert issues == [], f"{ds} example row failed L1: {issues!r}"

def test_template_header_only_no_issues():
    for ds in list_datasets():
        issues = validate_rows(ds, [])
        assert issues == []


# ---------------------------------------------------------------------------
# L1 validation — happy paths
# ---------------------------------------------------------------------------

def test_validate_rows_repo_courses_faculty_rooms_pass():
    """Repo's own clean files should have 0 L1 issues (except known C#14/enrollment dupes tested elsewhere)."""
    import pathlib as pl
    root = pl.Path(__file__).resolve().parents[1]
    for ds in ["courses", "faculty", "rooms", "time_slots", "departments", "programs", "sections",
               "elective_groups", "elective_group_courses", "fixed_events", "academic_rules"]:
        p = root / f"{ds}.csv"
        assert p.exists()
        with open(p, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        issues = validate_rows(ds, rows)
        assert issues == [], f"{ds} should be clean, got {issues[:2]}"

def test_faculty_availability_with_zero_score_passes():
    """Synthetic dataset uses 0 as preference_score — must be valid (min 0)."""
    rows = [{"faculty_id": "F001", "slot_id": "MON_0900", "available": "True", "preference_score": "0"}]
    assert validate_rows("faculty_availability", rows) == []


# ---------------------------------------------------------------------------
# L1 validation — issue detection (BLOCKERs)
# ---------------------------------------------------------------------------

def test_missing_required_field_flagged():
    rows = [{"course_code": "MAT101", "course_name": "Maths"}]  # missing course_id etc.
    issues = validate_rows("courses", rows)
    fields = {i["field"] for i in issues}
    assert "course_id" in fields

def test_int_type_flagged():
    rows = [{"course_id": "C001", "course_code": "MAT101", "course_name": "M", "department_id": "D01",
             "course_type": "THEORY", "course_category": "CORE", "credits": "bad",
             "weekly_hours": "4", "sessions_per_week": "4", "session_duration": "1",
             "requires_lab": "False", "required_room_type": "CLASSROOM", "min_room_capacity": "50"}]
    issues = validate_rows("courses", rows)
    assert any(i["field"] == "credits" for i in issues)

def test_enum_flagged():
    rows = [{"course_id": "C001", "course_code": "X", "course_name": "Y", "department_id": "D01",
             "course_type": "BADTYPE", "course_category": "CORE", "credits": "4",
             "weekly_hours": "4", "sessions_per_week": "4", "session_duration": "1",
             "requires_lab": "False", "required_room_type": "CLASSROOM", "min_room_capacity": "50"}]
    assert any(i["field"] == "course_type" for i in validate_rows("courses", rows))

def test_bool_flagged():
    rows = [{"course_id": "C001", "course_code": "X", "course_name": "Y", "department_id": "D01",
             "course_type": "THEORY", "course_category": "CORE", "credits": "4",
             "weekly_hours": "4", "sessions_per_week": "4", "session_duration": "1",
             "requires_lab": "maybe", "required_room_type": "CLASSROOM", "min_room_capacity": "50"}]
    assert any(i["field"] == "requires_lab" for i in validate_rows("courses", rows))

def test_time_format_flagged():
    rows = [{"slot_id": "MON_0900", "day": "MON", "period_number": "1", "start_time": "9am", "end_time": "10:00", "is_break": "False"}]
    assert any(i["field"] == "start_time" for i in validate_rows("time_slots", rows))

def test_end_before_start_flagged():
    rows = [{"slot_id": "MON_0900", "day": "MON", "period_number": "1", "start_time": "11:00", "end_time": "10:00", "is_break": "False"}]
    assert any(i["field"] == "end_time" for i in validate_rows("time_slots", rows))

def test_duplicate_unique_flagged():
    rows = [
        {"department_id": "D01", "department_name": "CSE"},
        {"department_id": "D01", "department_name": "ECE"},
    ]
    assert any("Duplicate" in i["message"] for i in validate_rows("departments", rows))

def test_course_offering_duplicate_combo_flagged():
    rows = [
        {"offering_id": "O1", "course_id": "C001", "section_id": "S_CSE_1_A", "required_sessions": "4", "session_duration": "1", "student_count": "65"},
        {"offering_id": "O2", "course_id": "C001", "section_id": "S_CSE_1_A", "required_sessions": "4", "session_duration": "1", "student_count": "60"},
    ]
    assert any("Duplicate offering" in i["message"] for i in validate_rows("course_offerings", rows))

def test_weekly_hours_mismatch_flagged():
    rows = [{"course_id": "C001", "course_code": "X", "course_name": "Y", "department_id": "D01",
             "course_type": "THEORY", "course_category": "CORE", "credits": "4",
             "weekly_hours": "10", "sessions_per_week": "4", "session_duration": "1",
             "requires_lab": "False", "required_room_type": "CLASSROOM", "min_room_capacity": "50"}]
    assert any(i["field"] == "weekly_hours" and "!=" in i["message"] for i in validate_rows("courses", rows))

def test_faculty_min_exceeds_max_flagged():
    rows = [{"faculty_id": "F001", "name": "X", "department_id": "D01", "designation": "Professor",
             "employment_type": "PERMANENT", "max_hours_per_week": "10", "max_hours_per_day": "4", "min_hours_per_week": "12"}]
    assert any("min_hours_per_week" in i["field"] and "exceeds" in i["message"] for i in validate_rows("faculty", rows))

def test_range_min_max_flagged():
    rows = [{"faculty_id": "F001", "name": "X", "department_id": "D01", "designation": "Professor",
             "employment_type": "PERMANENT", "max_hours_per_week": "100", "max_hours_per_day": "4", "min_hours_per_week": "8"}]
    assert any(i["field"] == "max_hours_per_week" for i in validate_rows("faculty", rows))

def test_unknown_dataset_returns_blocker():
    issues = validate_rows("no_such_dataset", [])
    assert len(issues) == 1 and issues[0]["severity"] == "BLOCKER"

def test_row_numbers_are_one_indexed_and_issue_has_dataset_and_hint():
    rows = [
        {"department_id": "D01", "department_name": "CSE"},
        {"department_id": "", "department_name": "ECE"},   # row 2 empty required
    ]
    issues = validate_rows("departments", rows)
    assert any(i["row"] == 2 and i["dataset"] == "departments" and "fix_hint" in i for i in issues)
    assert all(i["severity"] == "BLOCKER" for i in issues)

def test_optional_blank_equipment_not_flagged():
    """equipment fields are optional — blank should pass."""
    rows = [{"room_id": "R001", "room_name": "Room", "building": "A", "floor": "1",
             "room_type": "CLASSROOM", "capacity": "40", "has_projector": "True",
             "has_computers": "False", "has_ac": "True", "equipment": ""}]
    assert validate_rows("rooms", rows) == []

def test_get_schema_and_get_field():
    assert get_field("courses", "course_id")["required"] is True
    try:
        get_schema("unknown_ds")
        assert False, "should raise KeyError"
    except KeyError:
        pass
