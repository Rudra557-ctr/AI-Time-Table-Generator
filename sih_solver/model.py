"""CP3 – Decision Variables + Domain Construction (Round2 Part 5).

Three core variables:
  Start[o,s] -> slot_id domain (start of duration block)
  Teacher[o] -> faculty_id domain (EligibleFaculty)
  Room[o,s] -> room_id domain (CompatibleRoomsByEquipment)

No constraints yet – pure domain.
"""
from ortools.sat.python import cp_model
from .preprocessing import load_all, eligible_faculty_per_course, compatible_rooms_by_course, all_contiguous_starts, valid_faculty_slots, valid_room_slots

def build_variables(root=None):
    data = load_all(root)
    offerings = data["course_offerings_deduped"]  # 133
    courses_by_id = {c["course_id"]: c for c in data["courses.csv"]}
    rooms = data["rooms.csv"]
    faculty_courses = data["faculty_courses.csv"]
    time_slots = data["time_slots.csv"]

    # Preprocessing
    eligible = eligible_faculty_per_course(faculty_courses)
    compatible = compatible_rooms_by_course(data["courses.csv"], rooms, offerings)

    # slot id lists
    all_slots = [s["slot_id"] for s in time_slots]
    # Map slot_id -> index for CP-SAT int var (we use int domain via mapping)
    slot_to_idx = {sid: i for i, sid in enumerate(all_slots)}
    idx_to_slot = {i: sid for sid, i in slot_to_idx.items()}

    # For each offering, compute contiguous starts per duration
    # duration[o] from offering session_duration (string)
    model = cp_model.CpModel()

    Start = {}  # (offering_id, session_idx) -> IntVar (slot index domain)
    Teacher = {}  # offering_id -> IntVar (faculty index domain)
    Room = {}  # (offering_id, session_idx) -> IntVar (room index domain)

    # Faculty mapping per course
    all_faculty_ids = sorted({r["faculty_id"] for r in data["faculty.csv"]})
    fac_to_idx = {fid:i for i,fid in enumerate(all_faculty_ids)}
    idx_to_fac = {i:fid for fid,i in fac_to_idx.items()}

    all_room_ids = sorted(r["room_id"] for r in rooms)
    room_to_idx = {rid:i for i,rid in enumerate(all_room_ids)}
    idx_to_room = {i:rid for rid,i in room_to_idx.items()}

    # Build Teacher vars first (per offering)
    for o in offerings:
        oid = o["offering_id"]
        course_id = o["course_id"]
        elig = sorted(eligible.get(course_id, []))
        if not elig:
            raise ValueError(f"No eligible faculty for {course_id}")
        fac_indices = [fac_to_idx[f] for f in elig]
        # CP-SAT domain can be non-contiguous via AllowedValues? Simpler: IntVar 0..len(fac)-1 and map
        # But we need to allow only eligible indices; use domain from explicit values via NewIntVar with domain
        # Use NewIntVarFromDomain with Domain.FromValues
        dom = cp_model.Domain.FromValues(fac_indices)
        Teacher[oid] = model.NewIntVarFromDomain(dom, f"Teacher_{oid}")

    # Build Start and Room per session
    for o in offerings:
        oid = o["offering_id"]
        duration = int(o["session_duration"])
        req_sessions = int(o["required_sessions"])
        # contiguous starts for this duration
        valid_starts = all_contiguous_starts(time_slots, duration)
        start_indices = [slot_to_idx[s] for s in valid_starts]
        if not start_indices:
            raise ValueError(f"No valid starts for duration {duration}")
        dom = cp_model.Domain.FromValues(start_indices)
        course = courses_by_id[o["course_id"]]
        comp_rooms = compatible.get(o["course_id"], [])
        if not comp_rooms:
            raise ValueError(f"No compatible rooms for {o['course_id']}")
        room_indices = [room_to_idx[r["room_id"]] for r in comp_rooms]
        room_dom = cp_model.Domain.FromValues(room_indices)
        for s in range(req_sessions):
            Start[(oid, s)] = model.NewIntVarFromDomain(dom, f"Start_{oid}_{s}")
            Room[(oid, s)] = model.NewIntVarFromDomain(room_dom, f"Room_{oid}_{s}")

    meta = {
        "offerings": offerings,
        "courses_by_id": courses_by_id,
        "slot_to_idx": slot_to_idx,
        "idx_to_slot": idx_to_slot,
        "fac_to_idx": fac_to_idx,
        "idx_to_fac": idx_to_fac,
        "room_to_idx": room_to_idx,
        "idx_to_room": idx_to_room,
        "eligible": eligible,
        "compatible": compatible,
        "data": data,
    }
    return model, Start, Teacher, Room, meta

def stats(root=None):
    model, Start, Teacher, Room, meta = build_variables(root)
    offerings = meta["offerings"]
    total_sessions = sum(int(o["required_sessions"]) for o in offerings)
    print(f"Offerings: {len(offerings)}")
    print(f"Total sessions: {total_sessions}")
    print(f"Start vars: {len(Start)}")
    print(f"Teacher vars: {len(Teacher)}")
    print(f"Room vars: {len(Room)}")
    # Domain sizes sample
    for oid in list(Teacher.keys())[:2]:
        print(f"Teacher {oid} domain size", len(meta["eligible"].get(next(o['course_id'] for o in offerings if o['offering_id']==oid), [])))
    return model, Start, Teacher, Room, meta

if __name__ == "__main__":
    stats()
