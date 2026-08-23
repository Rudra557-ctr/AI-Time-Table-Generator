"""CP2 Preprocessing – Derived Data (Round2 Part 4).

All functions are pure, dataset-driven, no solver variables.
"""
import csv
import pathlib
from collections import defaultdict
from datetime import datetime

DATASET_ROOT = pathlib.Path(__file__).resolve().parent.parent
CORRECTED_ROOT = pathlib.Path("/tmp/sih_timetable_dataset_corrected")

# HC10 equipment synonym map: course equipment requirement -> acceptable room
# equipment tokens (interim policy CC09). Keeps matching feasible when the
# course vocabulary is broader than the room vocabulary (e.g. DATABASE_SYSTEMS
# labs run on COMPUTERS rooms).
EQUIPMENT_SYNONYMS = {
    "DATABASE_SYSTEMS": "COMPUTERS",
    "DATABASE": "COMPUTERS",
    "DBMS_SOFTWARE": "COMPUTERS",
    "GPUS": "COMPUTERS",
    "GPU": "COMPUTERS",
    "PROGRAMMING_IDE": "COMPUTERS",
    "SOFTWARE_DEV": "COMPUTERS",
    "AUDIO": "AUDIO_SYSTEM",
    "PROJECTOR_SCREEN": "PROJECTOR",
    "MICROCONTROLLER": "MICROCONTROLLERS",
    "OSCILLOSCOPE": "OSCILLOSCOPES",
    "ROBOT_KIT": "ROBOT_KITS",
    "3D_PRINTERS": "3D_PRINTER",
    "DRAWING_BOARD": "DRAWING_BOARDS",
    "PHYSICS_EQUIPMENT_SET": "PHYSICS_EQUIPMENT",
}

def _read(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def load_all(root=None):
    if root is not None:
        root = pathlib.Path(root)
    if root is None:
        # Prefer corrected dataset where lab capacities are 70 (feasible) over raw 40
        if CORRECTED_ROOT.exists() and (CORRECTED_ROOT / "course_offerings.csv").exists():
            root = CORRECTED_ROOT
        elif (DATASET_ROOT / "course_offerings.csv").exists():
            root = DATASET_ROOT
        else:
            root = DATASET_ROOT
    data = {}
    for fname in ["courses.csv","rooms.csv","faculty.csv","faculty_courses.csv",
                  "faculty_availability.csv","room_availability.csv","time_slots.csv",
                  "course_offerings.csv","sections.csv","students.csv",
                  "student_enrollments.csv","elective_groups.csv","elective_group_courses.csv","fixed_events.csv"]:
        try:
            data[fname] = _read(root / fname)
        except FileNotFoundError:
            data[fname] = []
    # dedup offerings
    seen=set(); deduped=[]
    for r in data["course_offerings.csv"]:
        k=(r["course_id"], r["section_id"])
        if k in seen: continue
        seen.add(k); deduped.append(r)
    data["course_offerings_deduped"] = deduped
    return data

# ---- Derived quantities ----

def eligible_faculty_per_course(faculty_courses):
    d=defaultdict(set)
    for r in faculty_courses:
        d[r["course_id"]].add(r["faculty_id"])
    return dict(d)

def compatible_rooms_for_course(course, rooms, offerings_for_course=None):
    """CompatibleRoomsByEquipment per Round2 Part 4."""
    req_type = course["required_room_type"]
    min_cap = int(course["min_room_capacity"] or 0)
    equip_req = course["equipment_required"].strip()
    # also consider offering studentCount if provided (use max)
    # For labs, studentCount may exceed lab capacity due to batch splitting not modeled;
    # if no room fits max_student, fallback to minCapacity only (Round1 Part C #11 pragmatic).
    effective_cap = min_cap
    if offerings_for_course:
        max_student = max(int(o["student_count"]) for o in offerings_for_course)
        effective_cap = max(min_cap, max_student)
    # first filter by type + capacity
    candidates = [r for r in rooms if r["room_type"]==req_type and int(r["capacity"])>=effective_cap]
    if not candidates and offerings_for_course and effective_cap != min_cap:
        # fallback to minCapacity only
        candidates = [r for r in rooms if r["room_type"]==req_type and int(r["capacity"])>=min_cap]
    if not equip_req:
        return candidates  # C024/C039 fallback
    # equipment must be superset: split course req by comma
    req_tokens = [t.strip() for t in equip_req.split(",") if t.strip()]
    if not req_tokens:
        return candidates
    # apply synonym map to course requirements (HC10 vocab matching)
    req_tokens = [EQUIPMENT_SYNONYMS.get(t, t) for t in req_tokens]
    # check each room equipment
    filtered=[]
    for r in candidates:
        room_equip = set(t.strip() for t in r["equipment"].split(",") if t.strip())
        if all(t in room_equip for t in req_tokens):
            filtered.append(r)
    # If no room matches equipment (Round1 C#13 mismatch), fallback to type+capacity only
    # This is the interim policy CC09 – return candidates but flag
    if not filtered and req_tokens:
        return candidates  # fallback
    return filtered

def compatible_rooms_by_course(courses, rooms, offerings_deduped):
    per_course_offerings=defaultdict(list)
    for o in offerings_deduped:
        per_course_offerings[o["course_id"]].append(o)
    result={}
    for c in courses:
        result[c["course_id"]] = compatible_rooms_for_course(c, rooms, per_course_offerings.get(c["course_id"], []))
    return result

def valid_faculty_slots(faculty_availability):
    d=defaultdict(set)
    for r in faculty_availability:
        if r["available"].lower()=="true":
            d[r["faculty_id"]].add(r["slot_id"])
    return dict(d)

def valid_room_slots(room_availability):
    d=defaultdict(set)
    for r in room_availability:
        if r["available"].lower()=="true":
            d[r["room_id"]].add(r["slot_id"])
    return dict(d)

def parse_time(tstr):
    return datetime.strptime(tstr.strip(), "%H:%M")

def contiguous_slot_sets(time_slots, k=2):
    """Return dict day -> list of tuples of k slot_ids that are clock-contiguous.
    Excludes lunch gap MON_1200 (13:00) -> MON_1400 (14:00) because gap 1h !=0.
    """
    by_day=defaultdict(list)
    for r in time_slots:
        by_day[r["day"]].append(r)
    result={}
    for day, slots in by_day.items():
        # sort by start_time
        slots_sorted = sorted(slots, key=lambda x: parse_time(x["start_time"]))
        groups=[]
        for i in range(len(slots_sorted)-k+1):
            window=slots_sorted[i:i+k]
            ok=True
            for j in range(k-1):
                if parse_time(window[j]["end_time"]) != parse_time(window[j+1]["start_time"]):
                    ok=False; break
            if ok:
                groups.append(tuple(s["slot_id"] for s in window))
        result[day]=groups
    return result

def all_contiguous_starts(time_slots, duration):
    """Set of slot_ids that can be start of a duration-k block."""
    if duration==1:
        return set(r["slot_id"] for r in time_slots)
    csets=contiguous_slot_sets(time_slots, k=duration)
    starts=set()
    for day, groups in csets.items():
        for tup in groups:
            starts.add(tup[0])
    return starts

def occupied_chain_map(time_slots, duration):
    """start slot_id -> full tuple of slot_ids a session of this duration
    would occupy (itself, for duration 1; the full clock-contiguous run,
    for duration>1). Shared by any hard constraint that needs to know every
    slot a multi-slot session actually touches, not just its start -- see
    full_model.py's add_availability_constraints (HC06/HC07) and
    add_fixed_events (HC14), both of which had a bug from checking only the
    start slot before this helper existed (2026-08-23)."""
    if duration == 1:
        return {r["slot_id"]: (r["slot_id"],) for r in time_slots}
    chain = {}
    for day, groups in contiguous_slot_sets(time_slots, k=duration).items():
        for tup in groups:
            chain[tup[0]] = tup
    return chain

def blocked_assignments(fixed_events, time_slots):
    """Map event_id -> set of slot_ids overlapping window, with scope."""
    # Build slot windows
    slot_windows={}
    for s in time_slots:
        slot_windows[s["slot_id"]]=(parse_time(s["start_time"]), parse_time(s["end_time"]), s["day"])
    result={}
    for fe in fixed_events:
        day=fe["day"].strip()
        scope=fe["scope"].strip()
        ev_start=parse_time(fe["start_time"])
        ev_end=parse_time(fe["end_time"])
        blocked=set()
        for sid, (s_start,s_end,s_day) in slot_windows.items():
            if day!="ALL" and s_day!=day:
                continue
            # overlap if slot interval intersects event interval
            if not (s_end <= ev_start or s_start >= ev_end):
                blocked.add(sid)
        result[fe["event_id"]]={"scope":scope,"slots":blocked,"raw":fe}
    return result

def student_elective_offerings(student_enrollments, course_offerings_deduped):
    """Map student_id -> set of offering_ids for OAE/PCE enrollments."""
    # offering lookup course_id+section_id -> offering_id (but student_enroll doesn't have section)
    # For elective, enrollment is course_id only; we map to offering(s) of that course that exist for student's section?
    # Simplified: map student -> courses (OAE/PCE) -> offering_ids that match course_id
    # For true per-student offering, need to find offering where courseOf[o]==c and sectionOf[o]==student's section? But electives are cross-section.
    # Per Round2 Part 4: StudentElectiveOfferings(st) = {o | courseOf[o]==c for c with enrolled[st,c] and type in {OAE,PCE}}
    # So any offering of that course qualifies (since OAE shared).
    course_to_offerings=defaultdict(list)
    for o in course_offerings_deduped:
        course_to_offerings[o["course_id"]].append(o["offering_id"])
    per_student=defaultdict(set)
    for e in student_enrollments:
        if e["enrollment_type"] in ("OAE","PCE"):
            c=e["course_id"]
            for oid in course_to_offerings.get(c, []):
                per_student[e["student_id"]].add(oid)
    return dict(per_student)

def synchronized_offering_groups(elective_groups, elective_group_courses, offerings_deduped):
    """Synchronized elective offerings, grouped per (group_id, course_id).
    Offerings of the SAME course across sections represent one shared elective
    class (cross-section students attend together) -> same time slot.
    """
    groups=[]
    course_to_group={}
    for r in elective_group_courses:
        course_to_group.setdefault(r["elective_group_id"], set()).add(r["course_id"])
    offering_by_course=defaultdict(list)
    for o in offerings_deduped:
        offering_by_course[o["course_id"]].append(o["offering_id"])
    for eg in elective_groups:
        if eg["synchronized"].lower()=="true":
            courses=course_to_group.get(eg["elective_group_id"], set())
            for c in courses:
                oids = offering_by_course.get(c, [])
                if len(oids) >= 2:
                    groups.append({"group_id":eg["elective_group_id"],"course_id":c,"offerings":set(oids)})
    return groups

def elective_alternative_pairs(elective_groups, elective_group_courses, offerings_deduped,
                               student_enrollments=None):
    """Set of (oid1, oid2) offering pairs that are ALTERNATIVES for the same
    student: same elective group AND same section (student picks exactly one).
    Used by HC03 to skip requiring these to be non-overlapping.
    A pair is only treated as an alternative if NO student is actually enrolled
    in both courses (a course may belong to several groups, so e.g. C060 in
    EG01/EG02 and C065 in EG06 are both taken by the same student).
    """
    pairs = set()
    course_to_group={}
    for r in elective_group_courses:
        course_to_group.setdefault(r["elective_group_id"], set()).add(r["course_id"])
    offering_by_course=defaultdict(list)
    for o in offerings_deduped:
        offering_by_course[o["course_id"]].append(o)
    oid_to_course = {o["offering_id"]: o["course_id"] for o in offerings_deduped}
    # students who take both of a course pair -> that pair is NOT an alternative
    both_taken = set()
    if student_enrollments:
        stu_courses = defaultdict(set)
        for e in student_enrollments:
            stu_courses[e["student_id"]].add(e["course_id"])
        for courses in stu_courses.values():
            cl = sorted(courses)
            for i in range(len(cl)):
                for j in range(i+1, len(cl)):
                    both_taken.add((cl[i], cl[j]))
    for eg in elective_groups:
        if eg["synchronized"].lower()!="true":
            continue
        courses = course_to_group.get(eg["elective_group_id"], set())
        # offerings of all courses in this group, grouped by section
        by_sec = defaultdict(list)
        for c in courses:
            for o in offering_by_course.get(c, []):
                by_sec[o["section_id"]].append(o["offering_id"])
        for sec, oids in by_sec.items():
            oids = sorted(set(oids))
            for i in range(len(oids)):
                for j in range(i+1, len(oids)):
                    ca, cb = oid_to_course.get(oids[i]), oid_to_course.get(oids[j])
                    if ca and cb and ((ca, cb) in both_taken or (cb, ca) in both_taken):
                        continue
                    pairs.add((oids[i], oids[j]))
    return pairs

if __name__=="__main__":
    data=load_all()
    print("offerings deduped", len(data["course_offerings_deduped"]))
    comp=compatible_rooms_by_course(data["courses.csv"], data["rooms.csv"], data["course_offerings_deduped"])
    print("compatible sample C028", [r["room_id"] for r in comp.get("C028",[])])
    print("compatible C006", [r["room_id"] for r in comp.get("C006",[])])
    print("contiguous 2", contiguous_slot_sets(data["time_slots.csv"],2))
    print("blocked", blocked_assignments(data["fixed_events.csv"], data["time_slots.csv"]))
