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
from .soft import add_soft_objective, DEFAULT_WEIGHTS, PENALTY_TO_WEIGHT_KEY

# Round 3C part 2 (PLAN.md, 2026-08-23): tier assignment for
# solve_lexicographic_soft, in strict priority order (see soft.py's module
# docstring for why a single weighted sum can't guarantee this ordering).
# Keys are DEFAULT_WEIGHTS keys, not `penalties` dict keys.
TIER1_SECTION_STRUCTURE_KEYS = ["SC02_gaps", "SC02_gaps_excess", "SC_isolated"]
TIER2_FACULTY_KEYS = ["SC_facgaps", "SC_facgaps_excess"]
TIER3_REST_KEYS = ["SC01_pref", "SC09_balance", "SC03_wastage", "SC05_consecutive",
                    "SC06_spread", "SC08_undesirable", "SC11_building"]

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


def _tier_expr(penalties, weights, tier_keys):
    """Sum of weight*penalty_var for every tier key that's actually present
    (a key is absent from `penalties` if its own weight was 0 when
    add_soft_objective built the model, or the dataset has nothing for that
    term — e.g. SC06_spread is 0 when no course meets >1x/week)."""
    terms = []
    for name, var in penalties.items():
        wkey = PENALTY_TO_WEIGHT_KEY.get(name)
        if wkey in tier_keys and weights.get(wkey, 0):
            terms.append(weights[wkey] * var)
    return sum(terms) if terms else None


def solve_lexicographic_soft(root, hint_vars_vals=None, seed=0,
                              tier_time_limits=(200.0, 100.0, 150.0),
                              weights=None, num_workers=8):
    """Genuine hierarchical/lexicographic soft optimization (PLAN.md Round 3C
    part 2) — see soft.py's module docstring for the diagnosis that motivated
    this (a single weighted sum let SC03_wastage's raw scale dominate 68.5%
    of the objective despite the lowest nominal weight).

    Each tier rebuilds a FRESH hard model (add_soft_objective's variables
    aren't reusable across tiers here — see below) and solves in strict
    priority order:
      1. TIER1_SECTION_STRUCTURE_KEYS — section/student-group day structure
         (internal non-lunch gaps + isolated single-period classes).
      2. TIER2_FACULTY_KEYS — faculty compactness.
      3. TIER3_REST_KEYS — everything else (preference, workload balance,
         room wastage, marathon-avoidance, spread, undesirable slots,
         building movement).
    Two things carry from one tier's fresh model into the next's:
      - every PRIOR tier's achieved objective value, re-applied as a hard
        upper-bound constraint (model.Add(prior_tier_expr <= value_found))
        — so a lower tier can never trade away a unit of a higher tier's
        quality, regardless of either tier's raw magnitude on this (or any
        other) dataset;
      - a hint built from the PRIOR tier's own solved values (not the
        original hard-only hint, which goes stale the moment tier 1 moves
        anything) — warm-starting each tier from the actual state the
        previous tier left the schedule in, not from scratch under a new
        constraint. (A single shared CpModel with a fresh AddHint call
        between tiers was tried first and dropped: this OR-Tools version's
        AddHint appends to the hint proto rather than replacing it, so a
        second round of hints on the same variables is unreliable — see the
        existing comment in solve_hard_then_soft above for the same finding
        in the hard→soft handoff.)
    If a tier fails to find any solution in its budget, the function stops
    and returns the LAST tier that DID succeed (never a broken/UNKNOWN
    solver) — same fallback spirit as solve_hard_then_soft's hard-only
    fallback.

    hint_vars_vals: optional {("Start"|"Teacher"|"Room", key): value} dict
    (e.g. from a validated hard-only solve) to warm-start tier 1.

    Returns a dict: status per tier, objective/best_bound/gap per tier,
    the solver + Start/Teacher/Room/meta/penalties FOR THE LAST SUCCESSFUL
    TIER (read the solution from these, not from a stale reference to an
    earlier tier's now-superseded model), and total solve seconds. Never
    claims OPTIMAL unless CP-SAT proved it for that tier.
    """
    weights = weights or DEFAULT_WEIGHTS
    tiers = [
        ("tier1_section_structure", TIER1_SECTION_STRUCTURE_KEYS),
        ("tier2_faculty", TIER2_FACULTY_KEYS),
        ("tier3_rest", TIER3_REST_KEYS),
    ]
    tier_results = {}
    total_seconds = 0.0
    current_hint = dict(hint_vars_vals or {})
    locked = []  # [(tier_keys, value_found), ...] re-applied fresh in every subsequent tier's model
    last_good = None

    for (label, tier_keys), time_limit in zip(tiers, tier_time_limits):
        model, Start, Teacher, Room, meta = build_full_hard_model(root)
        for (kind, key), val in current_hint.items():
            var = {"Start": Start, "Teacher": Teacher, "Room": Room}[kind].get(key)
            if var is not None:
                model.AddHint(var, val)
        penalties = add_soft_objective(model, Start, Teacher, Room, meta, weights, set_objective=False)
        for prev_keys, prev_value in locked:
            prev_expr = _tier_expr(penalties, weights, prev_keys)
            if prev_expr is not None:
                model.Add(prev_expr <= prev_value)
        expr = _tier_expr(penalties, weights, tier_keys)
        if expr is None:
            tier_results[label] = {"status": "SKIPPED_EMPTY", "objective": None, "best_bound": None, "seconds": 0.0}
            continue
        model.Minimize(expr)
        solver, status_code, dt = _solve_once(model, time_limit, seed, num_workers)
        status = STATUS_NAMES.get(status_code, str(status_code))
        total_seconds += dt
        if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # This tier found nothing within budget -- can't lock a bound or
            # hand a warm-start to the next tier. Stop; last_good (the prior
            # tier, or None if tier 1 itself failed) is what gets returned.
            tier_results[label] = {"status": status, "objective": None, "best_bound": None, "seconds": dt}
            break
        obj = solver.ObjectiveValue()
        bound = solver.BestObjectiveBound()
        tier_results[label] = {"status": status, "objective": obj, "best_bound": bound, "seconds": dt}
        locked.append((tier_keys, int(round(obj))))
        current_hint = {}
        for kind, var_dict in (("Start", Start), ("Teacher", Teacher), ("Room", Room)):
            for key, var in var_dict.items():
                current_hint[(kind, key)] = solver.Value(var)
        last_good = {"solver": solver, "Start": Start, "Teacher": Teacher, "Room": Room,
                     "meta": meta, "penalties": penalties, "label": label}

    if last_good is None:
        raise RuntimeError("solve_lexicographic_soft: not even tier 1 found a solution within its time budget.")
    return {"tier_results": tier_results, "solver": last_good["solver"], "Start": last_good["Start"],
            "Teacher": last_good["Teacher"], "Room": last_good["Room"], "meta": last_good["meta"],
            "penalties": last_good["penalties"], "total_seconds": total_seconds,
            "final_tier_reached": last_good["label"]}
