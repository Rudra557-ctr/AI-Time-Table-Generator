"""Phase A — Single source of truth for every dataset schema.

All 19 datasets from data_dictionary.csv + adapter.CANONICAL.
Field specs drive:
  - form/table rendering in the wizard UI
  - dropdown enums (typos structurally impossible)
  - L1 validation via validate_rows() (types / enums / required / ranges / formats)
  - template generation via template_csv() (ALL canonical columns + 1 example row)

Wizard steps rely on get_schema() / list_datasets() / validate_rows() / template_csv().
Validator (Phase B) reuses these for L1 then adds L2/L3 cross-dataset checks.

Types use the same wording as data_dictionary.csv:
  object  -> non-empty string (free text unless enum/format is given)
  int64   -> base-10 integer
  bool    -> True/False variants (True/true/TRUE/1/yes/Yes vs False/false/FALSE/0/no/No)
  time    -> HH:MM 24h
  date    -> YYYY-MM-DD

Severity for L1 issues is always BLOCKER (hard stop before solve).
"""
from __future__ import annotations

import csv
import io
import re
from typing import List, Dict, Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLOT_RE = re.compile(r"^[A-Z]{3}_\d{4}$")

_BOOL_TRUE = {"true", "1", "yes", "y", "t"}
_BOOL_FALSE = {"false", "0", "no", "n", "f"}

# canonical day values (academic teaching days + ALL for fixed_events)
DAYS = ["MON", "TUE", "WED", "THU", "FRI"]
DAYS_PLUS_ALL = DAYS + ["ALL"]

def _is_bool_str(v: str) -> bool:
    return v.strip().lower() in _BOOL_TRUE | _BOOL_FALSE

def _is_int_str(v: str) -> bool:
    try:
        int(v.strip())
        return True
    except Exception:
        return False

def _parse_int(v: str):
    return int(v.strip())

# ---------------------------------------------------------------------------
# SCHEMAS — one entry per dataset; order matches data_dictionary.csv
# Each field dict may contain:
#   name, dtype, required, enum, pattern, format, min, max, unique, description,
#   auto_id  (format string for UI auto-generation, e.g. "C{idx:03d}")
# ---------------------------------------------------------------------------

SCHEMAS: Dict[str, List[Dict[str, Any]]] = {

    # Tier 4 context — keep full wizard steps as requested
    "universities": [
        {"name": "university_id", "dtype": "object", "required": True, "unique": True, "auto_id": "U{idx:03d}", "description": "Primary key"},
        {"name": "university_name", "dtype": "object", "required": True, "description": "Display name"},
        {"name": "campus", "dtype": "object", "required": True, "description": "Campus label"},
        {"name": "academic_year", "dtype": "object", "required": True, "description": "e.g. 2026-27"},
    ],

    "departments": [
        {"name": "department_id", "dtype": "object", "required": True, "unique": True, "auto_id": "D{idx:02d}", "description": "PK, e.g. D01"},
        {"name": "department_name", "dtype": "object", "required": True, "description": "e.g. Computer Science and Engineering"},
    ],

    "programs": [
        {"name": "program_id", "dtype": "object", "required": True, "unique": True, "auto_id": "P{idx:02d}", "description": "PK"},
        {"name": "program_code", "dtype": "object", "required": True, "description": "Short code, e.g. CSE"},
        {"name": "program_name", "dtype": "object", "required": True, "description": "Full name"},
        {"name": "department_id", "dtype": "object", "required": True, "fk": "departments.department_id", "description": "FK → departments"},
        {"name": "degree", "dtype": "object", "required": True, "enum": ["BTech", "MTech", "BSc", "MSc", "BA", "MA", "BBA", "MBA", "PhD", "Diploma"], "allow_custom": True, "description": "Common values shown as dropdown; custom allowed"},
        {"name": "duration_years", "dtype": "int64", "required": True, "min": 1, "max": 6, "description": "Programme length in years"},
    ],

    "academic_terms": [
        {"name": "term_id", "dtype": "object", "required": True, "unique": True, "auto_id": "TERM_{idx}", "description": "PK, e.g. TERM_2026_ODD"},
        {"name": "academic_year", "dtype": "object", "required": True, "description": "e.g. 2026-27"},
        {"name": "term_type", "dtype": "object", "required": True, "enum": ["ODD", "EVEN", "SEMESTER", "ANNUAL"], "description": "Term type"},
        {"name": "start_date", "dtype": "object", "required": True, "format": "date", "description": "YYYY-MM-DD"},
        {"name": "end_date", "dtype": "object", "required": True, "format": "date", "description": "YYYY-MM-DD, must be after start_date"},
    ],

    # Tier 1 core
    "time_slots": [
        {"name": "slot_id", "dtype": "object", "required": True, "unique": True, "pattern": r"^[A-Z]{3}_\d{4}$", "auto_id": "{DAY}_{HHMM}", "description": "PK like MON_0900 (DAY_HHMM)"},
        {"name": "day", "dtype": "object", "required": True, "enum": DAYS, "description": "Teaching day"},
        {"name": "period_number", "dtype": "int64", "required": True, "min": 1, "max": 12, "description": "1..N per day"},
        {"name": "start_time", "dtype": "object", "required": True, "format": "time", "description": "HH:MM 24h"},
        {"name": "end_time", "dtype": "object", "required": True, "format": "time", "description": "HH:MM must be > start_time"},
        {"name": "is_break", "dtype": "bool", "required": True, "description": "True = break period excluded from scheduling"},
    ],

    "sections": [
        {"name": "section_id", "dtype": "object", "required": True, "unique": True, "auto_id": "S_{PROGRAM}_{YEAR}_{NAME}", "description": "PK e.g. S_CSE_1_A"},
        {"name": "program_id", "dtype": "object", "required": True, "fk": "programs.program_id", "description": "FK → programs"},
        {"name": "year", "dtype": "int64", "required": True, "min": 1, "max": 6, "description": "Year of study"},
        {"name": "section_name", "dtype": "object", "required": True, "description": "e.g. A"},
        {"name": "student_count", "dtype": "int64", "required": True, "min": 1, "max": 500, "description": "Enrolled students"},
    ],

    "students": [
        {"name": "student_id", "dtype": "object", "required": True, "unique": True, "auto_id": "STU{idx:04d}", "description": "PK"},
        {"name": "student_name", "dtype": "object", "required": True, "description": "Display name"},
        {"name": "program_id", "dtype": "object", "required": True, "fk": "programs.program_id", "description": "FK → programs"},
        {"name": "branch", "dtype": "object", "required": True, "description": "Branch label, e.g. CSE"},
        {"name": "year", "dtype": "int64", "required": True, "min": 1, "max": 6, "description": "Year of study"},
        {"name": "section_id", "dtype": "object", "required": True, "fk": "sections.section_id", "description": "FK → sections"},
    ],

    "rooms": [
        {"name": "room_id", "dtype": "object", "required": True, "unique": True, "auto_id": "R{idx:03d}", "description": "PK"},
        {"name": "room_name", "dtype": "object", "required": True, "description": "Display name"},
        {"name": "building", "dtype": "object", "required": True, "description": "Drives SC11 building-movement penalty"},
        {"name": "floor", "dtype": "int64", "required": True, "min": 0, "max": 20, "description": "Floor number"},
        {"name": "room_type", "dtype": "object", "required": True, "enum": ["CLASSROOM", "LECTURE_HALL", "COMPUTER_LAB", "ELECTRONICS_LAB", "PHYSICS_LAB", "ROBOTICS_LAB", "WORKSHOP"], "description": "Must match course required_room_type for HC10"},
        {"name": "capacity", "dtype": "int64", "required": True, "min": 1, "max": 1000, "description": ">0"},
        {"name": "has_projector", "dtype": "bool", "required": True, "description": "Equipment flag"},
        {"name": "has_computers", "dtype": "bool", "required": True, "description": "Equipment flag"},
        {"name": "has_ac", "dtype": "bool", "required": True, "description": "Equipment flag"},
        {"name": "equipment", "dtype": "object", "required": False, "description": "Comma-separated vocabulary: PROJECTOR, WHITEBOARD, COMPUTERS, OSCILLOSCOPES, ROBOT_KITS, ELECTRONICS_KITS, PHYSICS_EQUIPMENT, DRAWING_BOARDS, AUDIO_SYSTEM, MICROCONTROLLERS, 3D_PRINTER, GPUS, etc."},
    ],

    "courses": [
        {"name": "course_id", "dtype": "object", "required": True, "unique": True, "auto_id": "C{idx:03d}", "description": "PK"},
        {"name": "course_code", "dtype": "object", "required": True, "unique": True, "description": "Unique code e.g. MAT101"},
        {"name": "course_name", "dtype": "object", "required": True, "description": "Full name"},
        {"name": "department_id", "dtype": "object", "required": True, "fk": "departments.department_id", "description": "FK → departments"},
        {"name": "course_type", "dtype": "object", "required": True, "enum": ["THEORY", "LAB", "WORKSHOP"], "description": "Type"},
        {"name": "course_category", "dtype": "object", "required": True, "enum": ["CORE", "OAE", "PCE", "SKILL", "INTERDISCIPLINARY"], "description": "Category"},
        {"name": "credits", "dtype": "int64", "required": True, "min": 0, "max": 10, "description": "Credits"},
        {"name": "weekly_hours", "dtype": "int64", "required": True, "min": 1, "max": 35, "description": "Should equal sessions_per_week × session_duration"},
        {"name": "sessions_per_week", "dtype": "int64", "required": True, "min": 1, "max": 7, "description": "Number of sessions per week"},
        {"name": "session_duration", "dtype": "int64", "required": True, "enum": [1, 2], "description": "1 or 2 contiguous slots"},
        {"name": "requires_lab", "dtype": "bool", "required": True, "description": "Lab flag"},
        {"name": "required_room_type", "dtype": "object", "required": True, "enum": ["CLASSROOM", "LECTURE_HALL", "COMPUTER_LAB", "ELECTRONICS_LAB", "PHYSICS_LAB", "ROBOTICS_LAB", "WORKSHOP"], "description": "Must have compatible room_type"},
        {"name": "min_room_capacity", "dtype": "int64", "required": True, "min": 1, "max": 1000, "description": "Minimum room capacity"},
        {"name": "equipment_required", "dtype": "object", "required": False, "description": "Comma-separated tokens; synonyms like DATABASE_SYSTEMS→COMPUTERS tolerated on import"},
    ],

    "faculty": [
        {"name": "faculty_id", "dtype": "object", "required": True, "unique": True, "auto_id": "F{idx:03d}", "description": "PK"},
        {"name": "name", "dtype": "object", "required": True, "description": "Display name"},
        {"name": "department_id", "dtype": "object", "required": True, "fk": "departments.department_id", "description": "FK → departments"},
        {"name": "designation", "dtype": "object", "required": True, "enum": ["Professor", "Associate Professor", "Assistant Professor"], "description": "Designation"},
        {"name": "employment_type", "dtype": "object", "required": True, "enum": ["PERMANENT", "ADJUNCT", "VISITING"], "description": "Employment type"},
        {"name": "max_hours_per_week", "dtype": "int64", "required": True, "min": 1, "max": 35, "description": "Weekly cap (≤ 35 teaching slots)"},
        {"name": "max_hours_per_day", "dtype": "int64", "required": True, "min": 1, "max": 12, "description": "Daily cap; ≤ max_hours_per_week"},
        {"name": "min_hours_per_week", "dtype": "int64", "required": True, "min": 0, "max": 35, "description": "≤ max_hours_per_week"},
    ],

    "faculty_courses": [
        {"name": "faculty_id", "dtype": "object", "required": True, "fk": "faculty.faculty_id", "composite_key": True, "description": "FK → faculty"},
        {"name": "course_id", "dtype": "object", "required": True, "fk": "courses.course_id", "composite_key": True, "description": "FK → courses"},
        {"name": "qualification_level", "dtype": "object", "required": True, "enum": ["PRIMARY", "SECONDARY"], "description": "Qualification"},
        {"name": "preferred", "dtype": "bool", "required": True, "description": "Preferred teacher for course (SC01)"},
    ],

    "faculty_availability": [
        {"name": "faculty_id", "dtype": "object", "required": True, "fk": "faculty.faculty_id", "description": "FK → faculty"},
        {"name": "slot_id", "dtype": "object", "required": True, "fk": "time_slots.slot_id", "description": "FK → time_slots"},
        {"name": "available", "dtype": "bool", "required": True, "description": "Available at this slot (HC06)"},
        {"name": "preference_score", "dtype": "int64", "required": True, "min": 0, "max": 5, "description": "0-5 preference (SC01); 0 = neutral"},
    ],

    "room_availability": [
        {"name": "room_id", "dtype": "object", "required": True, "fk": "rooms.room_id", "description": "FK → rooms"},
        {"name": "slot_id", "dtype": "object", "required": True, "fk": "time_slots.slot_id", "description": "FK → time_slots"},
        {"name": "available", "dtype": "bool", "required": True, "description": "Available (HC07)"},
    ],

    "course_offerings": [
        {"name": "offering_id", "dtype": "object", "required": True, "unique": True, "auto_id": "O{idx:04d}", "description": "PK, auto-generated if blank"},
        {"name": "course_id", "dtype": "object", "required": True, "fk": "courses.course_id", "description": "FK → courses"},
        {"name": "section_id", "dtype": "object", "required": True, "fk": "sections.section_id", "description": "FK → sections; (course_id,section_id) must be unique (dedup C#14)"},
        {"name": "required_sessions", "dtype": "int64", "required": True, "min": 1, "max": 7, "description": "Sessions for this offering (defaults to course.sessions_per_week)"},
        {"name": "session_duration", "dtype": "int64", "required": True, "enum": [1, 2], "description": "Defaults to course.session_duration"},
        {"name": "student_count", "dtype": "int64", "required": True, "min": 1, "max": 500, "description": "Enrolled (>0)"},
    ],

    "elective_groups": [
        {"name": "elective_group_id", "dtype": "object", "required": True, "unique": True, "auto_id": "EG{idx:02d}", "description": "PK e.g. EG01"},
        {"name": "group_name", "dtype": "object", "required": True, "description": "Display name"},
        {"name": "elective_type", "dtype": "object", "required": True, "enum": ["OAE", "PCE"], "description": "Open Area / Programme Core Elective"},
        {"name": "year", "dtype": "int64", "required": True, "min": 1, "max": 6, "description": "Year this group applies to"},
        {"name": "program_scope", "dtype": "object", "required": True, "description": "ALL or a program_code (e.g. CSE)"},
        {"name": "minimum_choices", "dtype": "int64", "required": True, "min": 0, "max": 10, "description": "≥0, ≤ maximum_choices"},
        {"name": "maximum_choices", "dtype": "int64", "required": True, "min": 0, "max": 10, "description": "≥ minimum_choices"},
        {"name": "synchronized", "dtype": "bool", "required": True, "description": "True = cross-section shared slot (enables HC13)"},
    ],

    "elective_group_courses": [
        {"name": "elective_group_id", "dtype": "object", "required": True, "fk": "elective_groups.elective_group_id", "description": "FK → elective_groups"},
        {"name": "course_id", "dtype": "object", "required": True, "fk": "courses.course_id", "description": "FK → courses"},
    ],

    "student_enrollments": [
        {"name": "student_id", "dtype": "object", "required": True, "fk": "students.student_id", "description": "FK → students"},
        {"name": "course_id", "dtype": "object", "required": True, "fk": "courses.course_id", "description": "FK → courses"},
        {"name": "enrollment_type", "dtype": "object", "required": True, "enum": ["CORE", "OAE", "PCE"], "description": "Enrollment category"},
    ],

    "fixed_events": [
        {"name": "event_id", "dtype": "object", "required": True, "unique": True, "auto_id": "EV{idx:03d}", "description": "PK"},
        {"name": "event_name", "dtype": "object", "required": True, "description": "Display name"},
        {"name": "day", "dtype": "object", "required": True, "enum": DAYS_PLUS_ALL, "description": "MON..FRI or ALL"},
        {"name": "start_time", "dtype": "object", "required": True, "format": "time", "description": "HH:MM"},
        {"name": "end_time", "dtype": "object", "required": True, "format": "time", "description": "HH:MM must be > start_time"},
        {"name": "scope", "dtype": "object", "required": True, "enum": ["ALL", "ALL_FACULTY"], "description": "ALL = blocks rooms, ALL_FACULTY = blocks faculty"},
    ],

    "academic_rules": [
        {"name": "rule_id", "dtype": "object", "required": True, "unique": True, "auto_id": "R{idx:03d}", "description": "PK"},
        {"name": "rule_name", "dtype": "object", "required": True, "enum": [
            "MAX_DAILY_FACULTY_HOURS", "MAX_WEEKLY_FACULTY_HOURS", "MIN_ROOM_CAPACITY",
            "FACULTY_SIMULTANEOUS_LIMIT", "ROOM_SIMULTANEOUS_LIMIT", "SECTION_SIMULTANEOUS_LIMIT",
            "PREFER_FACULTY_PREFERRED_SLOTS", "MINIMIZE_STUDENT_GAPS", "MINIMIZE_ROOM_WASTAGE",
        ], "allow_custom": True, "description": "Known rules shown as dropdown; custom names allowed"},
        {"name": "rule_type", "dtype": "object", "required": True, "enum": ["HARD", "SOFT"], "description": "HARD or SOFT"},
        {"name": "value", "dtype": "object", "required": True, "description": "Rule value (stringified int/enum)"},
        {"name": "active", "dtype": "bool", "required": True, "description": "Whether rule is active"},
    ],
}

# ---------------------------------------------------------------------------
# Legacy alias: keep adapter.CANONICAL import working if external code imports
# from sih_solver.schema — expose CANONICAL as the ordered field-name lists.
# ---------------------------------------------------------------------------
CANONICAL: Dict[str, List[str]] = {k: [f["name"] for f in fields] for k, fields in SCHEMAS.items()}

# Example row values (used by template_csv)
EXAMPLES: Dict[str, Dict[str, str]] = {
    "universities": {"university_id": "U001", "university_name": "Synthetic Institute of Technology", "campus": "Main Campus", "academic_year": "2026-27"},
    "departments": {"department_id": "D01", "department_name": "Computer Science and Engineering"},
    "programs": {"program_id": "P01", "program_code": "CSE", "program_name": "Computer Science and Engineering", "department_id": "D01", "degree": "BTech", "duration_years": "4"},
    "academic_terms": {"term_id": "TERM_2026_ODD", "academic_year": "2026-27", "term_type": "ODD", "start_date": "2026-08-01", "end_date": "2026-12-20"},
    "time_slots": {"slot_id": "MON_0900", "day": "MON", "period_number": "1", "start_time": "09:00", "end_time": "10:00", "is_break": "False"},
    "sections": {"section_id": "S_CSE_1_A", "program_id": "P01", "year": "1", "section_name": "A", "student_count": "65"},
    "students": {"student_id": "STU0001", "student_name": "Student 0001", "program_id": "P01", "branch": "CSE", "year": "1", "section_id": "S_CSE_1_A"},
    "rooms": {"room_id": "R001", "room_name": "Classroom-01", "building": "A", "floor": "1", "room_type": "CLASSROOM", "capacity": "70", "has_projector": "True", "has_computers": "False", "has_ac": "True", "equipment": "PROJECTOR,WHITEBOARD"},
    "courses": {"course_id": "C001", "course_code": "MAT101", "course_name": "Engineering Mathematics I", "department_id": "D01", "course_type": "THEORY", "course_category": "CORE", "credits": "4", "weekly_hours": "4", "sessions_per_week": "4", "session_duration": "1", "requires_lab": "False", "required_room_type": "CLASSROOM", "min_room_capacity": "50", "equipment_required": ""},
    "faculty": {"faculty_id": "F001", "name": "Prof. Aarav Sharma", "department_id": "D01", "designation": "Professor", "employment_type": "PERMANENT", "max_hours_per_week": "18", "max_hours_per_day": "4", "min_hours_per_week": "8"},
    "faculty_courses": {"faculty_id": "F001", "course_id": "C001", "qualification_level": "PRIMARY", "preferred": "True"},
    "faculty_availability": {"faculty_id": "F001", "slot_id": "MON_0900", "available": "True", "preference_score": "3"},
    "room_availability": {"room_id": "R001", "slot_id": "MON_0900", "available": "True"},
    "course_offerings": {"offering_id": "O0001", "course_id": "C001", "section_id": "S_CSE_1_A", "required_sessions": "4", "session_duration": "1", "student_count": "65"},
    "elective_groups": {"elective_group_id": "EG01", "group_name": "Year 3 Open Area Electives", "elective_type": "OAE", "year": "3", "program_scope": "ALL", "minimum_choices": "1", "maximum_choices": "1", "synchronized": "True"},
    "elective_group_courses": {"elective_group_id": "EG01", "course_id": "C001"},
    "student_enrollments": {"student_id": "STU0001", "course_id": "C001", "enrollment_type": "CORE"},
    "fixed_events": {"event_id": "EV001", "event_name": "Weekly Faculty Meeting", "day": "MON", "start_time": "12:00", "end_time": "13:00", "scope": "ALL_FACULTY"},
    "academic_rules": {"rule_id": "R001", "rule_name": "MAX_DAILY_FACULTY_HOURS", "rule_type": "HARD", "value": "4", "active": "true"},
}

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def list_datasets() -> List[str]:
    return list(SCHEMAS.keys())

def get_schema(dataset: str) -> List[Dict[str, Any]]:
    if dataset not in SCHEMAS:
        raise KeyError(f"Unknown dataset '{dataset}'. Known: {sorted(SCHEMAS.keys())}")
    return SCHEMAS[dataset]

def get_field(dataset: str, field_name: str) -> Dict[str, Any]:
    for f in get_schema(dataset):
        if f["name"] == field_name:
            return f
    raise KeyError(f"Field '{field_name}' not in dataset '{dataset}'")

# ---------------------------------------------------------------------------
# L1 validation — per-dataset, per-row type/enum/required/range/format checks
# ---------------------------------------------------------------------------

def _add_issue(issues: List[Dict[str, Any]], dataset: str, row: int, field: str, message: str, fix_hint: str = ""):
    issues.append({
        "dataset": dataset,
        "row": row,            # 1-indexed data row (header is 0); 0 = header/structural
        "field": field,
        "message": message,
        "fix_hint": fix_hint,
        "severity": "BLOCKER",
    })

def validate_rows(dataset: str, rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """L1 checks only (no cross-dataset FKs).

    `rows` is a list of dicts with string values (as read from CSV; empty string means blank cell).
    Row numbers reported are 1-indexed data rows (first data row = 1, header not counted).

    Returns list of issues; empty = pass.
    """
    if dataset not in SCHEMAS:
        return [{"dataset": dataset, "row": 0, "field": "", "message": f"Unknown dataset '{dataset}'", "fix_hint": f"Choose one of: {', '.join(sorted(SCHEMAS.keys()))}", "severity": "BLOCKER"}]
    fields = SCHEMAS[dataset]
    by_name = {f["name"]: f for f in fields}
    issues: List[Dict[str, Any]] = []

    # Structural: column presence — caller may have already mapped headers; warn on extra columns
    # Here we only check that every required field is at least present as column (value may be blank -> per-row check)
    # If rows is empty, we don't enforce here (Phase B will flag missing mandatory file).
    if not rows:
        return issues

    header = set(rows[0].keys())
    for f in fields:
        if f["required"] and f["name"] not in header:
            _add_issue(issues, dataset, 0, f["name"],
                       f"Missing required column '{f['name']}'",
                       f"Add column with header '{f['name']}'")
    # Unknown extra columns are warnings-like but L1 treats them as ignored (import tolerates)
    # Don't flag as BLOCKER — just structural helper for the UI's import dialog elsewhere.

    # Per-row checks
    seen_unique: Dict[str, set] = {}  # field -> set(values)
    for f in fields:
        if f.get("unique"):
            seen_unique[f["name"]] = set()

    for idx, row in enumerate(rows, start=1):
        # Also handle rows that are dict but may have None values (csv quirk)
        for f in fields:
            fname = f["name"]
            raw = row.get(fname)
            sval = "" if raw is None else str(raw).strip()
            required = f["required"]

            # Required + blank
            if required and sval == "":
                _add_issue(issues, dataset, idx, fname,
                           f"Required field '{fname}' is empty",
                           "Fill a valid value")
                continue
            # Optional blank → skip further checks for this field
            if sval == "":
                continue

            dtype = f["dtype"]

            # Type checks
            if dtype == "int64":
                if not _is_int_str(sval):
                    _add_issue(issues, dataset, idx, fname,
                               f"Expected integer, got '{sval}'",
                               "Use a whole number like 4")
                    continue
                ival = _parse_int(sval)
                if f.get("min") is not None and ival < f["min"]:
                    _add_issue(issues, dataset, idx, fname,
                               f"Value {ival} is below minimum {f['min']}",
                               f"Use a value >= {f['min']}")
                if f.get("max") is not None and ival > f["max"]:
                    _add_issue(issues, dataset, idx, fname,
                               f"Value {ival} exceeds maximum {f['max']}",
                               f"Use a value <= {f['max']}")
                # Enum for ints (e.g. session_duration 1|2)
                if "enum" in f and ival not in f["enum"]:
                    _add_issue(issues, dataset, idx, fname,
                               f"Value {ival} not in allowed {f['enum']}",
                               f"Choose one of: {', '.join(map(str, f['enum']))}")

            elif dtype == "bool":
                if not _is_bool_str(sval):
                    _add_issue(issues, dataset, idx, fname,
                               f"Expected boolean, got '{sval}'",
                               "Use True or False")
                # enum constraint on bools is rare; skip

            elif dtype == "object":
                # Enum for strings
                if "enum" in f and not f.get("allow_custom"):
                    if sval not in f["enum"]:
                        _add_issue(issues, dataset, idx, fname,
                                   f"Value '{sval}' not in allowed {f['enum']}",
                                   f"Choose one of: {', '.join(map(str, f['enum']))}")
                # Pattern
                if "pattern" in f:
                    if not re.match(f["pattern"], sval):
                        _add_issue(issues, dataset, idx, fname,
                                   f"Value '{sval}' doesn't match pattern {f['pattern']}",
                                   "Fix the format")
                # Format helpers
                fmt = f.get("format")
                if fmt == "time" and not _TIME_RE.match(sval):
                    _add_issue(issues, dataset, idx, fname,
                               f"Expected HH:MM (24h), got '{sval}'",
                               "Use format 09:00")
                elif fmt == "date" and not _DATE_RE.match(sval):
                    _add_issue(issues, dataset, idx, fname,
                               f"Expected YYYY-MM-DD, got '{sval}'",
                               "Use format 2026-08-01")
                # unique check deferred after type pass
            else:
                # unknown dtype — treat as object
                pass

            # Uniqueness within dataset (collect and check after row loop for clearer message;
            # but we also flag on second occurrence inline)
            if f.get("unique") and sval != "":
                s = seen_unique.get(fname)
                if s is not None:
                    if sval in s:
                        _add_issue(issues, dataset, idx, fname,
                                   f"Duplicate value '{sval}' — {fname} must be unique",
                                   "Use a unique ID")
                    else:
                        s.add(sval)

        # Cross-field row rules
        # time_slots: end_time > start_time
        if dataset == "time_slots":
            st = str(row.get("start_time", "")).strip()
            et = str(row.get("end_time", "")).strip()
            if _TIME_RE.match(st) and _TIME_RE.match(et) and st >= et:
                _add_issue(issues, dataset, idx, "end_time",
                           f"end_time ({et}) must be after start_time ({st})",
                           "Fix times so end > start")
        if dataset == "academic_terms":
            sd = str(row.get("start_date", "")).strip()
            ed = str(row.get("end_date", "")).strip()
            if _DATE_RE.match(sd) and _DATE_RE.match(ed) and sd >= ed:
                _add_issue(issues, dataset, idx, "end_date",
                           f"end_date ({ed}) must be after start_date ({sd})",
                           "Fix dates so end > start")
        if dataset == "fixed_events":
            st = str(row.get("start_time", "")).strip()
            et = str(row.get("end_time", "")).strip()
            if _TIME_RE.match(st) and _TIME_RE.match(et) and st >= et:
                _add_issue(issues, dataset, idx, "end_time",
                           f"end_time ({et}) must be after start_time ({st})",
                           "Fix times so end > start")
        if dataset == "elective_groups":
            mn = str(row.get("minimum_choices", "")).strip()
            mx = str(row.get("maximum_choices", "")).strip()
            if _is_int_str(mn) and _is_int_str(mx) and _parse_int(mn) > _parse_int(mx):
                _add_issue(issues, dataset, idx, "maximum_choices",
                           f"maximum_choices ({mx}) < minimum_choices ({mn})",
                           "Maximum must be >= minimum")
        if dataset == "faculty":
            mx_w = str(row.get("max_hours_per_week", "")).strip()
            mx_d = str(row.get("max_hours_per_day", "")).strip()
            mn_w = str(row.get("min_hours_per_week", "")).strip()
            if _is_int_str(mx_w) and _is_int_str(mx_d) and _parse_int(mx_d) > _parse_int(mx_w):
                _add_issue(issues, dataset, idx, "max_hours_per_day",
                           f"max_hours_per_day ({mx_d}) exceeds max_hours_per_week ({mx_w})",
                           "Daily cap cannot exceed weekly cap")
            if _is_int_str(mx_w) and _is_int_str(mn_w) and _parse_int(mn_w) > _parse_int(mx_w):
                _add_issue(issues, dataset, idx, "min_hours_per_week",
                           f"min_hours_per_week ({mn_w}) exceeds max_hours_per_week ({mx_w})",
                           "Min cannot exceed max")
        if dataset == "courses":
            wh = str(row.get("weekly_hours", "")).strip()
            spw = str(row.get("sessions_per_week", "")).strip()
            sd = str(row.get("session_duration", "")).strip()
            if _is_int_str(wh) and _is_int_str(spw) and _is_int_str(sd):
                if _parse_int(spw) * _parse_int(sd) != _parse_int(wh):
                    _add_issue(issues, dataset, idx, "weekly_hours",
                               f"weekly_hours ({wh}) != sessions_per_week ({spw}) × session_duration ({sd})",
                               "Fix so weekly_hours equals sessions × duration")
                if _parse_int(spw) < 1 or _parse_int(sd) not in (1, 2):
                    pass  # already flagged via type/enum above

    # Composite uniqueness for faculty_courses and elective_group_courses and student_enrollments ?
    # For now only field-level unique as defined above; composite dedup is L2/L3 and import will surface as duplicate-row warning.
    # But faculty_courses composite pair duplicate is a meaningful blocker:
    if dataset in ("faculty_courses", "elective_group_courses", "student_enrollments"):
        seen_pairs = set()
        for idx, row in enumerate(rows, start=1):
            if dataset == "faculty_courses":
                pair = (str(row.get("faculty_id", "")).strip(), str(row.get("course_id", "")).strip())
            elif dataset == "elective_group_courses":
                pair = (str(row.get("elective_group_id", "")).strip(), str(row.get("course_id", "")).strip())
            else:
                pair = (str(row.get("student_id", "")).strip(), str(row.get("course_id", "")).strip())
            if pair[0] == "" or pair[1] == "":
                continue
            if pair in seen_pairs:
                _add_issue(issues, dataset, idx, pair[0],
                           f"Duplicate row for pair {pair}",
                           "Remove the duplicate")
            else:
                seen_pairs.add(pair)

    # Offering uniqueness on (course_id, section_id) is a known dedup rule (C#14); treat second occurrence as BLOCKER
    if dataset == "course_offerings":
        seen_combo = set()
        for idx, row in enumerate(rows, start=1):
            c = str(row.get("course_id", "")).strip()
            s = str(row.get("section_id", "")).strip()
            if c == "" or s == "":
                continue
            key = (c, s)
            if key in seen_combo:
                _add_issue(issues, dataset, idx, "course_id",
                           f"Duplicate offering for (course_id, section_id)=({c},{s}) — must be unique",
                           "Remove duplicate or change course/section")
            else:
                seen_combo.add(key)

    return issues


def validate_file(path: str, dataset: str | None = None) -> List[Dict[str, Any]]:
    """Convenience: read a CSV file and validate it. If dataset is None, infer from filename."""
    import pathlib as _pl
    p = _pl.Path(path)
    if dataset is None:
        dataset = p.stem  # e.g. courses.csv -> courses
    with open(p, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return validate_rows(dataset, rows)


# ---------------------------------------------------------------------------
# Template generation — ALL canonical columns + 1 example row
# ---------------------------------------------------------------------------

def template_rows(dataset: str, include_example: bool = True) -> List[Dict[str, str]]:
    """Return list of dicts suitable for csv.DictWriter: optional example row."""
    fields = get_schema(dataset)
    header = [f["name"] for f in fields]
    if not include_example:
        return []
    ex = EXAMPLES.get(dataset, {})
    row = {h: ex.get(h, "") for h in header}
    return [row]

def template_csv(dataset: str, include_example: bool = True) -> str:
    """Return CSV string for the dataset's template (header + example row).

    Used by GET /api/templates/{dataset}.
    If include_example is False, returns header-only CSV (for empty import seed).
    """
    fields = get_schema(dataset)
    header = [f["name"] for f in fields]
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=header, lineterminator="\n")
    w.writeheader()
    if include_example:
        ex = EXAMPLES.get(dataset, {})
        w.writerow({h: ex.get(h, "") for h in header})
    return out.getvalue()

def write_template_file(dataset: str, dest_path: str, include_example: bool = True) -> str:
    """Write template CSV to dest_path; returns the path."""
    import pathlib as _pl
    _pl.Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "w", newline="", encoding="utf-8") as f:
        f.write(template_csv(dataset, include_example=include_example))
    return dest_path

def required_datasets() -> List[str]:
    """Datasets that must be present for solving (hard gate).

    Includes `departments` and `programs` even though no HC/SC reads them directly —
    `faculty.department_id`, `courses.department_id`, and `sections.program_id` are FK
    fields that always resolve against them once faculty/courses/sections have any rows
    (which they must, being required themselves), so leaving them out of this list let
    validate_all() report can_solve=True on a store that L2 would still reject. Verified
    empirically: the 7-dataset set alone reproducibly leaves 3 FK BLOCKERs unresolved.
    """
    return ["time_slots", "rooms", "faculty", "courses", "faculty_courses", "course_offerings",
            "sections", "departments", "programs"]

def optional_datasets() -> List[str]:
    return ["faculty_availability", "room_availability", "students", "student_enrollments",
            "elective_groups", "elective_group_courses", "fixed_events",
            "universities", "academic_terms", "academic_rules"]

# Back-compat alias used by older tests/docs
DATASETS = SCHEMAS

if __name__ == "__main__":
    # Quick sanity: validate the repo's own CSVs
    import pathlib as _pl
    root = _pl.Path(__file__).parent.parent
    for ds in required_datasets() + ["faculty_availability", "room_availability", "fixed_events", "elective_groups"]:
        path = root / f"{ds}.csv"
        if path.exists():
            issues = validate_file(str(path), ds)
            print(f"{ds}: {len(issues)} issues")
            for iss in issues[:3]:
                print(" ", iss)
