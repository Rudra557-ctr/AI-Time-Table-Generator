"""Human loop helper – presents timetable for SOFT scoring."""
import pathlib
from .full_model import build_full_hard_model
from .soft import add_soft_objective, apply_human_feedback, DEFAULT_WEIGHTS
from ortools.sat.python import cp_model

def generate_preview(root=None, limit=5):
    model, Start, Teacher, Room, meta = build_full_hard_model(root)
    # Add soft with default weights
    add_soft_objective(model, Start, Teacher, Room, meta, DEFAULT_WEIGHTS)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 8.0
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return f"No feasible solution (status {status})", None
    # Build preview string for first few offerings
    lines = []
    idx_to_slot = meta["idx_to_slot"]
    idx_to_fac = meta["idx_to_fac"]
    idx_to_room = meta["idx_to_room"]
    for o in meta["offerings"][:limit]:
        oid = o["offering_id"]
        fac = idx_to_fac[solver.Value(Teacher[oid])]
        for s in range(int(o["required_sessions"])):
            slot = idx_to_slot[solver.Value(Start[(oid,s)])]
            room = idx_to_room[solver.Value(Room[(oid,s)])]
            lines.append(f"{oid} {o['course_id']} {o['section_id']} s{s} -> {slot} {room} {fac}")
    return "\n".join(lines), (solver, model, Start, Teacher, Room, meta)

if __name__ == "__main__":
    preview, _ = generate_preview()
    print(preview)
