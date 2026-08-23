"""Lab batch splitting (Round1 L / NEP).

Sections in sections.csv hold up to 65 students but a single PHYSICS_LAB /
COMPUTER_LAB can only seat 70 in one block. To reflect real lab practice
(labs split into 2 batches of ~30-33), we split each lab offering whose
student_count exceeds BATCH_THRESHOLD into two batch offerings that may run
in the SAME lab room in different slots (sequential) - HC02 room collision
keeps them non-overlapping automatically.

Each batch offering:
  - keeps course_id / section_id / required_sessions / session_duration
  - gets offering_id suffix "-B1"/"-B2" and student_count ~ half
"""
import math
from collections import defaultdict

BATCH_THRESHOLD = 40  # student_count above this => split into 2 batches

def is_lab_course(course):
    return str(course.get("requires_lab", "")).lower() == "true"

def split_lab_offerings(offerings, courses_by_id, threshold=BATCH_THRESHOLD):
    """Return (split_offerings, report) where lab offerings above threshold
    are replaced by two batch offerings."""
    result = []
    report = {"split": 0, "batches": 0, "sessions_added": 0}
    for o in offerings:
        c = courses_by_id.get(o["course_id"])
        try:
            count = int(o["student_count"])
        except (TypeError, ValueError):
            count = 0
        if c is not None and is_lab_course(c) and count > threshold:
            b1_count = int(math.ceil(count / 2))
            b2_count = int(math.floor(count / 2))
            for suffix, n in (("B1", b1_count), ("B2", b2_count)):
                bo = dict(o)
                bo["offering_id"] = f"{o['offering_id']}-{suffix}"
                bo["student_count"] = str(n)
                result.append(bo)
            report["split"] += 1
            report["batches"] += 2
            report["sessions_added"] += 2 * int(o["required_sessions"])
        else:
            result.append(o)
    return result, report

def build_lab_batch_hard_model(root=None, threshold=BATCH_THRESHOLD):
    """Full hard model with lab batches split. Reuses build_variables via
    offerings_override, then applies the same full hard constraints as
    build_full_hard_model."""
    from .preprocessing import load_all
    from .model import build_variables
    from .hard import (add_faculty_collision, add_room_collision,
                       add_section_collision, add_student_collision,
                       add_synchronized_constraints)
    from .full_model import (add_no_repeat_same_course_same_day,
                             add_availability_constraints, add_fixed_events,
                             add_workload_constraints)
    from .preprocessing import synchronized_offering_groups, elective_alternative_pairs
    data = load_all(root)
    courses_by_id = {c["course_id"]: c for c in data["courses.csv"]}
    offerings, report = split_lab_offerings(data["course_offerings_deduped"],
                                            courses_by_id, threshold)
    model, Start, Teacher, Room, meta = build_variables(root, offerings_override=offerings)
    sync_groups = synchronized_offering_groups(meta["data"]["elective_groups.csv"],
                                               meta["data"]["elective_group_courses.csv"],
                                               meta["offerings"])
    alt_pairs = elective_alternative_pairs(meta["data"]["elective_groups.csv"],
                                           meta["data"]["elective_group_courses.csv"],
                                           meta["offerings"])
    add_faculty_collision(model, Start, Teacher, meta["offerings"], meta["data"]["time_slots.csv"])
    add_room_collision(model, Start, Room, meta["offerings"], meta["data"]["time_slots.csv"])
    add_section_collision(model, Start, meta["offerings"], meta["data"]["time_slots.csv"], sync_groups, alt_pairs)
    add_no_repeat_same_course_same_day(model, Start, meta)
    add_student_collision(model, Start, meta["offerings"], meta["data"]["time_slots.csv"],
                          meta["data"]["student_enrollments.csv"], meta["data"]["students.csv"])
    add_synchronized_constraints(model, Start, meta["offerings"], meta["data"]["time_slots.csv"], sync_groups)
    add_availability_constraints(model, Start, Teacher, Room, meta)
    add_fixed_events(model, Start, meta)
    add_workload_constraints(model, Start, Teacher, meta)
    return model, Start, Teacher, Room, meta, report