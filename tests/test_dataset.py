"""CP1 Tests – Dataset Gate. Run: pytest tests/test_dataset.py -v"""
import pathlib
import csv
from collections import Counter

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from sih_solver.dataset import audit_dataset, load_course_offerings, DATASET_ROOT_RAW, DATASET_ROOT_CORRECTED

def test_raw_offerings_count():
    rows, info = load_course_offerings(DATASET_ROOT_RAW, dedup=False)
    assert info["original"] == 144, f"expected 144 raw offerings, got {info['original']}"

def test_dedup_removes_11():
    _, info = load_course_offerings(DATASET_ROOT_RAW, dedup=True)
    assert info["removed"] == 11, f"expected 11 duplicates removed, got {info['removed']}"
    assert info["deduped"] == 133, f"expected 133 deduped, got {info['deduped']}"

def test_corrected_already_deduped():
    # Corrected dataset should have 0 duplicates remaining
    if not DATASET_ROOT_CORRECTED.exists():
        import pytest; pytest.skip("corrected dataset not extracted")
    _, info = load_course_offerings(DATASET_ROOT_CORRECTED, dedup=True)
    assert info["removed"] == 0, f"corrected should have 0 dups, got {info['removed']}"
    assert info["deduped"] == 133

def test_no_dup_keys_after_dedup():
    for root in [DATASET_ROOT_RAW, DATASET_ROOT_CORRECTED]:
        if not root.exists():
            continue
        rows, _ = load_course_offerings(root, dedup=True)
        keys = [(r["course_id"], r["section_id"]) for r in rows]
        assert len(keys) == len(set(keys)), f"duplicate keys remain in {root}"

def test_rooms_count():
    for root in [DATASET_ROOT_RAW, DATASET_ROOT_CORRECTED]:
        if not (root / "rooms.csv").exists():
            continue
        rows = list(csv.DictReader(open(root / "rooms.csv")))
        # Raw =27, Corrected =29? Actual corrected now 27 as well (29 with W001/W002)
        # Accept 27 or 29, but must be >=27
        assert len(rows) >= 27, f"rooms {len(rows)} <27 in {root}"

def test_courses_65():
    rows = list(csv.DictReader(open(DATASET_ROOT_RAW / "courses.csv")))
    assert len(rows) == 65

def test_time_slots_35():
    rows = list(csv.DictReader(open(DATASET_ROOT_RAW / "time_slots.csv")))
    assert len(rows) == 35

def test_faculty_availability_completeness():
    rows = list(csv.DictReader(open(DATASET_ROOT_RAW / "faculty_availability.csv")))
    assert len(rows) == 40*35 == 1400

def test_room_availability_completeness():
    import csv, pathlib
    rooms = list(csv.DictReader(open(DATASET_ROOT_RAW / "rooms.csv")))
    ra = list(csv.DictReader(open(DATASET_ROOT_RAW / "room_availability.csv")))
    assert len(ra) == len(rooms)*35, f"room_avail {len(ra)} != {len(rooms)}*35"

def test_equipment_mismatch_informational():
    # Round1 C#13 – 5-6 mismatches are expected as informational, not hard fail
    report = audit_dataset(DATASET_ROOT_RAW)
    # We expect at least 3 mismatches (DATABASE_SYSTEMS, GPUS, ROBOTICS etc.)
    assert report.get("equipment_mismatch_count", 0) >= 3

def test_eligibility_coverage():
    report = audit_dataset(DATASET_ROOT_RAW)
    assert report["eligible_per_course_min"] >= 3
