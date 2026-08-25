"""CP1 Dataset Gate – load, audit, correct.

Handles both raw sih/*.csv and corrected sih_timetable_dataset_corrected/*.csv.
Applies Round1 Part C fixes:
  - C#14 dedup course_offerings on (course_id, section_id) keeping first
  - C#13 equipment vocabulary fallback documented (not filtered here, handled in preprocessing)
"""
import csv
import pathlib
from collections import Counter, defaultdict
from .preprocessing import EQUIPMENT_SYNONYMS

DATASET_ROOT_RAW = pathlib.Path(__file__).resolve().parent.parent
DATASET_ROOT_CORRECTED = pathlib.Path("/tmp/sih_timetable_dataset_corrected")

# Also support the extracted corrected folder as alternative
if not DATASET_ROOT_CORRECTED.exists():
    DATASET_ROOT_CORRECTED = DATASET_ROOT_RAW / "sih_timetable_dataset_corrected"

def _read_csv(path: pathlib.Path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def load_course_offerings(root: pathlib.Path = DATASET_ROOT_RAW, dedup: bool = True):
    rows = _read_csv(root / "course_offerings.csv")
    original = len(rows)
    if not dedup:
        return rows, {"original": original, "deduped": original, "removed": 0, "duplicates": []}
    seen = set()
    deduped = []
    dups = []
    for r in rows:
        # Richer key — see preprocessing.py dedup comment: preserves intentional
        # lab A/B parallel splits (different student_count) while still
        # collapsing the 11 exact duplicates in the original SIH dataset.
        key = (r["course_id"], r["section_id"], r.get("required_sessions"), r.get("session_duration"), r.get("student_count"))
        if key in seen:
            dups.append(r)
            continue
        seen.add(key)
        deduped.append(r)
    return deduped, {"original": original, "deduped": len(deduped), "removed": len(dups), "duplicates": dups}

def audit_dataset(root: pathlib.Path = DATASET_ROOT_RAW):
    """Run Round1 Part C checks (subset for CP1). Returns dict."""
    report = {}
    # 1 counts
    for fname in ["students.csv","faculty.csv","sections.csv","courses.csv","course_offerings.csv","rooms.csv","time_slots.csv"]:
        try:
            rows = _read_csv(root / fname)
            report[fname] = len(rows)
        except FileNotFoundError:
            report[fname] = None
    # dedup
    _, info = load_course_offerings(root, dedup=True)
    report["course_offerings_original"] = info["original"]
    report["course_offerings_deduped"] = info["deduped"]
    report["course_offerings_dup_removed"] = info["removed"]
    # rooms vs validation_summary
    try:
        vs = _read_csv(root / "validation_summary.csv")
        report["validation_summary"] = vs[0] if vs else {}
    except:
        report["validation_summary"] = {}
    # equipment mismatch check (Round1 C#13) – informational
    try:
        courses = _read_csv(root / "courses.csv")
        rooms = _read_csv(root / "rooms.csv")
        room_equips = set()
        for r in rooms:
            for e in r["equipment"].split(","):
                e=e.strip()
                if e: room_equips.add(e)
        mism = []
        for c in courses:
            req = c["equipment_required"].strip()
            if req and req not in room_equips:
                # equipment_required may be comma list; check each token
                tokens = [t.strip() for t in req.split(",") if t.strip()]
                missing = [t for t in tokens if t not in room_equips and t not in EQUIPMENT_SYNONYMS]
                if missing:
                    mism.append((c["course_id"], req, missing))
        report["equipment_mismatch"] = mism
        report["equipment_mismatch_count"] = len(mism)
    except Exception as e:
        report["equipment_mismatch_error"] = str(e)
    # faculty_courses eligibility
    try:
        fc = _read_csv(root / "faculty_courses.csv")
        report["faculty_courses_rows"] = len(fc)
        per_course = Counter(r["course_id"] for r in fc)
        report["eligible_per_course_min"] = min(per_course.values()) if per_course else 0
        report["eligible_per_course_max"] = max(per_course.values()) if per_course else 0
        report["eligible_per_course_mean"] = sum(per_course.values())/len(per_course) if per_course else 0
    except:
        pass
    return report

def quick_solvability_check(normalized_dir: pathlib.Path):
    """PLAN.md §5.A2 — fast pre-solve check against a job's normalized/ folder.

    Catches the specific ways `model.py`/`full_model.py` fail today, so a bad
    upload gets a clear answer in well under a second instead of silently
    burning the full solve time budget:

      - a course with zero eligible faculty doesn't raise anything in
        model.py — the offering is just silently dropped from the schedule
        (`build_variables` prints a warning and `continue`s). That's worse
        than a crash: the solver reports OPTIMAL/FEASIBLE while quietly
        omitting part of what was asked for. BLOCKER.
      - a course with no compatible room falls back to an arbitrary
        CLASSROOM regardless of type/equipment/capacity fit. Not a crash,
        but likely a wrong-looking result. WARNING.
      - a course/offering needing `session_duration==2` with no contiguous
        same-day slot pair in time_slots.csv raises a bare ValueError deep
        in `build_variables`, killing the whole background solve. BLOCKER.

    Returns {"blockers": [str, ...], "warnings": [str, ...]}.
    """
    from .preprocessing import (
        eligible_faculty_per_course, compatible_rooms_by_course, all_contiguous_starts,
    )
    normalized_dir = pathlib.Path(normalized_dir)
    blockers, warnings = [], []

    required_files = ["courses.csv", "rooms.csv", "faculty.csv", "faculty_courses.csv",
                       "course_offerings.csv", "sections.csv", "time_slots.csv"]
    data = {}
    for fname in required_files:
        p = normalized_dir / fname
        rows = _read_csv(p) if p.exists() else []
        if not rows:
            blockers.append(f"Required file '{fname}' is missing or empty — cannot solve without it.")
        data[fname] = rows
    if blockers:
        # Every later check assumes these files exist; bail out with just the
        # missing-file blockers rather than cascading into confusing KeyErrors.
        return {"blockers": blockers, "warnings": warnings}

    # Identity-column integrity: a primary-key column that's blank or collapsed
    # onto one repeated value is a strong signal of a failed import-column
    # mapping (adapter.py's fuzzy header matching couldn't place a real-world
    # column name), not valid data. Caught a real bug this way: an older
    # version of adapter.py silently defaulted every unmapped section_id to
    # the literal "S_CSE_1_A" — a confident WRONG answer with no error
    # anywhere in the pipeline, worse than the file just being empty. Scoped
    # to each dataset's OWN primary key only (courses.course_id, not
    # course_offerings.course_id, which legitimately repeats as a normal FK).
    for fname, id_field in [("courses.csv", "course_id"), ("sections.csv", "section_id"),
                             ("faculty.csv", "faculty_id"), ("rooms.csv", "room_id")]:
        rows = data[fname]
        ids = [str(r.get(id_field, "")).strip() for r in rows]
        blank_count = sum(1 for v in ids if not v)
        if blank_count:
            blockers.append(f"{fname}: {blank_count} of {len(rows)} rows have a blank '{id_field}' — "
                             f"likely a column that didn't import correctly, not real data.")
            continue
        distinct = len(set(ids))
        if len(ids) > 1 and distinct == 1:
            blockers.append(f"{fname}: all {len(rows)} rows have the identical '{id_field}' value "
                             f"'{ids[0]}' — almost certainly a failed column import, not {len(rows)} "
                             f"real records that happen to share one ID.")
        elif len(ids) > 3 and distinct < len(ids) * 0.5:
            blockers.append(f"{fname}: only {distinct} distinct '{id_field}' values across {len(ids)} "
                             f"rows — check that this column mapped to the right source column.")

    courses = data["courses.csv"]
    rooms = data["rooms.csv"]
    faculty_courses = data["faculty_courses.csv"]
    time_slots = data["time_slots.csv"]

    seen = set()
    offerings_deduped = []
    for r in data["course_offerings.csv"]:
        k = (r["course_id"], r["section_id"], r.get("required_sessions"), r.get("session_duration"), r.get("student_count"))
        if k in seen:
            continue
        seen.add(k)
        offerings_deduped.append(r)

    used_course_ids = {o["course_id"] for o in offerings_deduped}
    courses_by_id = {c["course_id"]: c for c in courses}
    eligible = eligible_faculty_per_course(faculty_courses)
    compatible = compatible_rooms_by_course(courses, rooms, offerings_deduped)

    for cid in sorted(used_course_ids):
        if cid not in courses_by_id:
            blockers.append(f"Offering references course '{cid}' which isn't in courses.csv.")
            continue
        if not eligible.get(cid):
            blockers.append(f"Course '{cid}' has no eligible faculty in faculty_courses.csv — "
                             f"that offering would be silently dropped from the schedule.")
        if not compatible.get(cid):
            warnings.append(f"Course '{cid}' has no room matching its required_room_type/equipment — "
                             f"will fall back to an arbitrary classroom.")

    needs_double = any(int(o.get("session_duration", 1) or 1) == 2 for o in offerings_deduped) or \
        any(int(c.get("session_duration", 1) or 1) == 2 for c in courses)
    if needs_double and not all_contiguous_starts(time_slots, 2):
        blockers.append("At least one course/offering needs a 2-slot session but time_slots.csv has "
                         "no contiguous same-day slot pair — this will crash the solve, not just fail it.")

    return {"blockers": blockers, "warnings": warnings}


def get_dataset_roots():
    """Prefer corrected if exists else raw."""
    # Offer both for testing
    return {"raw": DATASET_ROOT_RAW, "corrected": DATASET_ROOT_CORRECTED}

if __name__ == "__main__":
    import json
    print("=== RAW ===")
    print(audit_dataset(DATASET_ROOT_RAW))
    print("=== CORRECTED ===")
    if DATASET_ROOT_CORRECTED.exists():
        print(audit_dataset(DATASET_ROOT_CORRECTED))
    _, info = load_course_offerings(DATASET_ROOT_RAW)
    print("dedup info", info)
