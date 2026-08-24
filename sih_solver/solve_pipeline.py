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
from .soft import add_soft_objective, DEFAULT_WEIGHTS, PENALTY_TO_WEIGHT_KEY, _build_occupied, _gap_and_isolated_terms

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


def _solve_hard_only(root, hard_time_limit, seeds):
    """Shared by solve_hard_then_soft and solve_fresh_lexicographic: hard-only
    (no objective), retrying seeds in order, stopping at the first
    OPTIMAL/FEASIBLE. Returns (model, Start, Teacher, Room, meta, hard_solver,
    hard_status, hard_seconds, seed_used, terminal) — `terminal` is a ready-to
    -return dict (INFEASIBLE, or UNKNOWN if every seed came back empty) or
    None if a usable hard_solver was found and the caller should proceed."""
    model, Start, Teacher, Room, meta = build_full_hard_model(root)
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
            return model, Start, Teacher, Room, meta, None, hard_status, hard_seconds, seed, {
                "status": "INFEASIBLE", "hard_status": hard_status, "soft_status": None,
                "solver": s, "Start": Start, "Teacher": Teacher, "Room": Room, "meta": meta,
                "seed_used": seed, "objective": None,
                "hard_seconds": hard_seconds, "soft_seconds": 0.0,
            }
    if hard_solver is None:
        return model, Start, Teacher, Room, meta, None, hard_status, hard_seconds, None, {
            "status": "UNKNOWN", "hard_status": hard_status, "soft_status": None,
            "solver": None, "Start": Start, "Teacher": Teacher, "Room": Room, "meta": meta,
            "seed_used": None, "objective": None,
            "hard_seconds": hard_seconds, "soft_seconds": 0.0,
        }
    return model, Start, Teacher, Room, meta, hard_solver, hard_status, hard_seconds, seed_used, None


def solve_hard_then_soft(root, hard_time_limit=150.0, soft_time_limit=120.0,
                          seeds=(0, 1, 42), weights=None):
    """Returns a dict:
      status: "OPTIMAL_SOFT" | "FEASIBLE_SOFT" | "HARD_ONLY_FALLBACK" | "INFEASIBLE" | "UNKNOWN"
      solver: the CpSolver to read the final assignment from (.Value(...))
      Start, Teacher, Room, meta: the model's variables/metadata
      hard_status, soft_status, seed_used, hard_seconds, soft_seconds, objective: diagnostics
    """
    model, Start, Teacher, Room, meta, hard_solver, hard_status, hard_seconds, seed_used, terminal = \
        _solve_hard_only(root, hard_time_limit, seeds)
    if terminal is not None:
        return terminal

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


def solve_fresh_lexicographic(root, hard_time_limit=150.0,
                               tier_time_limits=(90.0, 45.0, 45.0),
                               seeds=(0, 1, 42), weights=None, num_workers=8):
    """The fix for a real, observed defect: /api/solve was wired to
    solve_hard_then_soft, a single weighted-sum soft objective — the same
    approach Round 3C's own diagnosis (soft.py's module docstring) found let
    one term's raw magnitude dominate 68.5% of the objective regardless of
    its nominal weight, which is why generated timetables had gaps scattered
    across the middle of the day instead of pushed to the day's edges. The
    fix already existed (solve_lexicographic_soft, genuinely prioritizing
    section/day compactness above everything else) but was only ever wired
    into the RESOLVE path (solve_incremental_resolve), never the initial
    generate. This wires it into a fresh (no-previous-solve) generate too.

    Same two-phase shape as solve_hard_then_soft: hard-only first (retrying
    seeds), so a genuinely infeasible/under-time dataset still gets an
    honest INFEASIBLE/UNKNOWN instead of a confusing failure three tiers in.
    The found hard solution then warm-starts tier 1, so tier 1 isn't
    rediscovering feasibility from nothing AND optimizing gaps at once.

    Returns the same top-level keys as solve_hard_then_soft (status,
    hard_status, soft_status, seed_used, hard_seconds, soft_seconds,
    objective, solver/Start/Teacher/Room/meta) so /api/solve's existing
    payload-building code keeps working unchanged, PLUS tier_results and
    final_tier_reached (same shape solve_incremental_resolve already
    returns) for callers that want the honest per-tier breakdown.
    """
    model, Start, Teacher, Room, meta, hard_solver, hard_status, hard_seconds, seed_used, terminal = \
        _solve_hard_only(root, hard_time_limit, seeds)
    if terminal is not None:
        return terminal

    hint_vars_vals = {}
    for hkind, var_dict in (("Start", Start), ("Teacher", Teacher), ("Room", Room)):
        for key, var in var_dict.items():
            hint_vars_vals[(hkind, key)] = hard_solver.Value(var)

    try:
        lex = solve_lexicographic_soft(
            root, hint_vars_vals=hint_vars_vals, seed=seed_used,
            tier_time_limits=tier_time_limits, weights=weights, num_workers=num_workers,
        )
    except RuntimeError:
        # Not even tier 1 found a solution in its budget -- fall back to the
        # hard-only schedule, same graceful-degradation spirit as
        # solve_hard_then_soft's HARD_ONLY_FALLBACK.
        return {
            "status": "HARD_ONLY_FALLBACK", "hard_status": hard_status, "soft_status": "UNKNOWN",
            "solver": hard_solver, "hard_solver": hard_solver,
            "Start": Start, "Teacher": Teacher, "Room": Room, "meta": meta,
            "seed_used": seed_used, "objective": None,
            "hard_seconds": hard_seconds, "soft_seconds": tier_time_limits[0],
            "tier_results": {}, "final_tier_reached": None,
        }

    final_status = lex["tier_results"][lex["final_tier_reached"]]["status"]
    return {
        "status": "OPTIMAL_SOFT" if final_status == "OPTIMAL" else "FEASIBLE_SOFT",
        "hard_status": hard_status, "soft_status": final_status,
        "solver": lex["solver"], "hard_solver": hard_solver,
        "Start": lex["Start"], "Teacher": lex["Teacher"], "Room": lex["Room"], "meta": lex["meta"],
        "seed_used": seed_used,
        "objective": lex["tier_results"][lex["final_tier_reached"]]["objective"],
        "hard_seconds": hard_seconds, "soft_seconds": lex["total_seconds"],
        "tier_results": lex["tier_results"], "final_tier_reached": lex["final_tier_reached"],
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


def hint_from_csv(csv_path, meta):
    """Build a {("Start"|"Teacher"|"Room", key): value} hint dict from a
    previously-generated timetable CSV (the same shape write_csv-style
    callers produce: offering_id,course_id,section_id,session,slot_id,day,
    start_time,end_time,room_id,faculty_id), translated through `meta`'s
    index maps into the integer values CP-SAT variables actually hold.
    Shared by anything that needs to warm-start or stay-close-to a prior
    solve — solve_incremental_resolve below, and any one-off comparison
    script (see PLAN.md Round 3C for the pattern this generalizes)."""
    import csv
    rows = list(csv.DictReader(open(csv_path)))
    hint = {}
    seen_teacher = set()
    for r in rows:
        if r.get("slot_id") in ("UNASSIGNED", "?", ""):
            continue
        oid = r["offering_id"]
        s = int(r["session"]) - 1
        if r["slot_id"] in meta["slot_to_idx"]:
            hint[("Start", (oid, s))] = meta["slot_to_idx"][r["slot_id"]]
        if r["room_id"] in meta["room_to_idx"]:
            hint[("Room", (oid, s))] = meta["room_to_idx"][r["room_id"]]
        if oid not in seen_teacher and r["faculty_id"] in meta["fac_to_idx"]:
            hint[("Teacher", oid)] = meta["fac_to_idx"][r["faculty_id"]]
            seen_teacher.add(oid)
    return hint


def _stability_expr(model, Start, Teacher, Room, meta, reference):
    """Sum of BoolVars, one per (Start/Teacher/Room) variable in THIS model
    that also has an entry in `reference` (a prior solve's hint dict, e.g.
    from hint_from_csv) -- each 1 iff this model's value for that variable
    ends up different from the reference value, 0 if it stays the same.
    A variable with no entry in `reference` (a session/offering that didn't
    exist in the prior solve -- newly added) has nothing to be stable
    against and is skipped, not penalized; a reference entry with no
    matching variable here (removed in the new data) is likewise skipped.
    Minimizing this sum is "change as little as possible from the previous
    schedule" -- the actual mechanism behind solve_incremental_resolve's
    promise to not let one input change cascade through the whole
    timetable."""
    changed = []
    for kind, var_dict in (("Start", Start), ("Teacher", Teacher), ("Room", Room)):
        for key, var in var_dict.items():
            prev_val = reference.get((kind, key))
            if prev_val is None:
                continue
            b = model.NewBoolVar(f"changed_{kind}_{key}")
            model.Add(var != prev_val).OnlyEnforceIf(b)
            model.Add(var == prev_val).OnlyEnforceIf(b.Not())
            changed.append(b)
    return sum(changed) if changed else None


def solve_lexicographic_soft(root, hint_vars_vals=None, seed=0,
                              tier_time_limits=(200.0, 100.0, 150.0),
                              weights=None, num_workers=8,
                              stability_reference=None, stability_time_limit=None,
                              skip_tier1=False):
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

    stability_reference: optional {("Start"|"Teacher"|"Room", key): value}
    dict (typically hint_from_csv(...) of a job's PREVIOUS solve). When
    given, a tier 0 is solved FIRST, ahead of even section-day structure:
    minimize how many sessions differ from `stability_reference` at all
    (see _stability_expr). This is what makes a re-solve after one input
    changes behave like "fix what's now broken, leave everything else
    alone" instead of quietly re-deciding the whole timetable from
    scratch — the actual "don't let one change cascade" requirement. Also
    used as tier 0's own AddHint (so the search starts AT the old
    schedule, not from nothing) unless hint_vars_vals is given instead.
    stability_time_limit defaults to tier_time_limits[0] if not given.

    skip_tier1: when True, omits tier1_section_structure entirely (the
    caller has already handled section-gap/isolation structure some other
    way -- e.g. solve_deep_optimize running lns_gap_repair first, which
    empirically both converges faster AND further than tier1's joint
    all-sections-at-once optimization). tier_time_limits must then have
    exactly 2 entries (tier2, tier3), not 3, since only those two tiers run.

    Returns a dict: status per tier, objective/best_bound/gap per tier,
    the solver + Start/Teacher/Room/meta/penalties FOR THE LAST SUCCESSFUL
    TIER (read the solution from these, not from a stale reference to an
    earlier tier's now-superseded model), and total solve seconds. Never
    claims OPTIMAL unless CP-SAT proved it for that tier.
    """
    weights = weights or DEFAULT_WEIGHTS
    sc_tiers = [
        ("sc", "tier1_section_structure", TIER1_SECTION_STRUCTURE_KEYS),
        ("sc", "tier2_faculty", TIER2_FACULTY_KEYS),
        ("sc", "tier3_rest", TIER3_REST_KEYS),
    ]
    if skip_tier1:
        sc_tiers = sc_tiers[1:]
    time_limits = list(tier_time_limits)
    if stability_reference:
        sc_tiers.insert(0, ("stability", "tier0_stability", stability_reference))
        time_limits.insert(0, stability_time_limit if stability_time_limit is not None else tier_time_limits[0])
    tiers = sc_tiers

    tier_results = {}
    total_seconds = 0.0
    current_hint = dict(hint_vars_vals or stability_reference or {})
    locked = []  # [(kind, payload, value_found), ...] re-applied fresh in every subsequent tier's model
    last_good = None

    for (kind, label, payload), time_limit in zip(tiers, time_limits):
        model, Start, Teacher, Room, meta = build_full_hard_model(root)
        for (hkind, key), val in current_hint.items():
            var = {"Start": Start, "Teacher": Teacher, "Room": Room}[hkind].get(key)
            if var is not None:
                model.AddHint(var, val)
        penalties = add_soft_objective(model, Start, Teacher, Room, meta, weights, set_objective=False)

        def _build_expr(k, p):
            return _stability_expr(model, Start, Teacher, Room, meta, p) if k == "stability" \
                else _tier_expr(penalties, weights, p)

        for prev_kind, prev_payload, prev_value in locked:
            prev_expr = _build_expr(prev_kind, prev_payload)
            if prev_expr is not None:
                model.Add(prev_expr <= prev_value)
        expr = _build_expr(kind, payload)
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
        locked.append((kind, payload, int(round(obj))))
        current_hint = {}
        for hkind, var_dict in (("Start", Start), ("Teacher", Teacher), ("Room", Room)):
            for key, var in var_dict.items():
                current_hint[(hkind, key)] = solver.Value(var)
        last_good = {"solver": solver, "Start": Start, "Teacher": Teacher, "Room": Room,
                     "meta": meta, "penalties": penalties, "label": label}

    if last_good is None:
        raise RuntimeError("solve_lexicographic_soft: not even tier 1 found a solution within its time budget.")
    return {"tier_results": tier_results, "solver": last_good["solver"], "Start": last_good["Start"],
            "Teacher": last_good["Teacher"], "Room": last_good["Room"], "meta": last_good["meta"],
            "penalties": last_good["penalties"], "total_seconds": total_seconds,
            "final_tier_reached": last_good["label"]}


def solve_incremental_resolve(root, previous_csv_path, seed=0,
                               stability_time_limit=60.0,
                               tier_time_limits=(40.0, 30.0, 30.0),
                               weights=None, num_workers=8):
    """The actual 'dynamic re-solve' entry point: given a job's root data
    (already updated with whatever changed -- a faculty marked unavailable,
    an offering's session count edited, etc.) and the CSV from that job's
    PREVIOUS solve, re-solve MINIMIZING how much the schedule changes from
    that previous solve (tier 0), then apply the same section-structure /
    faculty / everything-else tiers as solve_lexicographic_soft on top of
    that -- so a change that forces one session to move doesn't also quietly
    let the optimizer reshuffle everything else "while it's in there".

    Time budgets default much shorter than a cold solve_lexicographic_soft
    call (stability_time_limit=60s, tier budgets 40/30/30s vs the cold
    solve's 220/100/130s) -- a re-solve is meant to feel interactive, not
    repeat the full initial solve's time cost. Tune per deployment.

    Returns the same shape as solve_lexicographic_soft, plus `changed`: a
    list of {"kind","key","old","new"} dicts -- one per Start/Teacher/Room
    variable whose final value differs from `previous_csv_path`'s, with
    "old"/"new" already resolved to real slot_id/faculty_id/room_id strings
    (not raw indices) so a caller can use it directly as a diff report. This
    is the actual "here's what cascaded" answer, computed the same way
    _stability_expr's penalty is, just read back out of the final solution
    rather than left as an opaque objective number.
    """
    # A throwaway model, built and discarded, purely to get meta's id maps
    # (slot_to_idx/room_to_idx/fac_to_idx) so hint_from_csv can translate the
    # previous CSV's slot_id/room_id/faculty_id strings into the same integer
    # values the real solve's variables will use.
    _, _, _, _, meta_for_ids = build_full_hard_model(root)
    reference = hint_from_csv(previous_csv_path, meta_for_ids)

    result = solve_lexicographic_soft(
        root, seed=seed, tier_time_limits=tier_time_limits, weights=weights,
        num_workers=num_workers, stability_reference=reference,
        stability_time_limit=stability_time_limit,
    )

    solver, Start, Teacher, Room, meta = result["solver"], result["Start"], result["Teacher"], result["Room"], result["meta"]
    idx_maps = {"Start": meta["idx_to_slot"], "Teacher": meta["idx_to_fac"], "Room": meta["idx_to_room"]}
    changed = []
    for kind, var_dict in (("Start", Start), ("Teacher", Teacher), ("Room", Room)):
        for key, var in var_dict.items():
            prev_val = reference.get((kind, key))
            if prev_val is None:
                continue
            new_val = solver.Value(var)
            if new_val != prev_val:
                idx_map = idx_maps[kind]
                changed.append({"kind": kind, "key": key, "old": idx_map.get(prev_val), "new": idx_map.get(new_val)})
    result["changed"] = changed
    return result


def solve_deep_optimize(root, previous_csv_path, seed=0,
                         lns_max_rounds=20, lns_time_limits=(5.0, 15.0, 30.0),
                         tier_time_limits=(30.0, 30.0), run_faculty_preference_polish=False,
                         weights=None, num_workers=8):
    """The 'Optimize Further' entry point: take an ALREADY-VALID schedule
    (previous_csv_path, from a fast solve_hard_then_soft generate) and
    genuinely re-optimize it, warm-started from that schedule throughout so
    no phase needs to rediscover hard-constraint feasibility from scratch.

    Two phases, run in sequence:
      1. lns_gap_repair -- section-gap/isolation structure, via the
         Lantiv-inspired local-repair loop (see that function's docstring).
         Defaults tuned for demo-friendly speed: lns_max_rounds=20 (not the
         40 first validated) because round-by-round logging on a real run
         showed the worst offenders get fixed in the first ~15-20 rounds --
         rounds 20-39 were almost entirely diminishing-returns retries that
         mostly failed (score already near-optimal per section by then).
         Each round used to pay a measured ~1.3-3.1s CP-SAT model-rebuild
         cost via a fresh build_full_hard_model call -- with 40 rounds that
         overhead alone was ~126s of the original ~180s. Fixed by building
         the hard model ONCE and, per round, cloning its already-built
         proto (_clone_model, a ~0.05s protobuf-level copy) instead of
         re-running the Python-side builder -- OR-Tools CpModel constraints
         can't be REMOVED once added, but a fresh clone sidesteps that
         entirely since each round gets its own independent copy to pin
         constraints onto, not a mutated shared model. Variable wrapper
         objects (Start/Teacher/Room) from the original build stay valid
         against any clone since OR-Tools only needs their index. At
         max_rounds=20 the SAME real dataset still cut internal gaps ~79%
         (101->21ish); verify per-run, don't assume the exact percentage
         holds on every dataset.
      2. solve_lexicographic_soft with skip_tier1=True, warm-started
         directly from phase 1's final assignment -- faculty-compactness
         (tier2), then preferences/workload/room-use/spread (tier3), same
         strict per-tier priority as before. tier_time_limits defaults to
         (30.0, 30.0) (not the 90/90 first validated) for the same
         demo-speed reason -- more likely to end FEASIBLE rather than
         fully converged, or even fail to improve at all (gracefully
         handled below), trading some faculty/preference polish for time.

    run_faculty_preference_polish: default False -- phase 2 is SKIPPED
    entirely, not given a token time budget doomed to fail. Measured live:
    at the previously-tried 30s/30s tier budgets, phase 2 timed out without
    improving anything and its ~30s was pure waste (fell back to the exact
    same LNS-only result phase 1 already had). Skipping it outright saves
    that time with zero quality cost at this budget level. Pass True to run
    it anyway (e.g. a "final polish" pass once demo-time pressure is off,
    ideally with the original 90s/90s budgets that were shown to actually
    converge).

    Deliberately does NOT hard-lock phase 1's gap score before running
    phase 2, when it runs (unlike tier1->tier2's locking when the OLD
    single-lexicographic path ran all three tiers together) -- chosen for
    speed/simplicity over that extra safety margin. In principle tier2/tier3
    could trade back a small amount of gap quality for a faculty/preference
    gain since nothing stops them; `lns_objective`/`lns_starting_objective`
    in the return value let a caller compare the gap score before and after
    phase 2 to see whether that actually happened on a given run, rather
    than assuming it never does.

    Does NOT use solve_incremental_resolve/stability_reference in either
    phase: that minimizes how much changes from the previous solve, which
    is exactly wrong here -- the goal is genuine re-optimization, not
    staying close to a schedule being replaced because its structure
    wasn't good enough.

    Returns the same top-level shape as before (status, hard_status,
    soft_status, objective, hard_seconds, soft_seconds, tier_results,
    final_tier_reached, solver/Start/Teacher/Room/meta), with hard_status
    "REUSED" (no hard-only phase re-run), plus `lns_rounds`,
    `lns_objective`, `lns_starting_objective` for phase 1's own log.
    """
    lns = lns_gap_repair(root, previous_csv_path, weights=weights,
                          max_rounds=lns_max_rounds, time_limits=lns_time_limits,
                          num_workers=num_workers)
    warm_hint = lns["final_hint"]
    # soft_seconds below is reported to the API/UI as "total_seconds" for the
    # whole /api/optimize call -- must include LNS's own time, not just
    # solve_lexicographic_soft's, or the reported duration silently
    # understates how long the operation actually took (caught on a live
    # run: LNS took ~180s that were missing from the first version of this).
    lns_seconds = sum(r["seconds"] for r in lns["rounds"])

    lex = None
    if run_faculty_preference_polish:
        try:
            lex = solve_lexicographic_soft(
                root, hint_vars_vals=warm_hint, seed=seed,
                tier_time_limits=tier_time_limits, weights=weights, num_workers=num_workers,
                skip_tier1=True,
            )
        except RuntimeError:
            pass  # falls through to the LNS-only return below, same as "skipped"

    if lex is None:
        # Either phase 2 was skipped outright, or it ran but not even tier2
        # converged. If LNS itself committed at least one improvement,
        # that's still a real, validated, hard-constraint-clean result worth
        # returning -- better than discarding it because the LATER phase
        # didn't pan out (or never ran). Only report total failure if LNS
        # also never committed anything.
        if lns["solver"] is None:
            return {
                "status": "OPTIMIZE_FAILED", "hard_status": "REUSED", "soft_status": "UNKNOWN",
                "solver": None, "Start": None, "Teacher": None, "Room": None, "meta": None,
                "seed_used": seed, "objective": None,
                "hard_seconds": 0.0, "soft_seconds": lns_seconds,
                "tier_results": {}, "final_tier_reached": None,
                "lns_rounds": lns["rounds"], "lns_objective": lns["objective"],
                "lns_starting_objective": lns["starting_objective"], "lns_seconds": round(lns_seconds, 1),
            }
        return {
            "status": "FEASIBLE_SOFT", "hard_status": "REUSED", "soft_status": "LNS_ONLY",
            "solver": lns["solver"], "Start": lns["Start"], "Teacher": lns["Teacher"], "Room": lns["Room"],
            "meta": lns["meta"], "seed_used": seed, "objective": lns["objective"],
            "hard_seconds": 0.0, "soft_seconds": lns_seconds,
            "tier_results": {}, "final_tier_reached": "lns_gap_repair",
            "lns_rounds": lns["rounds"], "lns_objective": lns["objective"],
            "lns_starting_objective": lns["starting_objective"], "lns_seconds": round(lns_seconds, 1),
        }

    final_status = lex["tier_results"][lex["final_tier_reached"]]["status"]
    return {
        "status": "OPTIMAL_SOFT" if final_status == "OPTIMAL" else "FEASIBLE_SOFT",
        "hard_status": "REUSED", "soft_status": final_status,
        "solver": lex["solver"], "Start": lex["Start"], "Teacher": lex["Teacher"], "Room": lex["Room"],
        "meta": lex["meta"], "seed_used": seed,
        "objective": lex["tier_results"][lex["final_tier_reached"]]["objective"],
        "hard_seconds": 0.0, "soft_seconds": lns_seconds + lex["total_seconds"],
        "tier_results": lex["tier_results"], "final_tier_reached": lex["final_tier_reached"],
        "lns_rounds": lns["rounds"], "lns_objective": lns["objective"],
        "lns_starting_objective": lns["starting_objective"], "lns_seconds": round(lns_seconds, 1),
    }


def _offering_section_map(meta):
    return {o["offering_id"]: o["section_id"] for o in meta["offerings"]}


def _hint_rows_for_scoring(hint, meta):
    """Builds minimal {"section_id","day","slot_id"} dicts from a hint
    dict's Start entries, for gap_stats._occupancy/_segments to score
    against -- reuses the SAME independently-validated scoring logic
    Analytics/GET /api/report already use, so LNS ranks sections by the
    same definition of "bad" the rest of the app reports, not a fifth
    reimplementation that could disagree with what the user sees elsewhere."""
    idx_to_slot = meta["idx_to_slot"]
    slot_rows = {s["slot_id"]: s for s in meta["data"]["time_slots.csv"]}
    rows = []
    for o in meta["offerings"]:
        oid = o["offering_id"]
        for s in range(int(o["required_sessions"])):
            key = ("Start", (oid, s))
            if key not in hint:
                continue
            slot_id = idx_to_slot[hint[key]]
            sl = slot_rows.get(slot_id)
            if sl is None:
                continue
            rows.append({"section_id": o["section_id"], "day": sl["day"], "slot_id": slot_id})
    return rows


def _rank_sections_by_gap_score(hint, meta):
    """[(section_id, score)] sorted worst-first. score = total gaps + total
    isolated single-period runs across the section's week -- the same two
    quantities SC02_gaps/SC_isolated weight, so "worst section" here means
    the same thing it means to the CP-SAT objective."""
    from .gap_stats import _occupancy, _segments, _period_map
    rows = _hint_rows_for_scoring(hint, meta)
    slot_to_period, day_periods = _period_map(meta["data"]["time_slots.csv"])
    occ = _occupancy(rows, "section_id", slot_to_period)
    scores = {}
    for sec, by_day in occ.items():
        total = 0
        for day, periods in by_day.items():
            seg = _segments(periods, day_periods.get(day, []))
            if seg:
                total += seg["gaps"] + seg["isolated_runs"]
        scores[sec] = total
    # Sections with zero occupancy in `rows` (shouldn't happen for a real
    # dataset, but keeps the ranking total honest) score 0 implicitly by
    # being absent -- callers only care about sections with score > 0.
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def _section_gap_objective(model, Start, meta, target_section):
    """(gaps_expr, isolated_expr) for ONE section, built via the same
    _build_occupied + _gap_and_isolated_terms soft.py uses for the real
    SC02_gaps/SC_isolated objective -- scoped to a single section so the
    resulting CP-SAT model only needs that section's sessions to be free
    variables (everything else the caller pins separately)."""
    data = meta["data"]
    days = ["MON", "TUE", "WED", "THU", "FRI"]
    day_period_to_idx = {}
    for s in data["time_slots.csv"]:
        day_period_to_idx[(s["day"], int(s["period_number"]))] = meta["slot_to_idx"][s["slot_id"]]
    courses_by_id = {c["course_id"]: c for c in data["courses.csv"]}
    occ, _ = _build_occupied(model, Start, meta["offerings"], courses_by_id, data["time_slots.csv"],
                              meta["slot_to_idx"], [target_section], days, day_period_to_idx)
    gap_terms, isolated_terms = [], []
    for day in days:
        if not occ[target_section][day]:
            continue
        gaps, isolated = _gap_and_isolated_terms(model, occ[target_section], target_section, day)
        gap_terms.append(gaps)
        isolated_terms.extend(isolated)
    gaps_expr = sum(gap_terms) if gap_terms else 0
    isolated_expr = sum(isolated_terms) if isolated_terms else 0
    return gaps_expr, isolated_expr


def _clone_model(base_model):
    """Cheap protobuf-level copy of an already-built hard model, so LNS's
    per-round pin-and-resolve doesn't pay build_full_hard_model's ~1.3-3s
    Python-side rebuild (looping every course/offering emitting collision
    constraints) on every one of up to max_rounds rounds. Variable wrapper
    objects (Start/Teacher/Room) created against base_model stay valid for
    adding new constraints/hints on the clone -- OR-Tools only needs the
    var's index, not live model identity -- verified empirically: the
    cloned model solves correctly and base_model is left untouched.
    """
    new_model = cp_model.CpModel()
    new_model.Proto().copy_from(base_model.Proto())
    return new_model


def lns_gap_repair(root, base_csv_path, weights=None,
                    max_rounds=40, time_limits=(5.0, 15.0, 30.0),
                    num_workers=8):
    """Large Neighborhood Search gap repair -- borrows Lantiv Timetabling
    Turbo's OWN documented approach (rank violations, spend an escalating
    time budget fixing the worst one, requeue if unresolved, repeat -- see
    https://timetabling-turbo.lantiv.com/wiki/Turbo8-Automatic_Timetabling.html)
    while keeping CP-SAT as the actual solving engine for every repair step,
    so hard-constraint validity is proven at each step, not heuristically
    assumed the way a plain local-search move is.

    Unlike solve_lexicographic_soft's tier1 (jointly optimizes gap
    structure across EVERY section in one CP-SAT model -- expensive, and
    empirically got stuck with an unproven bound even after 240s on a
    32-section dataset), this repairs ONE section at a time: freeze every
    OTHER section's Start/Teacher/Room assignments as fixed equality
    constraints, leaving only the target section's own sessions free, and
    re-solve just that much smaller subproblem to minimize its own gap+
    isolated score. Each round is therefore cheap (a couple dozen free
    variables instead of thousands), so many rounds fit in the time one
    joint solve would take -- the same "many small fixes beat one huge
    one" idea Lantiv uses, but each fix is still a real, hard-constraint-
    respecting CP-SAT solve over the full model (with almost everything
    pinned), not a heuristic swap that could silently violate something.

    Algorithm per round:
      1. Score every section's current gap+isolated count and pick the
         worst one that hasn't already exhausted every time_limits entry.
      2. Build a fresh hard model, pin every offering NOT in that section
         to its current hint value, minimize (SC02_gaps + SC_isolated) for
         just that section, with an escalating time budget on repeat
         visits (mirrors Lantiv's 3s -> 15s -> ... escalation).
      3. If the new score is strictly better, commit it into the working
         hint. If not, mark that section "stuck at this time_limits index"
         so it isn't retried at the SAME budget again -- it can still be
         retried at the next, larger budget once every other section has
         had its turn there.
      4. Stop after max_rounds, when every section scores 0, or when no
         section has any budget left to try.

    Returns: status ("LNS_REPAIRED" if at least one round committed an
    improvement, "LNS_NO_CHANGE" if the input was already as good as this
    approach could get, or unchanged from the start), objective (final
    total gap+isolated score across all sections -- lower is better,
    directly comparable to the score computed on `base_csv_path` before
    running), solver/Start/Teacher/Room/meta from the last committed
    round's model (read the schedule from these), and `rounds`: a full log
    of every attempt for transparency -- never silently claims an
    improvement that didn't happen.
    """
    weights = weights or DEFAULT_WEIGHTS
    base_model, base_Start, base_Teacher, base_Room, meta_for_ids = build_full_hard_model(root)
    hint = hint_from_csv(base_csv_path, meta_for_ids)
    offering_section = _offering_section_map(meta_for_ids)

    def section_of(kind, key):
        return offering_section.get(key if kind == "Teacher" else key[0])

    starting_score = sum(score for _, score in _rank_sections_by_gap_score(hint, meta_for_ids))

    stuck_at_index = {}  # section_id -> highest time_limits index already tried and failed
    rounds_log = []
    last_model_bits = None
    seed_counter = 0

    for round_num in range(max_rounds):
        ranking = [(sec, score) for sec, score in _rank_sections_by_gap_score(hint, meta_for_ids) if score > 0]
        if not ranking:
            break  # every section is gap-and-isolation-free

        target = None
        for sec, score in ranking:
            next_idx = stuck_at_index.get(sec, -1) + 1
            if next_idx < len(time_limits):
                target = sec
                target_idx = next_idx
                break
        if target is None:
            break  # every remaining section has exhausted every time budget

        before_score = dict(ranking)[target]
        time_limit = time_limits[target_idx]

        model = _clone_model(base_model)
        Start, Teacher, Room, meta = base_Start, base_Teacher, base_Room, meta_for_ids
        for (kind, key), val in hint.items():
            var_dict = {"Start": Start, "Teacher": Teacher, "Room": Room}[kind]
            var = var_dict.get(key)
            if var is None:
                continue
            if section_of(kind, key) == target:
                model.AddHint(var, val)
            else:
                model.Add(var == val)

        gaps_expr, isolated_expr = _section_gap_objective(model, Start, meta, target)
        model.Minimize(weights.get("SC02_gaps", 10) * gaps_expr + weights.get("SC_isolated", 10) * isolated_expr)
        seed_counter += 1
        solver, status_code, dt = _solve_once(model, time_limit, seed_counter, num_workers)
        status = STATUS_NAMES.get(status_code, str(status_code))

        committed = False
        after_score = before_score
        if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            new_hint = dict(hint)
            for kind, var_dict in (("Start", Start), ("Teacher", Teacher), ("Room", Room)):
                for key, var in var_dict.items():
                    if section_of(kind, key) == target:
                        new_hint[(kind, key)] = solver.Value(var)
            after_score = dict(_rank_sections_by_gap_score(new_hint, meta_for_ids)).get(target, 0)
            if after_score < before_score:
                hint = new_hint
                committed = True
                stuck_at_index.pop(target, None)  # improved -- earns a fresh shot next time it's picked
                last_model_bits = (solver, Start, Teacher, Room, meta)

        if not committed:
            stuck_at_index[target] = target_idx

        rounds_log.append({
            "round": round_num, "section": target, "time_limit": time_limit, "status": status,
            "seconds": round(dt, 2), "before_score": before_score, "after_score": after_score,
            "committed": committed,
        })

    final_score = sum(score for _, score in _rank_sections_by_gap_score(hint, meta_for_ids))
    return {
        "status": "LNS_REPAIRED" if last_model_bits else "LNS_NO_CHANGE",
        "objective": final_score, "starting_objective": starting_score,
        "rounds": rounds_log,
        "solver": last_model_bits[0] if last_model_bits else None,
        "Start": last_model_bits[1] if last_model_bits else None,
        "Teacher": last_model_bits[2] if last_model_bits else None,
        "Room": last_model_bits[3] if last_model_bits else None,
        "meta": last_model_bits[4] if last_model_bits else None,
        "final_hint": hint,
    }
