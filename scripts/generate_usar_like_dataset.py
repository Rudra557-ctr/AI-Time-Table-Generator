"""Generate a dataset shaped like USAR's real Odd-Semester-2026-27 published
timetable PDF ("Updated TT-16082026-Batch") -- 4 branches (AIDS, AIML, AR
Robotics, IIOT), 4 year-groups each (I/III/V/VII), B1/B2 batch sections,
lab sub-batch splitting (A/B groups in parallel rooms), OAE/PCE electives at
years V and VII, and course loads sized so each section's weekly grid comes
out densely packed (most of the 5x7 slot grid filled) -- matching that PDF's
visual density -- while staying solvable by the existing CP-SAT pipeline
with NO project code changes.

Deliberately a SEPARATE dataset/output directory from synthetic_data/ (which
tests/test_synthetic_dataset.py depends on) -- this one is for manually
generating and inspecting a dense, multi-branch timetable, not for the
pytest suite.

Usage: python3 scripts/generate_usar_like_dataset.py [output_dir]
Default output_dir: usar_like_dataset/ (repo root).
"""
import csv
import pathlib
import random
import sys

random.seed(20260825)  # deterministic

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "usar_like_dataset"

DAYS = ["MON", "TUE", "WED", "THU", "FRI"]
# Same 7-period, lunch-gap-between-4-and-5 shape as scripts/generate_synthetic_dataset.py
PERIODS = [(1, "09:00", "10:00"), (2, "10:00", "11:00"), (3, "11:00", "12:00"),
           (4, "12:00", "13:00"), (5, "14:00", "15:00"), (6, "15:00", "16:00"), (7, "16:00", "17:00")]

YEAR_LABELS = {1: "I", 2: "III", 3: "V", 4: "VII"}

# (branch_code, department_id, program_id, department_name, branch-specific
#  advanced-lab room types used from year III onward, course-code prefix
#  used for year III+ courses -- year I uses the shared "AR" prefix for all
#  branches, matching the real PDF where AR-101..AR-165 appear identically
#  across AIDS-I/AIML-I/AR-I/IIOT-I as common first-year curriculum)
BRANCHES = [
    ("AIDS", "D_AIDS", "P_AIDS", "AI & Data Science", ["COM_LAB", "ELE_LAB"], "ARD"),
    ("AIML", "D_AIML", "P_AIML", "AI & Machine Learning", ["COM_LAB"], "ARM"),
    ("AR", "D_AR", "P_AR", "Robotics", ["ROB_LAB", "MATERIAL_LAB", "MECHATRONIC_LAB"], "ARA"),
    ("IIOT", "D_IIOT", "P_IIOT", "Industrial IoT", ["IIOT_LAB"], "ARI"),
]

FIRST_NAMES = ["Anirban", "Manisha", "Arti", "Neeta", "Sushobhan", "Bindoo", "Anupam", "Riya",
               "Renu", "Amar", "Atul", "Priyanka", "Kanika", "Abha", "Ruchika", "Rohit", "Disha",
               "Ashish", "Ritu", "Sanjay", "Chetana", "Jyoti", "Pooja", "Himani", "Subhash",
               "Bhanu Prakash", "Reena", "Mahesh", "Kriti", "Ghanendra", "Sowmya", "Manoj",
               "Ravi", "Sheetal", "Rajendra", "Ankur", "Shashi", "Pushp Kumar", "Amanpreet",
               "Sakshi", "Sourabh", "Arvind", "Pawan Kumar", "Deepak", "Rajavel", "Navdeep",
               "Rahul", "Aarti", "Pratibha", "Khyati", "Geetanshi", "Neeraj"]
LAST_NAMES = ["Sharma", "Verma", "Singh", "Rao", "Gupta", "Nair", "Bose", "Kapoor", "Reddy",
              "Menon", "Shah", "Pillai", "Chatterjee", "Desai", "Iyer", "Malhotra", "Chawla"]
DESIGNATIONS = ["Professor", "Associate Professor", "Assistant Professor"]

_used_names = set()


def _fac_name():
    while True:
        n = f"Dr. {random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        if n not in _used_names:
            _used_names.add(n)
            return n


def build():
    rows = {}

    rows["universities.csv"] = [{
        "university_id": "USAR01", "university_name": "University School of Automation & Robotics",
        "campus": "East Delhi Campus", "academic_year": "2026-27",
    }]
    rows["departments.csv"] = [{"department_id": d, "department_name": f"{name}"} for _, d, _, name, _, _ in BRANCHES] + \
        [{"department_id": "D_COMMON", "department_name": "First Year / Cross-Branch Common Courses"}]
    rows["programs.csv"] = [
        {"program_id": p, "program_code": code, "program_name": name, "department_id": dept,
         "degree": "BTech", "duration_years": "4"}
        for code, dept, p, name, _, _ in BRANCHES
    ]

    # ---- sections: 4 branches x 4 years x {B1,B2} = 32 ----
    sections = []
    for code, dept, prog, name, _labs, _prefix in BRANCHES:
        for y in (1, 2, 3, 4):
            for batch in ("B1", "B2"):
                sections.append({
                    "section_id": f"{code}-{YEAR_LABELS[y]}_{batch}", "program_id": prog,
                    "year": str(y), "section_name": batch,
                    "student_count": str(random.randint(52, 64)),
                })
    rows["sections.csv"] = sections
    sec_by_id = {s["section_id"]: s for s in sections}

    # ---- time_slots ----
    time_slots = []
    for day in DAYS:
        for period, start, end in PERIODS:
            time_slots.append({
                "slot_id": f"{day}_{start.replace(':', '')}", "day": day, "period_number": str(period),
                "start_time": start, "end_time": end, "is_break": "False",
            })
    rows["time_slots.csv"] = time_slots

    # ---- rooms ----
    rooms = []
    # Classrooms are branch-scoped too (room_type e.g. "AIDS_CLASSROOM"), for
    # the same reason as the labs below: a genuinely SHARED classroom pool
    # across all 32 sections is what made the combined CP-SAT model too slow
    # to solve cold (a single-attempt 45s test on the shared-classroom
    # version still came back UNKNOWN) -- 8 sections per branch never need
    # more than 8 classrooms at once, so 8 dedicated ones per branch is
    # generous headroom while keeping branches fully independent. Display
    # names still read as plain "Classroom NN" for visual similarity to the
    # PDF's room labels.
    branch_classroom_type = {}
    for code, _dept, _prog, _name, _labs, _prefix in BRANCHES:
        rtype = f"{code}_CLASSROOM"
        branch_classroom_type[code] = rtype
        for i in range(1, 9):
            rooms.append({
                "room_id": f"{code}_CR{i:02d}", "room_name": f"Classroom {i:02d}",
                "building": chr(ord("A") + (i - 1) % 5), "floor": str(1 + (i % 4)),
                "room_type": rtype, "capacity": str(random.choice([70, 72, 75, 78, 80, 85])),
                "has_projector": "True", "has_computers": "False", "has_ac": "True",
                "equipment": "PROJECTOR,WHITEBOARD",
            })
    for i in range(1, 5):
        rooms.append({
            "room_id": f"LH{i:02d}", "room_name": f"Lecture Hall {i:02d}", "building": "MAIN",
            "floor": "1", "room_type": "LECTURE_HALL", "capacity": str(random.choice([100, 110, 120, 130])),
            "has_projector": "True", "has_computers": "False", "has_ac": "True",
            "equipment": "PROJECTOR,AUDIO_SYSTEM,WHITEBOARD",
        })
    # Per-branch lab rooms for year-I/II labs -- room_type is branch-scoped
    # (e.g. "AIDS_COM_LAB" not "COM_LAB") so branches never compete for the
    # same physical room pool. An earlier version used ONE truly-shared
    # pool across all 4 branches, cosmetically matching the PDF's identical
    # "Com Lab"/"Ele.Lab"/"Phy Lab" room names everywhere -- but that made
    # the CP-SAT model for all 32 sections genuinely hard to solve cold
    # (proven only via a 547s search that still came back UNKNOWN, not
    # feasible/infeasible). Branch-scoping keeps the four branches'
    # sub-models decoupled, which is what actually made the full solve fast
    # (see the branch-by-branch solve driver) -- room *display names* still
    # read as "Com Lab"/"Ele. Lab"/"Phy Lab" for visual similarity to the PDF.
    branch_lab_room_specs = [
        ("COM", "Com Lab", "COM_LAB", 38, "COMPUTERS,PROJECTOR"),
        ("ELE", "Ele. Lab", "ELE_LAB", 36, "ELECTRONICS_KITS"),
        ("PHY", "Phy Lab", "PHY_LAB", 36, "LAB_EQUIPMENT"),
    ]
    branch_lab_room_type = {}  # (branch_code, generic_type) -> branch-scoped type string
    for code, _dept, _prog, _name, _labs, _prefix in BRANCHES:
        for prefix, label, rtype, cap, equip in branch_lab_room_specs:
            scoped_type = f"{code}_{rtype}"
            branch_lab_room_type[(code, rtype)] = scoped_type
            for i in range(1, 3):
                rooms.append({
                    "room_id": f"{code}_{prefix}{i:02d}", "room_name": f"{label} {i:02d}", "building": "LABS",
                    "floor": "1", "room_type": scoped_type, "capacity": str(cap),
                    "has_projector": "False", "has_computers": str(rtype == "COM_LAB"), "has_ac": "True",
                    "equipment": equip,
                })
    # Branch-specific advanced labs (year III+): 2 rooms per distinct type
    # used by that branch, so a lab split into simultaneous A/B sub-batches
    # always has 2 same-type rooms free at once. These types were already
    # branch-exclusive by construction (only one branch lists each type).
    branch_lab_types = {"ROB_LAB": "Robotics Lab", "MATERIAL_LAB": "Material Science Lab",
                         "MECHATRONIC_LAB": "Mechatronics Lab", "IIOT_LAB": "IIoT Lab"}
    for code, _dept, _prog, _name, labs, _prefix in BRANCHES:
        for lt in labs:
            if lt not in branch_lab_types:
                continue  # COM_LAB/ELE_LAB/PHY_LAB -- already created above
            for i in range(1, 3):
                rooms.append({
                    "room_id": f"{code}_{lt[:4]}{i:02d}", "room_name": f"{branch_lab_types[lt]} {i:02d}",
                    "building": "LABS", "floor": "2", "room_type": lt, "capacity": "36",
                    "has_projector": "False", "has_computers": "False", "has_ac": "True",
                    "equipment": "SPECIALIZED_EQUIPMENT",
                })
    rows["rooms.csv"] = rooms

    # ---- faculty pools -- per branch (not shared across branches), for the
    # same decoupling reason as the lab rooms above. Cross-branch electives
    # (OAE at years V/VII) still use one shared course_id for cosmetic/
    # bookkeeping consistency, but each branch gets its OWN eligible
    # faculty slice for it (see assign_eligibility calls below) rather than
    # all branches drawing from one small shared pool. ----
    faculty = []
    faculty_courses = []

    def make_pool(dept, n):
        pool = []
        for _ in range(n):
            fid = f"F{len(faculty) + 1:04d}"
            pool.append(fid)
            faculty.append({
                "faculty_id": fid, "name": _fac_name(), "department_id": dept,
                "designation": random.choice(DESIGNATIONS),
                "employment_type": "PERMANENT" if random.random() < 0.85 else "VISITING",
                "max_hours_per_week": str(random.choice([16, 18, 20])),
                "max_hours_per_day": "5", "min_hours_per_week": str(random.choice([8, 10, 12])),
            })
        return pool

    year1_theory_pool = {}
    lab_pool = {}
    elective_pool = {}
    branch_pool = {}
    for code, dept, _prog, _name, _labs, _prefix in BRANCHES:
        year1_theory_pool[code] = make_pool("D_COMMON", 8)
        lab_pool[code] = make_pool("D_COMMON", 6)
        elective_pool[code] = make_pool("D_COMMON", 6)
        branch_pool[code] = make_pool(dept, 16)

    def assign_eligibility(course_id, pool, k=3):
        elig = random.sample(pool, k=min(k, len(pool)))
        for j, fid in enumerate(elig):
            faculty_courses.append({
                "faculty_id": fid, "course_id": course_id,
                "qualification_level": "PRIMARY" if j == 0 else "SECONDARY",
                "preferred": "True" if j == 0 else "False",
            })

    # ---- courses + offerings ----
    courses = []
    offerings = []
    _off_idx = 1

    def add_offering(cid, sec_id, sessions, dur, count):
        nonlocal _off_idx
        offerings.append({
            "offering_id": f"OFF{_off_idx:04d}", "course_id": cid, "section_id": sec_id,
            "required_sessions": str(sessions), "session_duration": str(dur),
            "student_count": str(count),
        })
        _off_idx += 1
        return offerings[-1]["offering_id"]

    def add_course(cid, code_, name, dept, ctype, category, spw, dur, room_type, min_cap, equip=""):
        courses.append({
            "course_id": cid, "course_code": code_, "course_name": name, "department_id": dept,
            "course_type": ctype, "course_category": category,
            "credits": str(2 if ctype == "LAB" else 3), "weekly_hours": str(spw * dur),
            "sessions_per_week": str(spw), "session_duration": str(dur),
            "requires_lab": str(ctype == "LAB"), "required_room_type": room_type,
            "min_room_capacity": str(min_cap), "equipment_required": equip,
        })

    def resolve_lab_type(code, rtype):
        """COM_LAB/ELE_LAB/PHY_LAB are branch-scoped room types (see rooms
        above); every other lab type (ROB_LAB, IIOT_LAB, ...) is already
        exclusive to the one branch that lists it, so it's used as-is."""
        return branch_lab_room_type.get((code, rtype), rtype)

    YEAR1_THEORY = ["Mathematics I", "Applied Physics", "Programming Fundamentals",
                     "Engineering Graphics", "Communication Skills", "Environmental Science"]
    YEAR1_LAB = [("Programming Lab", "COM_LAB"), ("Electronics Workshop", "ELE_LAB"), ("Physics Lab", "PHY_LAB")]

    YEAR2_THEORY_TMPL = ["{b} Core Principles I", "Data Structures & Algorithms", "{b} Systems Design",
                          "Discrete Mathematics", "Professional Ethics"]
    YEAR2_LAB = [("{b} Programming Lab", "COM_LAB"), ("{b} Systems Lab", "ELE_LAB"), ("{b} Design Lab", "PHY_LAB")]

    YEAR3_THEORY_TMPL = ["{b} Advanced Topics I", "{b} Advanced Topics II", "{b} Analysis & Methods"]

    YEAR4_THEORY_TMPL = ["{b} Capstone Theory I", "{b} Capstone Theory II"]

    # (course_id SUFFIX, display name) -- course_id becomes f"C_{branch}_{suffix}"
    # per branch (see the OAE blocks below): same-looking "OAE-1"/"OAE-2"
    # course code everywhere, but a genuinely separate course_id (and
    # eligible-faculty slice) per branch.
    oae_v_courses = [("OAEV1", "Environmental Sustainability"), ("OAEV2", "Entrepreneurship Basics")]
    pce_v_by_branch_tmpl = ["{b} Professional Elective A", "{b} Professional Elective B"]
    oae_vii_courses = [("OAEVII1", "Social Media Analytics"), ("OAEVII2", "Mobile App Development")]
    pce_vii_by_branch_tmpl = ["{b} Capstone Elective A", "{b} Capstone Elective B"]

    def _split(count, floor=15):
        """Split count into (half, other) that sum to count, stay >= floor,
        and are DIFFERENT when possible — so the two parallel A/B offerings
        get distinct (course_id, section_id, student_count) keys and survive
        the (course, section, count) dedup in preprocessing.py/dataset.py.
        Without this, even-count sections produce identical halves (e.g. 64→32/32)
        which the dedup would collapse to one offering, losing a lab batch."""
        half = max(floor, count // 2)
        other = count - half
        if half == other and count >= 2 * floor + 1:
            # make them differ by 1 while keeping sum and floor
            half -= 1
            other += 1
        # clamp floor after adjustment
        if half < floor:
            half = floor
            other = count - half
        if other < floor:
            other = floor
            half = count - other
        return half, other

    for code, dept, prog, bname, labs_types, prefix in BRANCHES:
        for batch in ("B1", "B2"):
            sec_id = f"{code}-{YEAR_LABELS[1]}_{batch}"
            count = int(sec_by_id[sec_id]["student_count"])
            half, other = _split(count, floor=15)

            # ---- Year I: shared-LOOKING "AR" course codes across branches
            # (cosmetic only -- course_id is still per-branch, drawing from
            # that branch's own faculty/room pool, not a true cross-branch
            # shared resource; see the pool/room comments above) ----
            for i, name in enumerate(YEAR1_THEORY, start=101):
                cid = f"C_{code}_AR{i}"
                if not any(c["course_id"] == cid for c in courses):
                    add_course(cid, f"AR-{i}", name, "D_COMMON", "THEORY", "CORE",
                               3, 1, branch_classroom_type[code], 68)
                    assign_eligibility(cid, year1_theory_pool[code])
                add_offering(cid, sec_id, 3, 1, count)
            for j, (name, rtype) in enumerate(YEAR1_LAB):
                cid = f"C_{code}_AR15{j}"
                if not any(c["course_id"] == cid for c in courses):
                    add_course(cid, f"AR-15{j}", name, "D_COMMON", "LAB", "CORE", 1, 2, resolve_lab_type(code, rtype), 34)
                    assign_eligibility(cid, lab_pool[code])
                oidA = add_offering(cid, sec_id, 1, 2, half)
                oidB = add_offering(cid, sec_id, 1, 2, other)
                rows.setdefault("_parallel_pairs", []).append((oidA, oidB))

            # ---- Year III: branch-specific prefix + branch faculty pool ----
            sec_id3 = f"{code}-{YEAR_LABELS[2]}_{batch}"
            count3 = int(sec_by_id[sec_id3]["student_count"])
            half3, other3 = _split(count3, floor=15)
            for i, tmpl in enumerate(YEAR2_THEORY_TMPL, start=201):
                cid = f"C_{code}_{prefix}{i}"
                if not any(c["course_id"] == cid for c in courses):
                    add_course(cid, f"{prefix}-{i}", tmpl.format(b=bname), dept, "THEORY", "CORE", 3, 1, branch_classroom_type[code], 68)
                    assign_eligibility(cid, branch_pool[code])
                add_offering(cid, sec_id3, 3, 1, count3)
            for j, (tmpl, rtype) in enumerate(YEAR2_LAB):
                lab_room_type = resolve_lab_type(code, rtype)
                cid = f"C_{code}_{prefix}25{j}"
                if not any(c["course_id"] == cid for c in courses):
                    add_course(cid, f"{prefix}-25{j}", tmpl.format(b=bname), dept, "LAB", "CORE", 1, 2, lab_room_type, 34)
                    assign_eligibility(cid, branch_pool[code])
                oidA = add_offering(cid, sec_id3, 1, 2, half3)
                oidB = add_offering(cid, sec_id3, 1, 2, other3)
                rows.setdefault("_parallel_pairs", []).append((oidA, oidB))

            # ---- Year V: lighter theory + humanities + OAE + PCE ----
            sec_id5 = f"{code}-{YEAR_LABELS[3]}_{batch}"
            count5 = int(sec_by_id[sec_id5]["student_count"])
            half5, other5 = _split(count5, floor=15)
            for i, tmpl in enumerate(YEAR3_THEORY_TMPL, start=301):
                cid = f"C_{code}_{prefix}{i}"
                if not any(c["course_id"] == cid for c in courses):
                    add_course(cid, f"{prefix}-{i}", tmpl.format(b=bname), dept, "THEORY", "CORE", 4, 1, branch_classroom_type[code], 68)
                    assign_eligibility(cid, branch_pool[code])
                add_offering(cid, sec_id5, 4, 1, count5)
            cid_lab5 = f"C_{code}_{prefix}353"
            if not any(c["course_id"] == cid_lab5 for c in courses):
                add_course(cid_lab5, f"{prefix}-353", f"{bname} Applied Lab", dept, "LAB", "CORE", 1, 2,
                           resolve_lab_type(code, labs_types[0]), 34)
                assign_eligibility(cid_lab5, branch_pool[code])
            oidA = add_offering(cid_lab5, sec_id5, 1, 2, half5)
            oidB = add_offering(cid_lab5, sec_id5, 1, 2, other5)
            rows.setdefault("_parallel_pairs", []).append((oidA, oidB))

            cid_hum = f"C_{code}_HS301"
            if not any(c["course_id"] == cid_hum for c in courses):
                add_course(cid_hum, f"HS{code}-301", "Humanities & Management Elective", "D_COMMON",
                           "THEORY", "CORE", 2, 1, branch_classroom_type[code], 68)
                assign_eligibility(cid_hum, elective_pool[code])
            add_offering(cid_hum, sec_id5, 2, 1, count5)

            # OAE-1 (V): course_id is branch-scoped (own eligible-faculty
            # slice per branch, like everything else in this dataset) --
            # course_CODE stays "OAE-1"/"OAE-2" across branches so it still
            # reads as the same cross-branch open elective in the UI.
            oae_v_cids = []
            for suffix, name_ in oae_v_courses:
                cid = f"C_{code}_{suffix}"
                if not any(c["course_id"] == cid for c in courses):
                    add_course(cid, suffix.replace("OAEV", "OAE-"), name_, "D_COMMON", "THEORY", "ELECTIVE", 2, 1, branch_classroom_type[code], 28)
                    assign_eligibility(cid, elective_pool[code])
                oae_v_cids.append(cid)
            # PCE-1 (V): branch-specific choice of 2
            pce_v_cids = []
            for k, tmpl in enumerate(pce_v_by_branch_tmpl, start=1):
                cid = f"C_{code}_PCEV{k}"
                if not any(c["course_id"] == cid for c in courses):
                    add_course(cid, f"{prefix}-PCE-V{k}", tmpl.format(b=bname), dept, "THEORY", "ELECTIVE", 2, 1, branch_classroom_type[code], 28)
                    assign_eligibility(cid, branch_pool[code])
                pce_v_cids.append(cid)

            rows.setdefault("_elective_v_sections", []).append((sec_id5, count5, oae_v_cids, pce_v_cids))

            # ---- Year VII: light theory + lab + PCE + OAE ----
            sec_id7 = f"{code}-{YEAR_LABELS[4]}_{batch}"
            count7 = int(sec_by_id[sec_id7]["student_count"])
            half7, other7 = _split(count7, floor=12)
            for i, tmpl in enumerate(YEAR4_THEORY_TMPL, start=401):
                cid = f"C_{code}_{prefix}{i}"
                if not any(c["course_id"] == cid for c in courses):
                    add_course(cid, f"{prefix}-{i}", tmpl.format(b=bname), dept, "THEORY", "CORE", 3, 1, branch_classroom_type[code], 68)
                    assign_eligibility(cid, branch_pool[code])
                add_offering(cid, sec_id7, 3, 1, count7)
            cid_lab7 = f"C_{code}_{prefix}453"
            if not any(c["course_id"] == cid_lab7 for c in courses):
                add_course(cid_lab7, f"{prefix}-453", f"{bname} Capstone Lab", dept, "LAB", "CORE", 1, 2,
                           resolve_lab_type(code, labs_types[0]), 34)
                assign_eligibility(cid_lab7, branch_pool[code])
            oidA = add_offering(cid_lab7, sec_id7, 1, 2, half7)
            oidB = add_offering(cid_lab7, sec_id7, 1, 2, other7)
            rows.setdefault("_parallel_pairs", []).append((oidA, oidB))

            # OAE-4/OAE-5 (VII): same branch-scoped-course_id, shared-looking
            # course_code pattern as OAE-1/OAE-2 above.
            oae_vii_cids = []
            for suffix, name_ in oae_vii_courses:
                cid = f"C_{code}_{suffix}"
                if not any(c["course_id"] == cid for c in courses):
                    disp = "OAE-4" if suffix == "OAEVII1" else "OAE-5"
                    add_course(cid, disp, name_, "D_COMMON", "THEORY", "ELECTIVE", 2, 1, branch_classroom_type[code], 28)
                    assign_eligibility(cid, elective_pool[code])
                oae_vii_cids.append(cid)
            pce_vii_cids = []
            for k, tmpl in enumerate(pce_vii_by_branch_tmpl, start=1):
                cid = f"C_{code}_PCEVII{k}"
                if not any(c["course_id"] == cid for c in courses):
                    add_course(cid, f"{prefix}-PCE-VII{k}", tmpl.format(b=bname), dept, "THEORY", "ELECTIVE", 2, 1, branch_classroom_type[code], 28)
                    assign_eligibility(cid, branch_pool[code])
                pce_vii_cids.append(cid)
            rows.setdefault("_elective_vii_sections", []).append((sec_id7, count7, oae_vii_cids, pce_vii_cids))

    rows["courses.csv"] = courses
    rows["faculty.csv"] = faculty
    rows["faculty_courses.csv"] = faculty_courses

    # ---- students + student_enrollments: ONLY for elective (OAE/PCE) picks
    # -- CORE enrollment rows aren't read by any hard constraint, so skipping
    # them keeps row count sane without losing HC04/HC13 coverage. ----
    students = []
    student_enrollments = []
    stu_idx = 1
    elective_offerings_v = []
    elective_offerings_vii = []

    def enroll_electives(sec_id, count, oae_cids, pce_cids, offering_bucket, prefix_tag):
        nonlocal stu_idx
        stu_ids = []
        n_elective_takers = max(20, count - 15)
        for _ in range(n_elective_takers):
            sid = f"STU{stu_idx:05d}"
            stu_idx += 1
            stu_ids.append(sid)
            students.append({
                "student_id": sid, "student_name": f"Student_{sid}",
                "program_id": sec_by_id[sec_id]["program_id"],
                "branch": sec_id.split("-")[0], "year": sec_by_id[sec_id]["year"], "section_id": sec_id,
            })
        oae_counts = {c: 0 for c in oae_cids}
        pce_counts = {c: 0 for c in pce_cids}
        for i, sid in enumerate(stu_ids):
            oae_choice = oae_cids[i % len(oae_cids)]
            pce_choice = pce_cids[i % len(pce_cids)]
            student_enrollments.append({"student_id": sid, "course_id": oae_choice, "enrollment_type": "OAE"})
            student_enrollments.append({"student_id": sid, "course_id": pce_choice, "enrollment_type": "PCE"})
            oae_counts[oae_choice] += 1
            pce_counts[pce_choice] += 1
        # Both elective choices are offered to every section (any student
        # could have picked either), and -- like the lab A/B sub-batches --
        # they only serve disjoint subsets of the section's own students, so
        # they're allowed to run in parallel via parallel_offerings.csv
        # rather than genuinely conflicting under HC03. Deliberately NOT
        # using elective_groups.csv's synchronized=True/HC13 for this: that
        # groups ALL sections' offerings of the same course_id (including
        # every other branch) into ONE forced-same-slot group, which would
        # need one distinct faculty+room per section at that exact slot --
        # this dataset's 3-eligible-faculty-per-elective-course pool isn't
        # sized for that many simultaneous instances. Keeping each section's
        # pair local via parallel_offerings.csv sidesteps that entirely.
        oae_oids = []
        for c in oae_cids:
            oid = add_offering(c, sec_id, 2, 1, max(oae_counts[c], 12))
            offering_bucket.append((c, oid))
            oae_oids.append(oid)
        for i in range(len(oae_oids)):
            for j in range(i + 1, len(oae_oids)):
                rows.setdefault("_parallel_pairs", []).append((oae_oids[i], oae_oids[j]))
        pce_oids = []
        for c in pce_cids:
            oid = add_offering(c, sec_id, 2, 1, max(pce_counts[c], 12))
            offering_bucket.append((c, oid))
            pce_oids.append(oid)
        for i in range(len(pce_oids)):
            for j in range(i + 1, len(pce_oids)):
                rows.setdefault("_parallel_pairs", []).append((pce_oids[i], pce_oids[j]))

    for sec_id, count, oae_cids, pce_cids in rows.pop("_elective_v_sections"):
        enroll_electives(sec_id, count, oae_cids, pce_cids, elective_offerings_v, "V")
    for sec_id, count, oae_cids, pce_cids in rows.pop("_elective_vii_sections"):
        enroll_electives(sec_id, count, oae_cids, pce_cids, elective_offerings_vii, "VII")

    rows["course_offerings.csv"] = offerings
    rows["students.csv"] = students
    rows["student_enrollments.csv"] = student_enrollments

    # ---- elective_groups / elective_group_courses: synchronized=False for
    # all groups (see enroll_electives()'s comment -- HC13 forced sync across
    # every branch's offerings of a shared elective course isn't sized right
    # for this dataset's faculty pools). Still recorded here since the choice
    # groups themselves are real data; just not used to force same-slot
    # scheduling. One group per (elective type, year[, branch for PCE]). ----
    elective_groups = []
    elective_group_courses = []
    oae_v_ids = [c for c, _ in oae_v_courses]
    elective_groups.append({"elective_group_id": "EG_OAE_V", "group_name": "Year V Open Area Electives",
                             "elective_type": "OAE", "year": "3", "program_scope": "ALL",
                             "minimum_choices": "1", "maximum_choices": "1", "synchronized": "False"})
    elective_group_courses += [{"elective_group_id": "EG_OAE_V", "course_id": c} for c in oae_v_ids]
    oae_vii_ids = [c for c, _ in oae_vii_courses]
    elective_groups.append({"elective_group_id": "EG_OAE_VII", "group_name": "Year VII Open Area Electives",
                             "elective_type": "OAE", "year": "4", "program_scope": "ALL",
                             "minimum_choices": "1", "maximum_choices": "1", "synchronized": "False"})
    elective_group_courses += [{"elective_group_id": "EG_OAE_VII", "course_id": c} for c in oae_vii_ids]
    for code, _dept, _prog, _bname, _labs, _prefix in BRANCHES:
        pce_v_ids = [f"C_{code}_PCEV{k}" for k in (1, 2)]
        elective_groups.append({"elective_group_id": f"EG_PCEV_{code}", "group_name": f"{code} Year V Professional Electives",
                                 "elective_type": "PCE", "year": "3", "program_scope": code,
                                 "minimum_choices": "1", "maximum_choices": "1", "synchronized": "False"})
        elective_group_courses += [{"elective_group_id": f"EG_PCEV_{code}", "course_id": c} for c in pce_v_ids]
        pce_vii_ids = [f"C_{code}_PCEVII{k}" for k in (1, 2)]
        elective_groups.append({"elective_group_id": f"EG_PCEVII_{code}", "group_name": f"{code} Year VII Professional Electives",
                                 "elective_type": "PCE", "year": "4", "program_scope": code,
                                 "minimum_choices": "1", "maximum_choices": "1", "synchronized": "False"})
        elective_group_courses += [{"elective_group_id": f"EG_PCEVII_{code}", "course_id": c} for c in pce_vii_ids]
    rows["elective_groups.csv"] = elective_groups
    rows["elective_group_courses.csv"] = elective_group_courses

    # ---- parallel_offerings.csv: lab A/B sub-batches run at the same time
    # in different rooms -- HC03 must not treat them as a section conflict. ----
    parallel_pairs = rows.pop("_parallel_pairs")
    rows["parallel_offerings.csv"] = [
        {"offering_id_a": a, "offering_id_b": b, "reason": "lab sub-batch (parallel groups, same section)"}
        for a, b in parallel_pairs
    ]

    # ---- faculty_availability / room_availability: mostly True, light
    # realistic exceptions so the grid stays dense (matches the PDF). ----
    fac_avail = []
    for f in faculty:
        friday_off = random.random() < 0.2
        for s in time_slots:
            avail = not (friday_off and s["day"] == "FRI" and int(s["period_number"]) >= 6)
            fac_avail.append({"faculty_id": f["faculty_id"], "slot_id": s["slot_id"],
                               "available": str(avail), "preference_score": str(random.choice([2, 3, 3, 4]))})
    rows["faculty_availability.csv"] = fac_avail

    room_avail = []
    maintenance_rooms = {rooms[0]["room_id"], rooms[10]["room_id"]}
    for r in rooms:
        for s in time_slots:
            avail = not (r["room_id"] in maintenance_rooms and s["day"] == "WED" and int(s["period_number"]) <= 1)
            room_avail.append({"room_id": r["room_id"], "slot_id": s["slot_id"], "available": str(avail)})
    rows["room_availability.csv"] = room_avail

    rows["fixed_events.csv"] = [{
        "event_id": "EV_MEET", "event_name": "Weekly Faculty Meeting", "day": "MON",
        "start_time": "12:00", "end_time": "13:00", "scope": "ALL_FACULTY",
    }]
    rows["academic_rules.csv"] = [
        {"rule_id": "R01", "rule_name": "MAX_DAILY_FACULTY_HOURS", "rule_type": "HARD", "value": "5", "active": "true"},
        {"rule_id": "R02", "rule_name": "MAX_WEEKLY_FACULTY_HOURS", "rule_type": "HARD", "value": "20", "active": "true"},
    ]

    return rows


def write(rows, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for fname, records in rows.items():
        if fname.startswith("_") or not records:
            continue
        path = out_dir / fname
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(records[0].keys()))
            w.writeheader()
            w.writerows(records)
        print(f"  wrote {fname}: {len(records)} rows")


def main():
    rows = build()
    write(rows, OUT)
    total_sessions = sum(int(o["required_sessions"]) for o in rows["course_offerings.csv"])
    print(f"\nUSAR-like dataset written to {OUT}")
    print(f"  {len(rows['sections.csv'])} sections, {len(rows['courses.csv'])} courses, "
          f"{len(rows['course_offerings.csv'])} offerings ({total_sessions} total weekly sessions), "
          f"{len(rows['faculty.csv'])} faculty, {len(rows['rooms.csv'])} rooms, "
          f"{len(rows['students.csv'])} elective-enrolled students")


if __name__ == "__main__":
    main()
