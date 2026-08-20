"""CP7 – SOFT constraints (Round2 Part 15/16) – FIXED per prompt.

Implements weighted-sum objective, normalized, in priority order:
  1. SC02 student gaps (highest)
  2. SC01 faculty preference (preferred boolean)
  3. SC09/SC04 workload balance
  4. SC03 room wastage (lowest)

Soft terms live only in Minimize(...), never in Add(...).
"""
from ortools.sat.python import cp_model
from collections import defaultdict

# Priority weights as per prompt: SC02 > SC01 > SC09 > SC03
DEFAULT_WEIGHTS = {
    "SC02_gaps": 10,      # highest
    "SC01_pref": 8,       # second
    "SC09_balance": 5,    # third
    "SC03_wastage": 1,    # lowest
}

def _slot_to_day_period(slot_id, time_slots):
    for s in time_slots:
        if s["slot_id"]==slot_id:
            return s["day"], int(s["period_number"])
    return None, None

def add_soft_objective(model, Start, Teacher, Room, meta, weights=None):
    """Add soft penalties. Returns dict of penalty vars for reporting."""
    if weights is None:
        weights = DEFAULT_WEIGHTS
    data = meta["data"]
    offerings = meta["offerings"]
    slot_to_idx = meta["slot_to_idx"]
    idx_to_slot = meta["idx_to_slot"]
    fac_to_idx = meta["fac_to_idx"]
    idx_to_fac = meta["idx_to_fac"]
    room_to_idx = meta["room_to_idx"]
    # Maps
    courses_by_id = {c["course_id"]: c for c in data["courses.csv"]}
    rooms_by_id = {r["room_id"]: int(r["capacity"]) for r in data["rooms.csv"]}
    # Preferred faculty per course: set of faculty_id where preferred==True
    preferred_by_course = defaultdict(set)
    for r in data["faculty_courses.csv"]:
        if r["preferred"].lower()=="true":
            preferred_by_course[r["course_id"]].add(r["faculty_id"])

    penalties = {}
    terms = []

    # --- SC02: Minimize student gaps per section per day ---
    # Gaps = empty slots between first and last occupied that day
    # Build occupied Bool per section per day per period (1..7)
    # For each section, per day, create occupied[period] Bool
    sections = sorted(set(o["section_id"] for o in offerings))
    days = ["MON","TUE","WED","THU","FRI"]
    # Map (day, period) -> slot_idx
    day_period_to_idx = {}
    for s in data["time_slots.csv"]:
        day_period_to_idx[(s["day"], int(s["period_number"]))] = slot_to_idx[s["slot_id"]]

    total_gap_penalty = 0
    gap_vars = []
    for sec in sections:
        for day in days:
            # Collect sessions for this section
            sec_sessions = [(o["offering_id"], ss) for o in offerings if o["section_id"]==sec for ss in range(int(o["required_sessions"]))]
            if not sec_sessions:
                continue
            # Create occupied bool per period
            occupied = {}
            for period in range(1,8):
                occupied[period] = model.NewBoolVar(f"occ_{sec}_{day}_p{period}")
                # Link occupied to sessions that occupy this period
                # For each session, it occupies period p if Start == slot_idx(day,p) OR (duration2 and Start == slot_idx(day,p-1))
                # Build OR conditions
                affecting = []
                for (oid, s) in sec_sessions:
                    # Find course duration
                    o = next(o for o in offerings if o["offering_id"]==oid)
                    dur = int(courses_by_id[o["course_id"]]["session_duration"])
                    slot_idx_p = day_period_to_idx.get((day, period))
                    # Starts at p
                    b_start = model.NewBoolVar(f"is_{oid}_{s}_at_{day}_{period}")
                    if slot_idx_p is not None:
                        model.Add(Start[(oid,s)] == slot_idx_p).OnlyEnforceIf(b_start)
                        model.Add(Start[(oid,s)] != slot_idx_p).OnlyEnforceIf(b_start.Not())
                    else:
                        model.Add(b_start == 0)
                    affecting.append(b_start)
                    # For duration 2, also occupies if starts at p-1
                    if dur==2 and period>1:
                        prev_slot = day_period_to_idx.get((day, period-1))
                        if prev_slot is not None:
                            b_prev = model.NewBoolVar(f"is_{oid}_{s}_at_{day}_{period-1}_dur2")
                            model.Add(Start[(oid,s)] == prev_slot).OnlyEnforceIf(b_prev)
                            model.Add(Start[(oid,s)] != prev_slot).OnlyEnforceIf(b_prev.Not())
                            affecting.append(b_prev)
                # occupied = OR(affecting)
                if affecting:
                    model.AddMaxEquality(occupied[period], affecting)
                else:
                    model.Add(occupied[period] == 0)
            # Now compute gaps: need first and last occupied period
            # Create IntVar first, last in 1..7, with 0 meaning no class that day
            has_any = model.NewBoolVar(f"has_any_{sec}_{day}")
            # has_any = OR(occupied)
            model.AddMaxEquality(has_any, [occupied[p] for p in range(1,8)])
            first = model.NewIntVar(0, 7, f"first_{sec}_{day}")
            last = model.NewIntVar(0, 7, f"last_{sec}_{day}")
            # For has_any false, first/last =0
            # For has_any true, first = min period where occupied, last = max period where occupied
            # Use AddMinEquality / AddMaxEquality with trick: create array of periods where not occupied -> large value
            # Simpler: use linear with element? Use AddMinEquality over list of Ints where occupied true
            # Create vars period_if_occupied else 8 for min, else 0 for max
            min_candidates = []
            max_candidates = []
            for p in range(1,8):
                # If occupied, candidate = p else 8 (for min) / 0 (for max)
                cand_min = model.NewIntVar(1, 8, f"cand_min_{sec}_{day}_{p}")
                cand_max = model.NewIntVar(0, 7, f"cand_max_{sec}_{day}_{p}")
                # cand_min = p if occupied else 8
                model.Add(cand_min == p).OnlyEnforceIf(occupied[p])
                model.Add(cand_min == 8).OnlyEnforceIf(occupied[p].Not())
                min_candidates.append(cand_min)
                model.Add(cand_max == p).OnlyEnforceIf(occupied[p])
                model.Add(cand_max == 0).OnlyEnforceIf(occupied[p].Not())
                max_candidates.append(cand_max)
            model.AddMinEquality(first, min_candidates)
            model.AddMaxEquality(last, max_candidates)
            # When has_any false, first should be 0, last 0 -> adjust
            # Our min gives 8 when no occupied, we want 0
            # So create corrected first/last
            first_corr = model.NewIntVar(0, 7, f"firstc_{sec}_{day}")
            last_corr = model.NewIntVar(0, 7, f"lastc_{sec}_{day}")
            model.Add(first_corr == 0).OnlyEnforceIf(has_any.Not())
            model.Add(first_corr == first).OnlyEnforceIf(has_any)
            model.Add(last_corr == 0).OnlyEnforceIf(has_any.Not())
            model.Add(last_corr == last).OnlyEnforceIf(has_any)
            # Gaps = (last - first -1) - (occupied_count -2)?? Actually gaps = (last - first +1) - sum(occupied)
            # For has_any false, gaps 0
            occupied_sum = sum(occupied[p] for p in range(1,8))
            gaps = model.NewIntVar(0, 7, f"gaps_{sec}_{day}")
            # gaps = last - first +1 - occupied_sum, when has_any true, else 0
            # Use linear: gaps = last - first +1 - occupied_sum
            # For has_any false, we force gaps 0 via reify
            tmp = model.NewIntVar(-7, 7, f"tmp_gaps_{sec}_{day}")
            model.Add(tmp == last_corr - first_corr + 1 - occupied_sum)
            model.Add(gaps == tmp).OnlyEnforceIf(has_any)
            model.Add(gaps == 0).OnlyEnforceIf(has_any.Not())
            # Add to total
            if weights.get("SC02_gaps",0):
                total_gap_penalty += gaps
                gap_vars.append(gaps)
    if weights.get("SC02_gaps",0) and gap_vars:
        # Normalize: max gaps per section per day is at most 5, total max ~ 80*5=400, weight accordingly
        penalties["SC02"] = total_gap_penalty
        terms.append(weights["SC02_gaps"] * total_gap_penalty)

    # --- SC01: Faculty preference (preferred boolean) ---
    pref_penalty = model.NewIntVar(0, 1000, "pen_pref")
    pref_terms = []
    for o in offerings:
        oid = o["offering_id"]
        cid = o["course_id"]
        pref_set = preferred_by_course.get(cid, set())
        if not pref_set:
            continue
        # Create Bool is_preferred = Teacher in pref_set
        # For each preferred faculty, create Bool
        # is_pref = OR over (Teacher == fac_idx for fac in pref_set)
        is_pref = model.NewBoolVar(f"is_pref_{oid}")
        # Need to link: is_pref true iff Teacher in pref_set
        # Use AllowedAssignments: (Teacher) in pref_set => is_pref true
        pref_indices = [fac_to_idx[f] for f in pref_set if f in fac_to_idx]
        if not pref_indices:
            continue
        # Create alternative: is_pref ==1 => Teacher in pref_set
        # is_pref ==0 => Teacher not in pref_set
        # Use table with 2 vars: Teacher and is_pref
        allowed_pref = [(fi,1) for fi in pref_indices]
        # For not pref, need all non-pref eligible
        non_pref = [fac_to_idx[f] for f in meta["eligible"].get(cid, set()) if f not in pref_set]
        allowed_not = [(fi,0) for fi in non_pref]
        allowed_all = allowed_pref + allowed_not
        model.AddAllowedAssignments([Teacher[oid], is_pref], allowed_all)
        # Penalty = 1 - is_pref (1 if non-preferred)
        # Instead of per offering penalty 0/1, we can sum
        pref_terms.append(1 - is_pref)
    if pref_terms and weights.get("SC01_pref",0):
        # Sum of non-preferred assignments
        total_pref_pen = model.NewIntVar(0, len(offerings), "total_pref_pen")
        model.Add(total_pref_pen == sum(pref_terms))
        penalties["SC01"] = total_pref_pen
        terms.append(weights["SC01_pref"] * total_pref_pen)

    # --- SC09: Balance faculty workload (deviation from midpoint) ---
    # For each faculty, total_hours = sum dur * is_assigned
    fac_hours = {}
    for fac_id in fac_to_idx:
        # collect is_assigned bools already created in workload? We recreate
        # Instead compute total_hours similarly to workload, but we already have weekly_terms in full_model
        # For soft, we need total_hours var
        pass
    # Simplified: penalize total_hours deviation from midpoint (min+max)/2
    # Create total_hours per faculty as IntVar
    workload_penalties = []
    faculty_rows = {r["faculty_id"]: r for r in data["faculty.csv"]}
    for fac_id, fac_idx in fac_to_idx.items():
        min_w = int(faculty_rows[fac_id]["min_hours_per_week"])
        max_w = int(faculty_rows[fac_id]["max_hours_per_week"])
        mid = (min_w + max_w)//2
        # Compute total hours for this faculty (reuse logic from workload)
        terms_for_fac = []
        for o in offerings:
            if fac_id not in meta["eligible"].get(o["course_id"], set()):
                continue
            oid = o["offering_id"]
            dur = int(courses_by_id[o["course_id"]]["session_duration"])
            for s in range(int(o["required_sessions"])):
                is_ass = model.NewBoolVar(f"soft_is_{oid}_{s}_{fac_id}")
                model.Add(Teacher[oid] == fac_idx).OnlyEnforceIf(is_ass)
                model.Add(Teacher[oid] != fac_idx).OnlyEnforceIf(is_ass.Not())
                terms_for_fac.append(dur * is_ass)
        if not terms_for_fac:
            continue
        total = model.NewIntVar(0, 40, f"soft_total_{fac_id}")
        model.Add(total == sum(terms_for_fac))
        # Penalty = abs(total - mid)
        abs_pen = model.NewIntVar(0, 40, f"pen_work_{fac_id}")
        # abs via two constraints: abs_pen >= total - mid, abs_pen >= mid - total
        model.Add(abs_pen >= total - mid)
        model.Add(abs_pen >= mid - total)
        # Also need to ensure abs_pen is exactly abs? The objective will push it down, so >= is enough (minimization)
        if weights.get("SC09_balance",0):
            workload_penalties.append(abs_pen)
    if workload_penalties and weights.get("SC09_balance",0):
        total_work_pen = model.NewIntVar(0, 2000, "total_work_pen")
        model.Add(total_work_pen == sum(workload_penalties))
        penalties["SC09"] = total_work_pen
        terms.append(weights["SC09_balance"] * total_work_pen)

    # --- SC03: Room wastage (lowest) ---
    wastage_terms = []
    for o in offerings:
        oid = o["offering_id"]
        cnt = int(o["student_count"])
        for s in range(int(o["required_sessions"])):
            # wastage = capacity[Room] - cnt
            cap_var = model.NewIntVar(0, 200, f"cap_{oid}_{s}")
            # Use element: cap_var = element(room_idx -> capacity)
            # Create array of capacities indexed by room_idx
            all_room_ids_sorted = sorted(meta["room_to_idx"], key=lambda x: meta["room_to_idx"][x])
            # Actually room_to_idx maps room_id -> idx, we need reverse sorted by idx
            idx_to_room_sorted = [None]*len(all_room_ids_sorted)
            for rid, idx in meta["room_to_idx"].items():
                idx_to_room_sorted[idx]=rid
            caps = [rooms_by_id[rid] for rid in idx_to_room_sorted]
            model.AddElement(Room[(oid,s)], caps, cap_var)
            waste = model.NewIntVar(0, 200, f"waste_{oid}_{s}")
            model.Add(waste == cap_var - cnt)
            # Ensure non-negative (capacity always >= cnt due to domain, so waste >=0)
            wastage_terms.append(waste)
    if wastage_terms and weights.get("SC03_wastage",0):
        total_waste = model.NewIntVar(0, 10000, "total_waste")
        model.Add(total_waste == sum(wastage_terms))
        penalties["SC03"] = total_waste
        terms.append(weights["SC03_wastage"] * total_waste)

    if terms:
        model.Minimize(sum(terms))
    return penalties

def apply_human_feedback(current_weights, feedback):
    new_weights = current_weights.copy()
    for k,v in feedback.items():
        if k in new_weights and isinstance(v, (int,float)):
            new_weights[k]=v
    comment = feedback.get("comment","").lower()
    if "gap" in comment:
        new_weights["SC02_gaps"] = new_weights.get("SC02_gaps",10)+2
    if "waste" in comment or "room" in comment:
        new_weights["SC03_wastage"] = new_weights.get("SC03_wastage",1)+1
    if "prefer" in comment:
        new_weights["SC01_pref"] = new_weights.get("SC01_pref",8)+1
    if "balance" in comment or "workload" in comment:
        new_weights["SC09_balance"] = new_weights.get("SC09_balance",5)+1
    return new_weights
