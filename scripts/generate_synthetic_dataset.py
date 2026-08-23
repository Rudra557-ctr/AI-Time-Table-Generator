"""Generate a synthetic dataset for testing the solver/pipeline against data
that ISN'T the bundled sample (SIH_Smart_Timetable_Dataset_CORRECTED) --
different institution, department names, course catalog, IDs, and scale, but
the same relational schema `sih_solver/adapter.py:CANONICAL` expects.

Why: PLAN.md's own top-ranked open item is "nobody has tested this on real,
messy data" -- everything verified so far (hard-constraint fixes, the
lexicographic soft objective) was proven against ONE dataset. This generates
a second, independently-built dataset so the pipeline's genericity claims
have something to actually stand on, not just an assertion in a docstring.

Deliberately NOT a copy-with-renamed-IDs of the bundled dataset: different
department/program names (IT/Mechanical/Civil instead of CSE/ECE/...),
different room-type vocabulary (DRAWING_HALL instead of ROBOTICS_LAB),
different scale (6 sections instead of 16, 32 courses instead of 65),
different faculty-availability/room-availability exception patterns. Same
STRUCTURAL assumptions the solver currently hardcodes elsewhere (5-day week,
7 periods/day, the mid-day slot-4/slot-5 clock gap standing in for lunch) --
changing those is a separate, larger genericity gap (see the note printed at
the end of this script), not something a dataset alone can test.

Usage: python3 scripts/generate_synthetic_dataset.py [output_dir]
Default output_dir: synthetic_data/ (repo root).
"""
import csv
import pathlib
import random
import sys

random.seed(20260823)  # deterministic -- re-running regenerates the identical dataset

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "synthetic_data"

DAYS = ["MON", "TUE", "WED", "THU", "FRI"]
PERIODS = [(1, "09:00", "10:00"), (2, "10:00", "11:00"), (3, "11:00", "12:00"),
           (4, "12:00", "13:00"), (5, "14:00", "15:00"), (6, "15:00", "16:00"), (7, "16:00", "17:00")]

DEPARTMENTS = [
    ("D01", "Information Technology"),
    ("D02", "Mechanical Engineering"),
    ("D03", "Civil Engineering"),
]
PROGRAMS = [
    ("P01", "IT", "Information Technology", "D01"),
    ("P02", "MECH", "Mechanical Engineering", "D02"),
    ("P03", "CIVIL", "Civil Engineering", "D03"),
]
YEARS = [1, 2]

# room_type each program's lab courses need, distinct from the bundled dataset's vocabulary
LAB_ROOM_TYPE = {"P01": "COMPUTER_LAB", "P02": "WORKSHOP", "P03": "DRAWING_HALL"}
LAB_EQUIPMENT = {"P01": "COMPUTERS", "P02": "WORKSHOP_TOOLS", "P03": "DRAFTING_TABLES"}

# (code_suffix, name, sessions_per_week, session_duration, is_lab)
COURSE_TEMPLATE_BY_YEAR = {
    1: [
        ("101", "{prog} Fundamentals I", 4, 1, False),
        ("102", "Applied Mathematics", 3, 1, False),
        ("103", "{prog} Core Principles", 3, 1, False),
        ("104", "{prog} Practical Lab", 1, 2, True),
        ("105", "Technical Communication", 2, 1, False),
    ],
    2: [
        ("201", "{prog} Fundamentals II", 4, 1, False),
        ("202", "{prog} Systems Design", 3, 1, False),
        ("203", "{prog} Analysis Methods", 3, 1, False),
        ("204", "{prog} Advanced Lab", 1, 2, True),
    ],
}

FIRST_NAMES = ["Asha", "Rohan", "Meera", "Karan", "Divya", "Nikhil", "Priya", "Arjun",
               "Sneha", "Vikram", "Ishita", "Aman", "Pooja", "Rahul", "Neha"]
LAST_NAMES = ["Rao", "Verma", "Iyer", "Nair", "Bose", "Kapoor", "Reddy", "Menon",
              "Shah", "Pillai", "Chatterjee", "Desai"]


def _name(used):
    while True:
        n = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        if n not in used:
            used.add(n)
            return n


def build():
    rows = {}  # filename -> list[dict]

    rows["universities.csv"] = [{
        "university_id": "SYN01", "university_name": "Riverside Institute of Technology",
        "campus": "North Campus", "academic_year": "2027-28",
    }]
    rows["departments.csv"] = [{"department_id": d, "department_name": n} for d, n in DEPARTMENTS]
    rows["programs.csv"] = [
        {"program_id": p, "program_code": code, "program_name": name, "department_id": dept,
         "degree": "BTech", "duration_years": "4"}
        for p, code, name, dept in PROGRAMS
    ]

    sections = []
    for p, code, name, dept in PROGRAMS:
        for y in YEARS:
            sections.append({
                "section_id": f"S_{code}_{y}_A", "program_id": p, "year": str(y),
                "section_name": "A", "student_count": str(random.randint(50, 70)),
            })
    rows["sections.csv"] = sections
    sec_by_id = {s["section_id"]: s for s in sections}

    # ---- courses (department-specific catalog, distinct vocabulary per program) ----
    courses = []
    course_by_prog_year = {}
    for p, code, name, dept in PROGRAMS:
        for y in YEARS:
            entries = []
            for suffix, tmpl, spw, dur, is_lab in COURSE_TEMPLATE_BY_YEAR[y]:
                cid = f"C_{code}{suffix}"
                room_type = LAB_ROOM_TYPE[p] if is_lab else "CLASSROOM"
                equip = LAB_EQUIPMENT[p] if is_lab else ""
                courses.append({
                    "course_id": cid, "course_code": f"{code}{suffix}",
                    "course_name": tmpl.format(prog=name), "department_id": dept,
                    "course_type": "LAB" if is_lab else "THEORY", "course_category": "CORE",
                    "credits": str(3 if not is_lab else 1), "weekly_hours": str(spw * dur),
                    "sessions_per_week": str(spw), "session_duration": str(dur),
                    "requires_lab": str(is_lab), "required_room_type": room_type,
                    "min_room_capacity": "35" if is_lab else "60",
                    "equipment_required": equip,
                })
                entries.append(cid)
            course_by_prog_year[(p, y)] = entries

    # Two shared cross-programme open electives (synchronized, year 2 only) --
    # exercises HC13 (synchronized electives) and HC04 (student-level elective
    # collision) the same way the bundled dataset's OAE/PCE groups do.
    oae_courses = [
        ("C_OAE01", "Environmental Studies"),
        ("C_OAE02", "Entrepreneurship Basics"),
    ]
    for cid, name in oae_courses:
        courses.append({
            "course_id": cid, "course_code": cid.replace("C_", ""), "course_name": name,
            "department_id": "D01", "course_type": "THEORY", "course_category": "ELECTIVE",
            "credits": "2", "weekly_hours": "2", "sessions_per_week": "2", "session_duration": "1",
            "requires_lab": "False", "required_room_type": "CLASSROOM", "min_room_capacity": "25",
            "equipment_required": "",
        })
    rows["courses.csv"] = courses

    # ---- course_offerings (+ elective offerings for year-2 sections) ----
    offerings = []
    idx = 1

    def add_offering(cid, sec_id, req_sessions, dur, count):
        nonlocal idx
        offerings.append({
            "offering_id": f"O{idx:04d}", "course_id": cid, "section_id": sec_id,
            "required_sessions": str(req_sessions), "session_duration": str(dur),
            "student_count": str(count),
        })
        idx += 1

    courses_by_id = {c["course_id"]: c for c in courses}
    for p, code, name, dept in PROGRAMS:
        for y in YEARS:
            sec_id = f"S_{code}_{y}_A"
            count = int(sec_by_id[sec_id]["student_count"])
            for cid in course_by_prog_year[(p, y)]:
                c = courses_by_id[cid]
                add_offering(cid, sec_id, int(c["sessions_per_week"]), int(c["session_duration"]), count)

    student_enrollments = []
    stu_idx = 1
    students = []
    for sec in sections:
        n = int(sec["student_count"])
        stu_ids_this_section = []
        for i in range(n):
            sid = f"SYNSTU{stu_idx:04d}"
            stu_idx += 1
            stu_ids_this_section.append(sid)
            students.append({
                "student_id": sid, "student_name": f"Student_{sid}",
                "program_id": sec["program_id"],
                "branch": sec["section_id"].split("_")[1], "year": sec["year"],
                "section_id": sec["section_id"],
            })
        for cid in course_by_prog_year.get((sec["program_id"], int(sec["year"])), []):
            for sid in stu_ids_this_section:
                student_enrollments.append({"student_id": sid, "course_id": cid, "enrollment_type": "CORE"})
        # year-2 sections: split students ~evenly across the two OAE electives
        if sec["year"] == "2":
            for i, sid in enumerate(stu_ids_this_section):
                chosen = oae_courses[i % 2][0]
                student_enrollments.append({"student_id": sid, "course_id": chosen, "enrollment_type": "OAE"})
    rows["students.csv"] = students
    rows["student_enrollments.csv"] = student_enrollments

    year2_sections = [s for s in sections if s["year"] == "2"]
    for cid, _name_ in oae_courses:
        for sec in year2_sections:
            chosen_count = sum(1 for e in student_enrollments
                                if e["course_id"] == cid and e["student_id"].startswith("SYNSTU")
                                and any(st["student_id"] == e["student_id"] and st["section_id"] == sec["section_id"] for st in students))
            add_offering(cid, sec["section_id"], 2, 1, max(chosen_count, 10))
    rows["course_offerings.csv"] = offerings

    rows["elective_groups.csv"] = [{
        "elective_group_id": "EG01", "group_name": "Year 2 Open Area Electives",
        "elective_type": "OAE", "year": "2", "program_scope": "ALL",
        "minimum_choices": "1", "maximum_choices": "1", "synchronized": "True",
    }]
    rows["elective_group_courses.csv"] = [
        {"elective_group_id": "EG01", "course_id": cid} for cid, _ in oae_courses
    ]

    # ---- faculty (comfortably >=3 eligible per course, per-department pools) ----
    faculty = []
    faculty_courses = []
    used_names = set()
    fac_idx = 1
    designations = ["Professor", "Associate Professor", "Assistant Professor"]
    for p, code, name, dept in PROGRAMS:
        dept_courses = [c["course_id"] for c in courses if c["department_id"] == dept]
        n_faculty = max(5, (len(dept_courses) * 3) // 4)  # generous eligible-per-course coverage
        dept_faculty_ids = []
        for i in range(n_faculty):
            fid = f"SF{fac_idx:03d}"
            fac_idx += 1
            dept_faculty_ids.append(fid)
            faculty.append({
                "faculty_id": fid, "name": f"Dr. {_name(used_names)}", "department_id": dept,
                "designation": random.choice(designations),
                "employment_type": "PERMANENT" if i < n_faculty - 1 else "VISITING",
                "max_hours_per_week": str(random.choice([16, 18, 20])),
                "max_hours_per_day": "4", "min_hours_per_week": str(random.choice([6, 8, 10])),
            })
        for cid in dept_courses:
            elig = random.sample(dept_faculty_ids, k=min(3, len(dept_faculty_ids)))
            for j, fid in enumerate(elig):
                faculty_courses.append({
                    "faculty_id": fid, "course_id": cid,
                    "qualification_level": "PRIMARY" if j == 0 else "SECONDARY",
                    "preferred": "True" if j == 0 else "False",
                })
    # OAE electives: any IT-department faculty can teach (matches D01 default above)
    it_faculty = [f["faculty_id"] for f in faculty if f["department_id"] == "D01"]
    for cid, _n in oae_courses:
        for j, fid in enumerate(random.sample(it_faculty, k=min(3, len(it_faculty)))):
            faculty_courses.append({
                "faculty_id": fid, "course_id": cid,
                "qualification_level": "PRIMARY" if j == 0 else "SECONDARY",
                "preferred": "True" if j == 0 else "False",
            })
    rows["faculty.csv"] = faculty
    rows["faculty_courses.csv"] = faculty_courses

    # ---- rooms: classrooms + one lab room per program's room type + a lecture hall ----
    rooms = []
    for i in range(1, 7):
        rooms.append({
            "room_id": f"SR{i:03d}", "room_name": f"Classroom-{i:02d}", "building": "A" if i <= 3 else "B",
            "floor": str(1 + (i % 3)), "room_type": "CLASSROOM", "capacity": str(random.choice([65, 70, 75])),
            "has_projector": "True", "has_computers": "False", "has_ac": "True",
            "equipment": "PROJECTOR,WHITEBOARD",
        })
    lab_specs = [
        ("SR007", "Computer Lab-1", "C", "1", "COMPUTER_LAB", 40, "COMPUTERS,PROJECTOR"),
        ("SR008", "Computer Lab-2", "C", "1", "COMPUTER_LAB", 40, "COMPUTERS,PROJECTOR"),
        ("SR009", "Workshop-1", "D", "1", "WORKSHOP", 35, "WORKSHOP_TOOLS"),
        ("SR010", "Drawing Hall-1", "D", "2", "DRAWING_HALL", 35, "DRAFTING_TABLES"),
        ("SR011", "Lecture Hall-1", "A", "1", "LECTURE_HALL", 120, "PROJECTOR,AUDIO_SYSTEM"),
    ]
    for rid, rname, bld, floor, rtype, cap, equip in lab_specs:
        rooms.append({
            "room_id": rid, "room_name": rname, "building": bld, "floor": floor, "room_type": rtype,
            "capacity": str(cap), "has_projector": "True",
            "has_computers": "True" if rtype == "COMPUTER_LAB" else "False", "has_ac": "True",
            "equipment": equip,
        })
    rows["rooms.csv"] = rooms

    # ---- time_slots: same 5x7 structure (a different period count is a
    # separate, larger genericity gap -- see the note at the end of main()) ----
    time_slots = []
    for day in DAYS:
        for period, start, end in PERIODS:
            time_slots.append({
                "slot_id": f"{day}_{start.replace(':','')}", "day": day, "period_number": str(period),
                "start_time": start, "end_time": end, "is_break": "False",
            })
    rows["time_slots.csv"] = time_slots

    # ---- faculty_availability / room_availability: FULL coverage, mostly
    # True, with a handful of realistic exceptions (Friday-afternoon-off for
    # some faculty, one room out for maintenance one day) ----
    fac_avail = []
    for f in faculty:
        friday_off = random.random() < 0.25
        for s in time_slots:
            avail = True
            if friday_off and s["day"] == "FRI" and int(s["period_number"]) >= 5:
                avail = False
            fac_avail.append({
                "faculty_id": f["faculty_id"], "slot_id": s["slot_id"],
                "available": str(avail), "preference_score": str(random.choice([2, 3, 3, 4])),
            })
    rows["faculty_availability.csv"] = fac_avail

    room_avail = []
    maintenance_room = rooms[0]["room_id"]
    for r in rooms:
        for s in time_slots:
            avail = True
            if r["room_id"] == maintenance_room and s["day"] == "WED" and int(s["period_number"]) <= 2:
                avail = False  # Wednesday-morning maintenance window, one room
            room_avail.append({"room_id": r["room_id"], "slot_id": s["slot_id"], "available": str(avail)})
    rows["room_availability.csv"] = room_avail

    rows["fixed_events.csv"] = [{
        "event_id": "SYNEV01", "event_name": "Weekly Faculty Meeting", "day": "MON",
        "start_time": "12:00", "end_time": "13:00", "scope": "ALL_FACULTY",
    }]

    rows["academic_rules.csv"] = [
        {"rule_id": "SR01", "rule_name": "MAX_DAILY_FACULTY_HOURS", "rule_type": "HARD", "value": "4", "active": "true"},
        {"rule_id": "SR02", "rule_name": "MAX_WEEKLY_FACULTY_HOURS", "rule_type": "HARD", "value": "20", "active": "true"},
    ]

    return rows


def write(rows, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for fname, records in rows.items():
        if not records:
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
    print(f"\nSynthetic dataset written to {OUT}")
    print(f"  {len(rows['sections.csv'])} sections, {len(rows['courses.csv'])} courses, "
          f"{len(rows['course_offerings.csv'])} offerings, {len(rows['faculty.csv'])} faculty, "
          f"{len(rows['rooms.csv'])} rooms, {len(rows['students.csv'])} students")
    print("\nNote on genericity this dataset does NOT test: it keeps the same 5-day, "
          "7-period-per-day time_slots.csv shape as the bundled dataset. soft.py's gap/consecutive-run "
          "terms currently loop `range(1,8)` hardcoded rather than deriving the period range from "
          "time_slots.csv, so a dataset with a different period count would need that generalized "
          "first -- out of scope for a dataset-only change.")


if __name__ == "__main__":
    main()
