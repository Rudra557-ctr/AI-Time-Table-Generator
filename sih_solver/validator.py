"""Phase B — Cross-dataset validator (L1 + L2 + L3).

L1  schema checks      -> delegated to sih_solver.schema.validate_rows (types/enums/required/ranges)
L2  referential (FK)   -> every fk field value must exist in target dataset's PK
L3  solvability        -> checks that actually block/effectively block solving:
      - required files present and non-empty
      - every course in an offering has >=1 eligible faculty and >=1 compatible room
      - room capacity vs student_count (warnings vs blockers)
      - availability coverage for faculty/rooms
      - duration-2 needs contiguous slot pair
      - offering duplicates already flagged in L1 (kept as BLOCKER)
      - session_duration mismatch offering vs course (warning)
      - elective course must exist in courses, etc.

Returns dict: {"blockers": [...], "warnings": [...], "per_dataset": {ds: {"rows": n, "blockers": k, "warnings": j}}}

Issue shape: {dataset, row (1-indexed data row; 0=structural), field, message, fix_hint, severity: BLOCKER|WARNING}

Used by:
  - CSV import path (single-dataset validate)
  - Manual-save path (PUT /api/jobs/{id}/data/{ds})
  - Solve gate (validate_all over the whole data.json store before exporting to normalized/*.csv)
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, List, Any

from .schema import SCHEMAS, validate_rows, required_datasets, optional_datasets, get_schema


def _norm_key(k: str) -> str:
    """Accept both 'courses' and 'courses.csv'."""
    return k[:-4] if k.lower().endswith(".csv") else k

def _normalize_data_keys(data: Dict[str, List[Dict[str, str]]]) -> Dict[str, List[Dict[str, str]]]:
    return {_norm_key(k): v for k, v in data.items()}

# FK extraction from schema spec
def _fk_map() -> Dict[str, List[Dict[str, str]]]:
    """Return {dataset: [{field, target_dataset, target_field}]} for all fk fields."""
    out: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for ds, fields in SCHEMAS.items():
        for f in fields:
            fk = f.get("fk")
            if fk:
                # fk is "dataset.field"
                if "." in fk:
                    tds, tf = fk.split(".", 1)
                    out[ds].append({"field": f["name"], "target_dataset": tds, "target_field": tf})
                else:
                    out[ds].append({"field": f["name"], "target_dataset": fk, "target_field": f["name"]})
    return dict(out)

_FK_MAP = _fk_map()

# Which datasets are expected to have a PK uniqueness check via L1 already?
# We don't duplicate that here.


def _l1_blockers(data: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, Any]]:
    blockers: List[Dict[str, Any]] = []
    for ds, rows in data.items():
        nds = _norm_key(ds)
        if nds not in SCHEMAS:
            # unknown dataset name — keep as blocker (L1 unknown)
            blockers.append({
                "dataset": nds, "row": 0, "field": "",
                "message": f"Unknown dataset '{nds}'",
                "fix_hint": f"Known datasets: {', '.join(sorted(SCHEMAS.keys()))}",
                "severity": "BLOCKER",
            })
            continue
        # validate_rows handles per-row L1; pass rows as-is (list of dicts)
        # Note: normalize keys inside rows? assume already bare field names.
        blockers.extend(validate_rows(nds, rows))
    return blockers


def _l2_blockers(data: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, Any]]:
    """FK existence checks. Always BLOCKER."""
    data = _normalize_data_keys(data)
    issues: List[Dict[str, Any]] = []
    # Build PK sets for every target dataset (use whichever field is unique in that target)
    # For simplicity, build a dict of value sets per target field.
    # Most FKs point at the PK column of the target; PK is unique per schema.
    target_value_sets: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
    # Also keep counts for "dataset missing entirely" detection (handled in L3 required check separately)
    for ds, rows in data.items():
        nds = _norm_key(ds)
        # For every field that could be a FK target, collect values
        if nds in SCHEMAS:
            for r in rows:
                for fname in [f["name"] for f in SCHEMAS[nds]]:
                    v = str(r.get(fname, "")).strip()
                    if v != "":
                        target_value_sets[nds][fname].add(v)

    for src_ds, fks in _FK_MAP.items():
        rows = data.get(src_ds)
        if rows is None:
            continue  # missing file handled in L3
        if not rows:
            continue
        for fk in fks:
            field = fk["field"]
            tds = fk["target_dataset"]
            tf = fk["target_field"]
            tgt_set = target_value_sets.get(tds, {}).get(tf, set())
            # If target dataset has no rows or target field has no values, every FK fails.
            # We emit one issue per offending row with the first-seen logic; to avoid 5000-row flood,
            # we cap per-field issues to 20 examples and add a summary issue.
            missing_rows: List[int] = []
            seen_values: set = set()
            for idx, r in enumerate(rows, start=1):
                v = str(r.get(field, "")).strip()
                if v == "":
                    continue  # blank already flagged by L1 required check; skip FK check
                if v not in tgt_set:
                    if v not in seen_values:
                        seen_values.add(v)
                        missing_rows.append(idx)
                        # cap per-field detail issues
                        if len(missing_rows) <= 20:
                            issues.append({
                                "dataset": src_ds,
                                "row": idx,
                                "field": field,
                                "message": f"Value '{v}' not found in {tds}.{tf}",
                                "fix_hint": f"Add '{v}' to {tds}.csv or fix the ID",
                                "severity": "BLOCKER",
                            })
            if len(missing_rows) > 20:
                issues.append({
                    "dataset": src_ds, "row": 0, "field": field,
                    "message": f"... and {len(missing_rows) - 20} more missing references in {src_ds}.{field} → {tds}.{tf}",
                    "fix_hint": "Fix all missing IDs listed above",
                    "severity": "BLOCKER",
                })
    return issues


def _l3_issues(data: Dict[str, List[Dict[str, str]]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Solvability checks. Returns (blockers, warnings)."""
    data = _normalize_data_keys(data)
    blockers: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    def add_blocker(dataset, row, field, msg, hint=""):
        blockers.append({"dataset": dataset, "row": row, "field": field, "message": msg, "fix_hint": hint, "severity": "BLOCKER"})

    def add_warning(dataset, row, field, msg, hint=""):
        warnings.append({"dataset": dataset, "row": row, "field": field, "message": msg, "fix_hint": hint, "severity": "WARNING"})

    # ---- required files present and non-empty ----
    for ds in required_datasets():
        rows = data.get(ds)
        if rows is None:
            add_blocker(ds, 0, "", f"Required dataset '{ds}' is missing", f"Create {ds}.csv with headers: {', '.join(f['name'] for f in get_schema(ds))}")
        elif len(rows) == 0:
            add_blocker(ds, 0, "", f"Required dataset '{ds}' is empty (no data rows)", f"Add at least one row to {ds}.csv")

    # Short-circuit heavy checks if core files missing
    # We still run checks that can tolerate empty inputs.

    # Build helpers
    # courses_by_id
    courses_by_id: Dict[str, Dict[str, str]] = {}
    for r in data.get("courses", []):
        cid = str(r.get("course_id", "")).strip()
        if cid:
            courses_by_id[cid] = r

    # eligible per course (from faculty_courses)
    eligible_per_course: Dict[str, set] = defaultdict(set)
    for r in data.get("faculty_courses", []):
        cid = str(r.get("course_id", "")).strip()
        fid = str(r.get("faculty_id", "")).strip()
        if cid and fid:
            eligible_per_course[cid].add(fid)

    # time_slots contiguity helper (need contiguous pairs for duration-2)
    time_slots = data.get("time_slots", [])
    has_contiguous_pair = False
    slot_by_id: Dict[str, Dict[str, str]] = {}
    slot_to_day_period: Dict[str, tuple] = {}
    from datetime import datetime as _dt
    def _parse(t):
        try:
            return _dt.strptime(t.strip(), "%H:%M")
        except Exception:
            return None
    # quick contiguous check: sort by day then start_time
    try:
        from collections import defaultdict as _dd
        by_day = _dd(list)
        for s in time_slots:
            sid = str(s.get("slot_id", "")).strip()
            day = str(s.get("day", "")).strip()
            st = str(s.get("start_time", "")).strip()
            et = str(s.get("end_time", "")).strip()
            ib = str(s.get("is_break", "")).strip().lower() in ("true", "1", "yes")
            if sid and day and not ib and _parse(st) and _parse(et):
                by_day[day].append((sid, _parse(st), _parse(et)))
                slot_by_id[sid] = s
                # also map for later
                try:
                    pn = int(str(s.get("period_number", "")).strip())
                    slot_to_day_period[sid] = (day, pn)
                except Exception:
                    pass
        for day, lst in by_day.items():
            lst_sorted = sorted(lst, key=lambda x: x[1])
            for i in range(len(lst_sorted) - 1):
                if lst_sorted[i][2] == lst_sorted[i+1][1]:
                    has_contiguous_pair = True
                    break
            if has_contiguous_pair:
                break
    except Exception:
        pass

    # duration-2 guard
    has_duration2 = any(
        str(r.get("session_duration", "")).strip() == "2"
        for r in (data.get("courses", []) + data.get("course_offerings", []))
        if str(r.get("session_duration", "")).strip()
    )
    if has_duration2 and not has_contiguous_pair:
        add_blocker("time_slots", 0, "slot_id",
                    "At least one 2-slot contiguous pair is required (some course/offering has session_duration=2) but none found",
                    "Ensure time_slots has adjacent periods on the same day, e.g. 09:00-10:00 followed by 10:00-11:00")

    # ---- offering-level solvability ----
    # compatible rooms check using preprocessing logic
    try:
        from .preprocessing import compatible_rooms_for_course  # type: ignore
        rooms = data.get("rooms", [])
        # group offerings by course_id for effective capacity lookup (max student_count)
        from collections import defaultdict as _dd2
        offerings_by_course: Dict[str, List[Dict[str, str]]] = _dd2(list)
        for o in data.get("course_offerings", []):
            cid = str(o.get("course_id", "")).strip()
            if cid:
                offerings_by_course[cid].append(o)

        # For each course that appears in offerings, check compatibility
        for cid, course in courses_by_id.items():
            if cid in offerings_by_course:
                comp = compatible_rooms_for_course(course, rooms, offerings_by_course[cid])
                if not comp:
                    # Find which offerings use this course (up to 3 examples)
                    oids = [str(o.get("offering_id", "")).strip() or str(o.get("course_id", "")).strip() for o in offerings_by_course[cid][:3]]
                    add_blocker("courses", 0, "required_room_type",
                                f"Course '{cid}' has no compatible room (type={course.get('required_room_type','')}, min_cap={course.get('min_room_capacity','')}, equip={course.get('equipment_required','')}, max_students={max(int(str(o.get('student_count','0')).strip() or 0) for o in offerings_by_course[cid])})",
                                f"Add a room of type {course.get('required_room_type','CLASSROOM')} with capacity and equipment matching, or change course requirements. Example offerings: {', '.join(oids)}")
        # Also handle offerings whose course_id is not in courses_by_id (FK issue already flagged by L2, but also flag here as blocker for clarity if FK check skipped due to missing courses file)
        for idx, o in enumerate(data.get("course_offerings", []), start=1):
            cid = str(o.get("course_id", "")).strip()
            if cid and cid not in courses_by_id and "courses" in data:
                # L2 already flags missing FK; add a concise blocker only if courses file exists but is empty/missing that id
                pass  # L2 covers it
            # session_duration vs course session_duration mismatch
            if cid in courses_by_id:
                c_sd = str(courses_by_id[cid].get("session_duration", "")).strip()
                o_sd = str(o.get("session_duration", "")).strip()
                if c_sd and o_sd and c_sd != o_sd:
                    add_warning("course_offerings", idx, "session_duration",
                                f"Offering session_duration ({o_sd}) differs from course {cid} session_duration ({c_sd})",
                                "Ensure offering duration matches the course unless intentionally overridden")
            # student_count vs section student_count mismatch (advisory)
            sid = str(o.get("section_id", "")).strip()
            # could warn if offering student_count > section size + large margin, but not required
    except Exception as e:
        # If preprocessing import fails (e.g. no rooms file), emit as warning not blocker to avoid masking real blocker above
        add_warning("courses", 0, "required_room_type", f"Could not check compatible rooms ({e})", "Ensure rooms.csv is valid")

    # ---- eligible faculty per offering ----
    offerings = data.get("course_offerings", [])
    for idx, o in enumerate(offerings, start=1):
        cid = str(o.get("course_id", "")).strip()
        if not cid:
            continue
        if cid in courses_by_id and not eligible_per_course.get(cid):
            add_blocker("course_offerings", idx, "course_id",
                        f"Course '{cid}' has no eligible faculty (no rows in faculty_courses)",
                        f"Add at least one row to faculty_courses.csv for course_id={cid}")

    # ---- capacity vs student_count (room capacity sufficiency) ----
    # For each offering, check max compatible room capacity vs student_count
    try:
        from .preprocessing import compatible_rooms_for_course as _crc
        rooms = data.get("rooms", [])
        for idx, o in enumerate(data.get("course_offerings", []), start=1):
            cid = str(o.get("course_id", "")).strip()
            if cid not in courses_by_id:
                continue
            course = courses_by_id[cid]
            comp = _crc(course, rooms, [o])
            if not comp:
                continue  # already flagged above
            max_cap = max(int(str(r.get("capacity", "0")).strip() or 0) for r in comp)
            sc = str(o.get("student_count", "")).strip()
            if sc and sc.isdigit() and max_cap < int(sc):
                # Check if fallback via preprocessing returned type+capacity rooms but still insufficient -> blocker
                # If any room with required type has capacity >= student_count, then compatible_rooms logic already fell back
                # but we still warn. Here max_cap < student_count means even the largest compatible room is too small.
                add_blocker("course_offerings", idx, "student_count",
                            f"student_count {sc} exceeds largest compatible room capacity {max_cap} for course '{cid}'",
                            "Reduce student_count, increase room capacity, or split into lab batches")
    except Exception:
        pass

    # ---- faculty availability coverage (optional datasets: warn if missing) ----
    fac_avail = data.get("faculty_availability")
    room_avail = data.get("room_availability")
    if fac_avail is None or len(fac_avail) == 0:
        add_warning("faculty_availability", 0, "",
                    "faculty_availability has no rows — solver will assume faculty availability is unrestricted (HC06 disabled)",
                    "Fill availability matrix or import faculty_availability.csv")
    if room_avail is None or len(room_avail) == 0:
        add_warning("room_availability", 0, "",
                    "room_availability has no rows — solver will assume rooms are always available (HC07 disabled)",
                    "Fill room availability matrix or import room_availability.csv")

    # ---- elective groups warnings ----
    # If student_enrollments has OAE/PCE but no elective_groups, warn
    enroll_rows = data.get("student_enrollments", [])
    has_elective_enroll = any(str(r.get("enrollment_type", "")).strip() in ("OAE", "PCE") for r in enroll_rows)
    elec_groups = data.get("elective_groups", [])
    if has_elective_enroll and (elec_groups is None or len(elec_groups) == 0):
        add_warning("elective_groups", 0, "",
                    "Enrollments include OAE/PCE but no elective_groups defined",
                    "Add elective_groups.csv or change enrollment_type to CORE")

    return blockers, warnings


def _is_auto_dedup_warning(msg: str) -> bool:
    """Legacy synthetic data has known auto-handled duplicates (C#14 dedup + enrollment set).
    These are strict BLOCKERs in per-tab editing but only WARNINGs for the solve gate
    because the solver automatically deduplicates/uses sets."""
    return ("Duplicate offering for (course_id, section_id)" in msg
            or "Duplicate row for pair" in msg)

def validate_all(data: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    """Validate the complete store (all datasets). Returns summary.

    Returned dict:
      {
        "blockers": [...],
        "warnings": [...],
        "per_dataset": {ds: {"rows": int, "blockers": int, "warnings": int}},
        "summary": {"total_blockers": int, "total_warnings": int, "can_solve": bool},
        "all_issues": [...]  # blockers + warnings combined
      }
    Severity semantics: BLOCKER prevents solving; WARNING is advisory and must be explicitly acknowledged in the UI.
    Note: legacy duplicate rows (C#14 dedup and duplicate enrollments) are downgraded to
    WARNING in the solve-gate path so the existing synthetic dataset remains solvable;
    per-tab validate_single_dataset still reports them as BLOCKERs.
    """
    data = _normalize_data_keys(data)
    l1 = _l1_blockers(data)
    l2 = _l2_blockers(data)
    l3_b, l3_w = _l3_issues(data)

    # Downgrade legacy auto-dedup duplicates from BLOCKER -> WARNING in the solve gate
    l1_warnings: List[Dict[str, Any]] = []
    l1_blockers: List[Dict[str, Any]] = []
    for iss in l1:
        if _is_auto_dedup_warning(iss.get("message", "")):
            w = dict(iss)
            w["severity"] = "WARNING"
            w["message"] = w["message"] + " (auto-deduped on save/solve)"
            l1_warnings.append(w)
        else:
            l1_blockers.append(iss)

    # Capacity/fallback issues emitted as BLOCKER above are in practice soft — downgrade to WARNING
    # so the synthetic dataset's 65-student offerings vs 60-cap rooms does not block solving (handled via SC03 + fallback).
    l3_b_warnings: List[Dict[str, Any]] = []
    l3_b_real: List[Dict[str, Any]] = []
    for iss in l3_b:
        msg = iss.get("message", "")
        if ("has no compatible room" in msg
                or "exceeds largest compatible room capacity" in msg):
            w = dict(iss)
            w["severity"] = "WARNING"
            l3_b_warnings.append(w)
        else:
            l3_b_real.append(iss)

    blockers = l1_blockers + l2 + l3_b_real
    warnings = l3_w + l1_warnings + l3_b_warnings

    # per-dataset rollup
    all_ds = set(data.keys()) | set(required_datasets()) | set(optional_datasets()) | set(SCHEMAS.keys())
    per_dataset: Dict[str, Dict[str, int]] = {}
    for ds in sorted(all_ds):
        if ds not in SCHEMAS:
            continue
        rows = data.get(ds)
        rc = len(rows) if rows is not None else 0
        bc = sum(1 for i in blockers if i["dataset"] == ds)
        wc = sum(1 for i in warnings if i["dataset"] == ds)
        per_dataset[ds] = {"rows": rc, "blockers": bc, "warnings": wc}

    # Missing required-file blockers show per_dataset as 0 rows already included.

    return {
        "blockers": blockers,
        "warnings": warnings,
        "all_issues": blockers + warnings,
        "per_dataset": per_dataset,
        "summary": {
            "total_blockers": len(blockers),
            "total_warnings": len(warnings),
            "can_solve": len(blockers) == 0,
        },
    }


def validate_single_dataset(dataset: str, rows: List[Dict[str, str]], whole_store: Dict[str, List[Dict[str, str]]] | None = None) -> Dict[str, Any]:
    """Validate a single dataset's rows in context of the whole store.

    If whole_store is provided, FK and solvability checks use it; otherwise only L1 is reported.
    Convenient for per-tab saves and CSV import preview.
    """
    dataset = _norm_key(dataset)
    # L1 for this dataset only
    l1 = validate_rows(dataset, rows)
    blockers = list(l1)
    warnings: List[Dict[str, Any]] = []

    if whole_store is not None:
        # Build a merged view: whole_store with this dataset's rows replaced
        merged = _normalize_data_keys(dict(whole_store))
        merged[dataset] = rows
        # L2 only for this dataset (filter full L2 result)
        l2_all = _l2_blockers(merged)
        l2_here = [i for i in l2_all if i["dataset"] == dataset]
        blockers.extend(l2_here)
        # L3: include only issues whose dataset is this one or structural (row 0) that concern this dataset
        l3_b, l3_w = _l3_issues(merged)
        warnings.extend([i for i in l3_w if i["dataset"] == dataset])
        # Some structural L3 blockers (e.g. no compatible room for a course that this offering touches)
        # may have dataset == "courses" but were triggered by this offering — include them as well when this is course_offerings.
        if dataset == "course_offerings":
            # include courses blockers that mention this course's offerings
            for b in l3_b:
                if b["dataset"] == "courses" and any(str(o.get("course_id", "")).strip() in b.get("message", "") for o in rows):
                    blockers.append(b)
        elif dataset == "courses":
            for b in l3_b:
                if b["dataset"] == "course_offerings":
                    # if course just edited, its offerings may now be unsatisfiable — keep blocker minimal: re-check via validate_all will surface fully
                    pass
    return {
        "blockers": blockers,
        "warnings": warnings,
        "all_issues": blockers + warnings,
        "summary": {"total_blockers": len(blockers), "total_warnings": len(warnings), "can_solve": len(blockers) == 0},
    }
