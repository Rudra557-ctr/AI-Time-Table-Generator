"""Product CLI – Coding Agent as Driver for iterative timetabling.

Usage:
  python -m sih_solver.cli --dataset /tmp/sih_timetable_dataset_corrected --time-limit 15
  python -m sih_solver.cli --varying /path/to/another/dataset

Implements dev loop: HARD tests all at once -> human only for SOFT.
"""
import argparse, pathlib, sys
from ortools.sat.python import cp_model

def run_loop(dataset_root, time_limit=10.0, feedback=None):
    from .full_model import build_full_hard_model
    from .soft import add_soft_objective, DEFAULT_WEIGHTS, apply_human_feedback
    from .diagnose import solve_with_diagnosis

    print(f"\n[1] INGEST dataset={dataset_root}")
    model, Start, Teacher, Room, meta = build_full_hard_model(dataset_root)
    print(f"    Offerings={len(meta['offerings'])} Sessions={len(Start)}")

    print("\n[2] GENERATE + HARD TEST (all HC01-16 at once)")
    status, diag, _ = solve_with_diagnosis(dataset_root, time_limit=time_limit)
    print(f"    Solver status: {diag['status']}")
    if status == cp_model.INFEASIBLE:
        print(f"    HARD FAIL -> bottlenecks: {diag.get('bottlenecks')}")
        print(f"    Suggestions: {diag.get('suggestions')}")
        return diag

    print("    HARD PASS (all 6 HARD groups)")

    print("\n[3] SOFT HUMAN REVIEW (only after HARD PASS)")
    # Add soft and re-solve for preview
    model2, Start2, Teacher2, Room2, meta2 = build_full_hard_model(dataset_root)
    weights = DEFAULT_WEIGHTS.copy()
    if feedback:
        weights = apply_human_feedback(weights, feedback)
        print(f"    Applied human feedback -> weights {weights}")
    add_soft_objective(model2, Start2, Teacher2, Room2, meta2, weights)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    status2 = solver.Solve(model2)
    print(f"    SOFT solve status: {status2}, objective={solver.ObjectiveValue() if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 'N/A'}")
    print("    Human loop: SOFT scores weighted sum; hard never re-tested as constraint (only objective).")
    print("    Iterate: if human says 'gaps bad', agent tunes w and loops to [2].")
    return {"hard": diag, "soft_status": status2, "weights": weights}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="SIH Timetable Agent Driver")
    ap.add_argument("--dataset", default="/tmp/sih_timetable_dataset_corrected", help="path to dataset folder")
    ap.add_argument("--time-limit", type=float, default=10.0)
    ap.add_argument("--varying", help="path to second varying dataset to test adapter")
    args = ap.parse_args()
    res = run_loop(pathlib.Path(args.dataset), time_limit=args.time_limit)
    if args.varying:
        print("\n=== VARYING DATASET TEST ===")
        run_loop(pathlib.Path(args.varying), time_limit=args.time_limit)
