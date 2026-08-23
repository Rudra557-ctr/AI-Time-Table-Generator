"""Adapter for varying user documents -> canonical SIH schema.

Handles:
- Column name fuzzy matching (CourseCode vs course_code vs Course ID)
- Missing columns with defaults
- ZIP of CSVs, single CSV/XLSX
- Normalization to sih_solver internal format (offerings deduped etc.)
"""
import csv, pathlib, re
from collections import defaultdict

# Canonical fields per dataset (from data_dictionary.csv)
CANONICAL = {
    "courses": ["course_id","course_code","course_name","department_id","course_type","course_category","credits","weekly_hours","sessions_per_week","session_duration","requires_lab","required_room_type","min_room_capacity","equipment_required"],
    "course_offerings": ["offering_id","course_id","section_id","required_sessions","session_duration","student_count"],
    "faculty": ["faculty_id","name","department_id","designation","employment_type","max_hours_per_week","max_hours_per_day","min_hours_per_week"],
    "rooms": ["room_id","room_name","building","floor","room_type","capacity","has_projector","has_computers","has_ac","equipment"],
    "time_slots": ["slot_id","day","period_number","start_time","end_time","is_break"],
    "sections": ["section_id","program_id","year","section_name","student_count"],
    "faculty_courses": ["faculty_id","course_id","qualification_level","preferred"],
    "faculty_availability": ["faculty_id","slot_id","available","preference_score"],
    "room_availability": ["room_id","slot_id","available"],
    "students": ["student_id","student_name","program_id","branch","year","section_id"],
    "student_enrollments": ["student_id","course_id","enrollment_type"],
    "fixed_events": ["event_id","event_name","day","start_time","end_time","scope"],
    "elective_groups": ["elective_group_id","group_name","elective_type","year","program_scope","minimum_choices","maximum_choices","synchronized"],
    "elective_group_courses": ["elective_group_id","course_id"],
    "departments": ["department_id","department_name"],
    "programs": ["program_id","program_code","program_name","department_id","degree","duration_years"],
    "universities": ["university_id","university_name","campus","academic_year"],
    "academic_rules": ["rule_id","rule_name","rule_type","value","active"],
}

# Aliases for fuzzy matching (lowercase, no spaces/underscores)
ALIASES = {
    "course_id": ["courseid","course_code","code","id"],
    "section_id": ["sectionid","section","class","class_id"],
    "faculty_id": ["facultyid","teacherid","profid"],
    "room_id": ["roomid","classroom","venue"],
    "required_sessions": ["sessions","sessions_per_week","weekly_sessions","requiredsessions"],
    "session_duration": ["duration","hours","sessionduration"],
    "student_count": ["students","count","enrolled","strength","studentcount"],
    "max_hours_per_day": ["maxdaily","dailyhours","maxdailyhours"],
    "max_hours_per_week": ["maxweekly","weeklyhours"],
}

def _norm(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())

def infer_column_mapping(user_headers, canonical_fields):
    """Map user headers -> canonical field via fuzzy."""
    norm_user = {h: _norm(h) for h in user_headers}
    norm_canon = {c: _norm(c) for c in canonical_fields}
    # Build alias map
    mapping = {}
    for canon in canonical_fields:
        c_norm = norm_canon[canon]
        # Direct match
        for uh, un in norm_user.items():
            if un == c_norm:
                mapping[canon] = uh
                break
        if canon in mapping:
            continue
        # Alias match
        for alias in ALIASES.get(canon, []):
            a_norm = _norm(alias)
            for uh, un in norm_user.items():
                if un == a_norm:
                    mapping[canon] = uh
                    break
            if canon in mapping:
                break
    return mapping

def normalize_csv(input_path, canonical_name, output_path):
    """Read user CSV with inferred mapping, write canonical CSV."""
    with open(input_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        user_headers = reader.fieldnames or []
        mapping = infer_column_mapping(user_headers, CANONICAL[canonical_name])
        rows = list(reader)
    # Write canonical
    with open(output_path, "w", newline='', encoding='utf-8') as out:
        w = csv.DictWriter(out, fieldnames=CANONICAL[canonical_name])
        w.writeheader()
        for idx, r in enumerate(rows):
            out_row = {}
            for canon in CANONICAL[canonical_name]:
                user_col = mapping.get(canon)
                if user_col and user_col in r and r[user_col].strip() != "":
                    out_row[canon] = r[user_col].strip()
                else:
                    # offering_id is the one field genuinely safe to auto-generate:
                    # it's a synthetic primary key this system owns (institutions
                    # don't have pre-existing "offering IDs"), and AUTO{idx} is
                    # unique per row and unmistakably synthetic-looking.
                    if canon == "offering_id" and canonical_name == "course_offerings":
                        out_row[canon] = f"AUTO{idx+1:04d}"
                    else:
                        # NOTE: identity/FK fields (course_id, section_id, faculty_id,
                        # room_id, ...) are deliberately NOT auto-generated here, unlike
                        # an earlier version of this function. That version hardcoded
                        # "section_id": "S_CSE_1_A" as a fallback — meaning any upload
                        # whose section column didn't map got ALL rows silently
                        # collapsed onto that one literal string, with no error anywhere
                        # in the pipeline. A confident wrong answer is worse than a
                        # missing one: leave identity fields blank on a failed mapping so
                        # sih_solver.dataset.quick_solvability_check's blank/duplicate-ID
                        # checks can catch it loudly instead.
                        defaults = {
                            "required_sessions": "1",
                            "session_duration": "1",
                            "student_count": "60",
                            "min_room_capacity": "30",
                            "requires_lab": "False",
                            "required_room_type": "CLASSROOM",
                            "equipment_required": "",
                            "available": "True",
                            "preference_score": "3",
                            "preferred": "False",
                        }
                        out_row[canon] = defaults.get(canon, "")
            w.writerow(out_row)
    return mapping

def detect_dataset_type(headers):
    """Infer which canonical dataset this CSV is by alias-aware mapping count."""
    best = None
    best_score = 0
    for name, fields in CANONICAL.items():
        mapping = infer_column_mapping(headers, fields)
        # Score = number of fields that could be mapped + bonus for key fields
        score = len(mapping)
        # Bonus for presence of discriminating fields
        if name == "course_offerings" and any(_norm(h) in ["section","sectionid","section_id"] for h in headers):
            score += 2
        if name == "courses" and any(_norm(h) in ["coursecode","coursename"] for h in headers):
            score += 1
        if score > best_score:
            best_score = score
            best = name
    return best if best_score >=2 else None

def normalize_upload_folder(upload_dir, normalized_dir, fill_missing=False):
    """Walk upload_dir (may contain ZIP extracted or single CSV), detect each CSV's type, normalize.

    fill_missing=False (default): a missing required dataset is reported as a
    warning and left absent from normalized_dir — callers (e.g.
    quick_solvability_check) can then fail loudly on it. Set fill_missing=True
    to opt into copying the bundled sample dataset's file as a stand-in
    (demo convenience only — silently blending real and sample data is exactly
    the kind of confident-wrong-answer bug this default protects against).
    """
    normalized_dir.mkdir(parents=True, exist_ok=True)
    # Find all CSVs
    csvs = list(upload_dir.rglob("*.csv")) + list(upload_dir.rglob("*.CSV"))
    # Also handle XLSX -> convert to CSV first (handled by parser)
    report = {"detected": [], "warnings": []}
    for csv_path in csvs:
        try:
            with open(csv_path, newline='', encoding='utf-8-sig') as f:
                headers = csv.DictReader(f).fieldnames or []
        except:
            report["warnings"].append(f"Could not read {csv_path.name}")
            continue
        ds_type = detect_dataset_type(headers)
        if not ds_type:
            report["warnings"].append(f"Unknown schema for {csv_path.name} headers {headers[:3]}")
            continue
        out_path = normalized_dir / f"{ds_type}.csv"
        mapping = normalize_csv(csv_path, ds_type, out_path)
        report["detected"].append({"file": csv_path.name, "type": ds_type, "mapping": mapping})
    # Required datasets: report if missing, only fill from the bundled sample
    # dataset when the caller explicitly opts in via fill_missing=True.
    required = ["courses","course_offerings","rooms","time_slots","sections","faculty","faculty_courses","faculty_availability","room_availability"]
    base = pathlib.Path("/tmp/sih_timetable_dataset_corrected")
    if not base.exists():
        base = pathlib.Path(__file__).resolve().parent.parent
    for req in required:
        if not (normalized_dir / f"{req}.csv").exists():
            if fill_missing:
                src = base / f"{req}.csv"
                if src.exists():
                    import shutil
                    shutil.copy(src, normalized_dir / f"{req}.csv")
                    report["warnings"].append(f"Missing {req}.csv – filled from base SIH dataset")
            else:
                report["warnings"].append(f"Missing {req}.csv – required dataset not uploaded; solve will fail until it's provided (pass fill_missing=True to auto-fill demo data).")
    return report
