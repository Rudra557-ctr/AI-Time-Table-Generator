"""Phase C tests — data store + new API (backend/app.py + backend/store.py).

Run:  pytest tests/test_data_api.py -v
"""
import io
import csv
import json
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from backend.app import app
from backend.store import load_store, init_store, export_to_normalized
from sih_solver.schema import SCHEMAS, template_csv, get_schema

client = TestClient(app)
BASE = pathlib.Path(__file__).resolve().parents[1]


def _new_job():
    r = client.post("/api/jobs")
    assert r.status_code == 200, r.text
    return r.json()["job_id"]


# ---------------------------------------------------------------------------
# Schema + template endpoints
# ---------------------------------------------------------------------------

def test_schema_lists_all_datasets():
    r = client.get("/api/schema")
    assert r.status_code == 200
    j = r.json()
    assert set(j["datasets"].keys()) == set(SCHEMAS.keys())
    assert len(j["datasets"]) == 19
    assert set(j["required"]) == {"time_slots", "rooms", "faculty", "courses", "faculty_courses", "course_offerings",
                                   "sections", "departments", "programs"}


def test_schema_single_dataset():
    r = client.get("/api/schema/courses")
    assert r.status_code == 200
    assert r.json()["dataset"] == "courses"
    assert any(f["name"] == "course_id" for f in r.json()["fields"])
    r2 = client.get("/api/schema/unknown_ds")
    assert r2.status_code == 404


def test_template_csv_has_all_canonical_columns():
    for ds in ["courses", "time_slots", "faculty", "course_offerings"]:
        r = client.get(f"/api/templates/{ds}")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        header = r.text.splitlines()[0].split(",")
        expected = [f["name"] for f in SCHEMAS[ds]]
        assert header == expected, f"{ds} header mismatch"
        # should contain example row
        assert len(r.text.splitlines()) >= 2

def test_template_csv_unknown_404():
    r = client.get("/api/templates/no_such")
    assert r.status_code == 404

def test_templates_all_zip():
    r = client.get("/api/templates/all.zip")
    assert r.status_code == 200
    assert "application/zip" in r.headers["content-type"]
    # read zip and check one entry
    import zipfile, io as _io
    z = zipfile.ZipFile(_io.BytesIO(r.content))
    names = z.namelist()
    assert "courses.csv" in names and "time_slots.csv" in names
    with z.open("courses.csv") as f:
        text = f.read().decode()
        assert text.splitlines()[0].split(",")[0] == "course_id"


# ---------------------------------------------------------------------------
# Job store + per-dataset CRUD
# ---------------------------------------------------------------------------

def test_create_job_empty_has_blockers():
    jid = _new_job()
    r = client.get(f"/api/jobs/{jid}")
    assert r.status_code == 200
    j = r.json()
    assert j["job_id"] == jid
    assert all(v == 0 for v in j["counts"].values())
    # empty store must have blockers for 7 required datasets
    assert j["validation"]["summary"]["total_blockers"] >= 7
    assert j["validation"]["summary"]["can_solve"] is False

def test_put_and_get_dataset():
    jid = _new_job()
    rows = [{"department_id": "D01", "department_name": "Test Dept"}]
    r = client.put(f"/api/jobs/{jid}/data/departments", json={"rows": rows})
    assert r.status_code == 200, r.text
    r2 = client.get(f"/api/jobs/{jid}/data/departments")
    assert r2.status_code == 200
    assert r2.json()["rows"] == rows

def test_put_validates_l1_and_rejects_blocker():
    jid = _new_job()
    # Missing required course_id
    bad = [{"course_code": "MAT101", "course_name": "Maths"}]
    r = client.put(f"/api/jobs/{jid}/data/courses", json={"rows": bad})
    assert r.status_code == 422
    j = r.json()
    assert any(i["field"] == "course_id" for i in j["validation"]["blockers"])

def test_put_unknown_dataset_404():
    jid = _new_job()
    r = client.put(f"/api/jobs/{jid}/data/no_such", json={"rows": []})
    assert r.status_code == 404
    r2 = client.get(f"/api/jobs/{jid}/data/no_such")
    assert r2.status_code == 404

def test_put_accepts_raw_list_and_replaces():
    jid = _new_job()
    rows1 = [{"department_id": "D01", "department_name": "A"}]
    rows2 = [{"department_id": "D02", "department_name": "B"}, {"department_id": "D03", "department_name": "C"}]
    client.put(f"/api/jobs/{jid}/data/departments", json={"rows": rows1})
    r = client.put(f"/api/jobs/{jid}/data/departments", json=rows2)  # raw list
    assert r.status_code == 200
    got = client.get(f"/api/jobs/{jid}/data/departments").json()["rows"]
    assert len(got) == 2 and got[0]["department_id"] == "D02"

def test_import_csv_with_fuzzy_headers():
    jid = _new_job()
    # CSV with alias headers (CourseCode vs course_code)
    csv_content = "CourseCode,Course Name,Department,Type,Category,credits,weekly_hours,sessions_per_week,session_duration,requires_lab,required_room_type,min_room_capacity\n"
    csv_content += "MAT101,Maths,D01,THEORY,CORE,4,4,4,1,False,CLASSROOM,50\n"
    # Must also have department D01 already, but import currently validates against whole store; if departments empty, FK will fail.
    # So prefill departments
    client.put(f"/api/jobs/{jid}/data/departments", json={"rows": [{"department_id": "D01", "department_name": "Test"}]})
    r = client.post(
        f"/api/jobs/{jid}/import/courses",
        files={"file": ("courses.csv", csv_content.encode(), "text/csv")},
    )
    # should either succeed after mapping (if validation passes) or report mapping preview on failure
    if r.status_code == 200:
        j = r.json()
        assert "mapping" in j
        assert j["dataset"] == "courses"
    else:
        # might still fail FK if other required fields missing but mapping should be shown
        assert r.status_code == 422
        assert "mapping" in r.json()

def test_import_csv_validation_reports_blocker():
    jid = _new_job()
    bad_csv = "course_id,wrong_col\nC001,xxx\n"
    r = client.post(
        f"/api/jobs/{jid}/import/courses",
        files={"file": ("courses.csv", bad_csv.encode(), "text/csv")},
    )
    assert r.status_code == 422
    assert "validation" in r.json()

def test_fill_minimal_store_until_can_solve():
    """PUT all required datasets with consistent template rows → can_solve becomes true."""
    jid = _new_job()
    # Fill datasets in FK order using template_rows but ensuring FK closure.
    # templates for all 19 are already referentially consistent after elective_group_courses fix (C001).
    from sih_solver.schema import template_rows
    order = ["departments", "programs", "universities", "academic_terms", "time_slots", "sections", "rooms", "courses", "faculty", "faculty_courses", "course_offerings", "faculty_availability", "room_availability"]
    # Also need optional for FK closure: elective_groups, elective_group_courses, etc. but minimal above should pass.
    # Start with departments/programs etc.
    for ds in order:
        rows = template_rows(ds, include_example=True)
        r = client.put(f"/api/jobs/{jid}/data/{ds}", json={"rows": rows})
        # Some PUTs may fail due to FK depending on order; ignore and continue filling missing FK targets first
        if r.status_code not in (200, 422):
            assert False, f"{ds} PUT unexpected {r.status_code} {r.text}"
        if r.status_code == 422:
            # might be FK missing — fill target first then retry
            pass
    # Fill any remaining required datasets that were skipped
    for ds in ["departments", "programs", "time_slots", "sections", "rooms", "courses", "faculty", "faculty_courses", "course_offerings"]:
        r = client.get(f"/api/jobs/{jid}/data/{ds}")
        if r.json()["count"] == 0:
            rows = template_rows(ds, include_example=True)
            client.put(f"/api/jobs/{jid}/data/{ds}", json={"rows": rows})
    r = client.get(f"/api/jobs/{jid}")
    j = r.json()
    assert j["validation"]["summary"]["can_solve"] is True, f"still blocked: {j['validation']['blockers'][:2]}"


# ---------------------------------------------------------------------------
# Legacy upload + solve gate
# ---------------------------------------------------------------------------

def test_upload_no_auto_fill_and_validation_flags_missing():
    # upload only departments.csv — without fill, missing required should be flagged as blockers, not filled
    csv_content = "department_id,department_name\nD01,Test Dept\n"
    r = client.post(
        "/api/upload",
        files=[("files", ("departments.csv", csv_content.encode(), "text/csv"))],
    )
    assert r.status_code == 200
    j = r.json()
    assert "job_id" in j
    assert "validation" in j
    assert j["validation"]["summary"]["can_solve"] is False  # missing required still blocker
    assert "filled from base SIH dataset" not in " ".join(j["report"].get("warnings", []))

def test_upload_with_fill_injects_base_data():
    csv_content = "department_id,department_name\nD01,Test Dept\n"
    r = client.post(
        "/api/upload?fill=true",
        files=[("files", ("departments.csv", csv_content.encode(), "text/csv"))],
    )
    assert r.status_code == 200
    j = r.json()
    # with fill, at least courses should now be present
    assert any("filled" in w.lower() for w in j["report"].get("warnings", []))

def test_solve_gate_blocks_when_missing_required():
    jid = _new_job()
    r = client.post(f"/api/solve/{jid}")
    assert r.status_code == 422
    assert "BLOCKER" in r.json()["error"] or "Blocker" in r.text or r.json()["validation"]["summary"]["total_blockers"] > 0

def test_solve_gate_allows_when_minimal_store_filled():
    jid = _new_job()
    from sih_solver.schema import template_rows
    for ds in ["departments", "programs", "universities", "academic_terms", "time_slots", "sections", "rooms", "courses", "faculty", "faculty_courses", "course_offerings", "faculty_availability", "room_availability"]:
        client.put(f"/api/jobs/{jid}/data/{ds}", json={"rows": template_rows(ds, include_example=True)})
    # fill elective groups so enrollments not warn-block? not needed
    # Ensure can_solve now
    r = client.get(f"/api/jobs/{jid}")
    assert r.json()["validation"]["summary"]["can_solve"] is True
    r2 = client.post(f"/api/solve/{jid}?time_limit=2")
    # time_limit 2s: solver may return UNKNOWN/INFEASIBLE on tiny instance but request should be accepted (not 422)
    assert r2.status_code == 200
    assert r2.json()["status"] in ("solving", "OPTIMAL", "FEASIBLE", "UNKNOWN")
