"""Hardened solve pipeline (PLAN.md §5.A1).

A single un-hinted hard+soft solve at a short time limit reliably comes back
UNKNOWN on this problem's size — documented in PLAN.md ("Hard + Soft, no hint:
UNKNOWN, obj 25888, bound 3030, 0 integer solutions"). This reproduces the
known-working path instead: solve HARD ONLY first (retrying seeds if needed),
then AddHint that solution into the combined hard+soft model before solving
soft. If soft still can't find an integer solution within its own budget, fall
back to the hard-only schedule — valid and conflict-free, just not
soft-optimized — rather than returning nothing.
"""
import time
from ortools.sat.python import cp_model
from .full_model import build_full_hard_model
from .soft import add_soft_objective, DEFAULT_WEIGHTS

STATUS_NAMES = {
    cp_model.UNKNOWN: "UNKNOWN",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.OPTIMAL: "OPTIMAL",
}


def _solve_once(model, time_limit, seed, num_workers=8):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = num_workers
    solver.parameters.random_seed = seed
    t0 = time.time()
    status = solver.Solve(model)
    return solver, status, time.time() - t0


def solve_hard_then_soft(root, hard_time_limit=150.0, soft_time_limit=120.0,
                          seeds=(0, 1, 42), weights=None):
    """Returns a dict:
      status: "OPTIMAL_SOFT" | "FEASIBLE_SOFT" | "HARD_ONLY_FALLBACK" | "INFEASIBLE" | "UNKNOWN"
      solver: the CpSolver to read the final assignment from (.Value(...))
      Start, Teacher, Room, meta: the model's variables/metadata
      hard_status, soft_status, seed_used, hard_seconds, soft_seconds, objective: diagnostics
    """
    model, Start, Teacher, Room, meta = build_full_hard_model(root)

    # Phase 1: hard-only, retry seeds in order, stop at the first OPTIMAL/FEASIBLE.
    hard_solver = None
    hard_status = None
    hard_seconds = 0.0
    seed_used = None
    for seed in seeds:
        s, st, dt = _solve_once(model, hard_time_limit, seed)
        hard_status = STATUS_NAMES.get(st, str(st))
        hard_seconds += dt
        if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            hard_solver = s
            seed_used = seed
            break
        if st == cp_model.INFEASIBLE:
            # Proven no valid schedule exists at all — no point trying more seeds or soft.
            return {
                "status": "INFEASIBLE", "hard_status": hard_status, "soft_status": None,
                "solver": s, "Start": Start, "Teacher": Teacher, "Room": Room, "meta": meta,
                "seed_used": seed, "objective": None,
                "hard_seconds": hard_seconds, "soft_seconds": 0.0,
            }
    if hard_solver is None:
        # Every seed came back UNKNOWN — no hard solution found within budget at all.
        return {
            "status": "UNKNOWN", "hard_status": hard_status, "soft_status": None,
            "solver": None, "Start": Start, "Teacher": Teacher, "Room": Room, "meta": meta,
            "seed_used": None, "objective": None,
            "hard_seconds": hard_seconds, "soft_seconds": 0.0,
        }

    # Capture the hard solution's values BEFORE mutating the model with soft additions.
    hint_vars, hint_vals = [], []
    for var_dict in (Start, Teacher, Room):
        for var in var_dict.values():
            hint_vars.append(var)
            hint_vals.append(hard_solver.Value(var))

    # Phase 2: hint into the combined hard+soft model, solve soft.
    add_soft_objective(model, Start, Teacher, Room, meta, weights or DEFAULT_WEIGHTS)
    # This installed OR-Tools version's AddHint takes one (var, value) pair per
    # call (appends to the solution_hint proto), not batched lists — confirmed
    # by reading cp_model.py's add_hint() source after a TypeError revealed the
    # batched-list form isn't what this version's Python binding expects.
    for var, val in zip(hint_vars, hint_vals):
        model.AddHint(var, val)
    soft_solver, soft_status_code, soft_seconds = _solve_once(model, soft_time_limit, seed_used)
    soft_status = STATUS_NAMES.get(soft_status_code, str(soft_status_code))

    if soft_status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "status": "OPTIMAL_SOFT" if soft_status_code == cp_model.OPTIMAL else "FEASIBLE_SOFT",
            "hard_status": hard_status, "soft_status": soft_status,
            "solver": soft_solver, "hard_solver": hard_solver,
            "Start": Start, "Teacher": Teacher, "Room": Room, "meta": meta,
            "seed_used": seed_used, "objective": soft_solver.ObjectiveValue(),
            "hard_seconds": hard_seconds, "soft_seconds": soft_seconds,
        }

    # Soft timed out without an integer solution — fall back to the hard-only
    # schedule (valid, conflict-free, just not soft-optimized) instead of nothing.
    return {
        "status": "HARD_ONLY_FALLBACK", "hard_status": hard_status, "soft_status": soft_status,
        "solver": hard_solver, "hard_solver": hard_solver,
        "Start": Start, "Teacher": Teacher, "Room": Room, "meta": meta,
        "seed_used": seed_used, "objective": None,
        "hard_seconds": hard_seconds, "soft_seconds": soft_seconds,
    }
