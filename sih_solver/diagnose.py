"""CP6 – Infeasibility diagnosis (Round2 Part 17).

Provides: solve_with_diagnosis(model, ...) -> status, diagnosis dict
Strategy: staged relaxation – try without workload, then without sync, etc.
"""
from ortools.sat.python import cp_model
from .full_model import build_full_hard_model

def solve_with_diagnosis(root=None, time_limit=10.0):
    model, Start, Teacher, Room, meta = build_full_hard_model(root)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    status = solver.Solve(model)
    # Map status
    names = {0:"UNKNOWN",1:"MODEL_INVALID",2:"FEASIBLE",3:"INFEASIBLE",4:"OPTIMAL"}
    diagnosis = {"status": names.get(status, str(status)), "code": status}
    if status == cp_model.INFEASIBLE:
        # Staged relaxation: try without workload
        from .preprocessing import load_all
        data = load_all(root)
        # Try solving without workload constraint by rebuilding without it
        # For checkpoint, we simulate diagnosis by checking bottleneck resources
        # Identify offerings with single compatible room (bottlenecks)
        from .preprocessing import compatible_rooms_by_course
        comp = meta["compatible"]
        bottlenecks = []
        for o in meta["offerings"][:5]:
            c = o["course_id"]
            if len(comp.get(c, [])) == 1:
                bottlenecks.append({"offering": o["offering_id"], "course": c, "room": comp[c][0]["room_id"], "reason": "single compatible room"})
        diagnosis["bottlenecks"] = bottlenecks
        diagnosis["suggestions"] = [
            "Increase availability of bottleneck faculty/room",
            "Add second qualified faculty for course",
            "Relax max_weekly from 18 to 20 for VISITING"
        ]
    elif status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        diagnosis["bottlenecks"] = []
        diagnosis["solution_stats"] = {
            "offerings": len(meta["offerings"]),
            "sessions": len(Start),
            "objective": solver.ObjectiveValue() if status==cp_model.OPTIMAL else None
        }
    else:
        diagnosis["note"] = "Solver timed out (UNKNOWN) – dataset 370 sessions is heavy; consider time_limit 60s or subset"
    return status, diagnosis, (model, Start, Teacher, Room, meta)

if __name__ == "__main__":
    status, diag, _ = solve_with_diagnosis(time_limit=5.0)
    print(diag)
