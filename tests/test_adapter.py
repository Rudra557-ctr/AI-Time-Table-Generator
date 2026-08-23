import pathlib
import tempfile

from sih_solver.adapter import normalize_upload_folder


def _make_upload_dir_with_only_courses():
    upload_dir = pathlib.Path(tempfile.mkdtemp())
    (upload_dir / "courses.csv").write_text(
        "course_id,course_code,course_name,department_id,course_type,course_category,"
        "credits,weekly_hours,sessions_per_week,session_duration,requires_lab,"
        "required_room_type,min_room_capacity,equipment_required\n"
        "C001,CS101,Intro,D01,CORE,CORE,3,3,1,1,False,CLASSROOM,30,\n"
    )
    return upload_dir


def test_missing_required_file_not_filled_by_default():
    upload_dir = _make_upload_dir_with_only_courses()
    normalized_dir = pathlib.Path(tempfile.mkdtemp())

    report = normalize_upload_folder(upload_dir, normalized_dir)

    assert not (normalized_dir / "rooms.csv").exists()
    assert not (normalized_dir / "faculty.csv").exists()
    assert any("rooms.csv" in w and "required dataset not uploaded" in w for w in report["warnings"])
    assert not any("filled from base SIH dataset" in w for w in report["warnings"])


def test_missing_required_file_filled_when_opted_in():
    upload_dir = _make_upload_dir_with_only_courses()
    normalized_dir = pathlib.Path(tempfile.mkdtemp())

    report = normalize_upload_folder(upload_dir, normalized_dir, fill_missing=True)

    assert (normalized_dir / "rooms.csv").exists()
    assert any("rooms.csv" in w and "filled from base SIH dataset" in w for w in report["warnings"])
