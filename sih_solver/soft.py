"""CP7 – SOFT constraints (Round2 Part 15/16) – FIXED per prompt + item 5.

Implements weighted-sum objective, normalized, in priority order:
  1. SC02 student gaps (highest)
  2. SC01 faculty preference (preferred boolean)
  3. SC09/SC04 workload balance
  4. SC05 excessive consecutive periods
  5. SC06 spread distinct days
  6. SC03 room wastage (lowest)

Soft terms live only in Minimize(...), never in Add(...).
"""
from ortools.sat.python import cp_model
from collections import defaultdict

# Priority weights as per prompt: SC02 > SC01 > SC09 > SC03
DEFAULT_WEIGHTS = {
    "SC02_gaps": 10,      # highest
    "SC01_pref": 8,       # second
    "SC09_balance": 5,    # third
    "SC05_consecutive": 4,
    "SC06_spread": 4,
    "SC08_undesirable": 2,
    "SC11_building": 2,
    "SC_facgaps": 2,
    "SC03_wastage": 1,    # lowest
}

def _slot_to_day_period(slot_id, time_slots):
    for s in time_slots:
        if s["slot_id"]==slot_id:
            return s["day"], int(s["period_number"])
    return None, None

def _build_occupied(model, Start, offerings, courses_by_id, time_slots, slot_to_idx,
                    sections, days, day_period_to_idx):
    """Return occ[sec][day][period] BoolVar = section has a session occupying that
    (day, period). Also returns affecting list per period (for building/room lookups)."""
    occ = {sec: {d: {} for d in days} for sec in sections}
    affecting = {sec: {d: {} for d in days} for sec in sections}
    for sec in sections:
        sec_sessions = [(o["offering_id"], ss) for o in offerings if o["section_id"]==sec
                        for ss in range(int(o["required_sessions"]))]
        if not sec_sessions:
            continue
        for day in days:
            for period in range(1, 8):
                aff = []
                for (oid, s) in sec_sessions:
                    o = next(o for o in offerings if o["offering_id"]==oid)
                    dur = int(courses_by_id[o["course_id"]]["session_duration"])
                    slot_idx_p = day_period_to_idx.get((day, period))
                    b_start = model.NewBoolVar(f"is_{oid}_{s}_at_{day}_{period}")
                    if slot_idx_p is not None:
                        model.Add(Start[(oid,s)] == slot_idx_p).OnlyEnforceIf(b_start)
                        model.Add(Start[(oid,s)] != slot_idx_p).OnlyEnforceIf(b_start.Not())
                    else:
                        model.Add(b_start == 0)
                    aff.append(b_start)
                    if dur==2 and period>1:
                        prev_slot = day_period_to_idx.get((day, period-1))
                        if prev_slot is not None:
                            b_prev = model.NewBoolVar(f"is_{oid}_{s}_at_{day}_{period-1}_dur2")
                            model.Add(Start[(oid,s)] == prev_slot).OnlyEnforceIf(b_prev)
                            model.Add(Start[(oid,s)] != prev_slot).OnlyEnforceIf(b_prev.Not())
                            aff.append(b_prev)
                o = model.NewBoolVar(f"occ_{sec}_{day}_p{period}")
                if aff:
                    model.AddMaxEquality(o, aff)
                else:
                    model.Add(o == 0)
                occ[sec][day][period] = o
                affecting[sec][day][period] = aff
    return occ, affecting

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
    courses_by_id = {c["course_id"]: c for c in data["courses.csv"]}
    rooms_by_id = {r["room_id"]: r for r in data["rooms.csv"]}
    preferred_by_course = defaultdict(set)
    for r in data["faculty_courses.csv"]:
        if r["preferred"].lower()=="true":
            preferred_by_course[r["course_id"]].add(r["faculty_id"])

    penalties = {}
    terms = []
    sections = sorted(set(o["section_id"] for o in offerings))
    days = ["MON","TUE","WED","THU","FRI"]
    day_period_to_idx = {}
    for s in data["time_slots.csv"]:
        day_period_to_idx[(s["day"], int(s["period_number"]))] = slot_to_idx[s["slot_id"]]

    # Shared occupied bools for section-based soft terms
    occ, affecting = _build_occupied(model, Start, offerings, courses_by_id,
                                      data["time_slots.csv"], slot_to_idx,
                                      sections, days, day_period_to_idx)

    # --- SC02: Minimize student gaps per section per day ---
    total_gap_penalty = 0
    gap_vars = []
    for sec in sections:
        for day in days:
            if not occ[sec][day]:
                continue
            occupied = occ[sec][day]
            has_any = model.NewBoolVar(f"has_any_{sec}_{day}")
            model.AddMaxEquality(has_any, [occupied[p] for p in range(1,8)])
            first = model.NewIntVar(0, 8, f"first_{sec}_{day}")
            last = model.NewIntVar(0, 8, f"last_{sec}_{day}")
            min_candidates = []
            max_candidates = []
            for p in range(1,8):
                cand_min = model.NewIntVar(1, 8, f"cand_min_{sec}_{day}_{p}")
                cand_max = model.NewIntVar(0, 7, f"cand_max_{sec}_{day}_{p}")
                model.Add(cand_min == p).OnlyEnforceIf(occupied[p])
                model.Add(cand_min == 8).OnlyEnforceIf(occupied[p].Not())
                min_candidates.append(cand_min)
                model.Add(cand_max == p).OnlyEnforceIf(occupied[p])
                model.Add(cand_max == 0).OnlyEnforceIf(occupied[p].Not())
                max_candidates.append(cand_max)
            model.AddMinEquality(first, min_candidates)
            model.AddMaxEquality(last, max_candidates)
            first_corr = model.NewIntVar(0, 7, f"firstc_{sec}_{day}")
            last_corr = model.NewIntVar(0, 7, f"lastc_{sec}_{day}")
            model.Add(first_corr == 0).OnlyEnforceIf(has_any.Not())
            model.Add(first_corr == first).OnlyEnforceIf(has_any)
            model.Add(last_corr == 0).OnlyEnforceIf(has_any.Not())
            model.Add(last_corr == last).OnlyEnforceIf(has_any)
            occupied_sum = sum(occupied[p] for p in range(1,8))
            gaps = model.NewIntVar(0, 7, f"gaps_{sec}_{day}")
            tmp = model.NewIntVar(-7, 7, f"tmp_gaps_{sec}_{day}")
            model.Add(tmp == last_corr - first_corr + 1 - occupied_sum)
            model.Add(gaps == tmp).OnlyEnforceIf(has_any)
            model.Add(gaps == 0).OnlyEnforceIf(has_any.Not())
            if weights.get("SC02_gaps",0):
                total_gap_penalty += gaps
                gap_vars.append(gaps)
    if weights.get("SC02_gaps",0) and gap_vars:
        penalties["SC02"] = total_gap_penalty
        terms.append(weights["SC02_gaps"] * total_gap_penalty)

    # --- SC05: excessive consecutive periods (window of 3+ occupied) per section/day ---
    if weights.get("SC05_consecutive",0):
        consec_terms = []
        for sec in sections:
            for day in days:
                if not occ[sec][day]:
                    continue
                occupied = occ[sec][day]
                for p in range(2, 7):
                    triple = model.NewBoolVar(f"triple_{sec}_{day}_{p}")
                    model.AddBoolAnd([occupied[p-1], occupied[p], occupied[p+1]]).OnlyEnforceIf(triple)
                    model.AddBoolOr([occupied[p-1].Not(), occupied[p].Not(), occupied[p+1].Not()]).OnlyEnforceIf(triple.Not())
                    consec_terms.append(triple)
        if consec_terms:
            total_consec = model.NewIntVar(0, len(consec_terms), "total_consec")
            model.Add(total_consec == sum(consec_terms))
            penalties["SC05"] = total_consec
            terms.append(weights["SC05_consecutive"] * total_consec)

    # --- SC06: spread same course across distinct days (per section, course) ---
    if weights.get("SC06_spread",0):
        spread_terms = []
        # group single-duration sessions per (section, course)
        groups = defaultdict(list)
        for o in offerings:
            cid = o["course_id"]
            if int(courses_by_id[cid]["sessions_per_week"]) > 1 and int(courses_by_id[cid]["session_duration"]) == 1:
                for ss in range(int(o["required_sessions"])):
                    groups[(o["section_id"], cid)].append((o["offering_id"], ss))
        for (sec, cid), sess_list in groups.items():
            if len(sess_list) <= 1:
                continue
            day_bools = []
            for day in days:
                # any session of this group on this day? = occ[sec][day][p] for the group's sessions
                any_day = model.NewBoolVar(f"spread_{sec}_{cid}_{day}")
                conds = []
                for (oid, s) in sess_list:
                    for p in range(1,8):
                        # this session occupies (day,p)? affecting var
                        aff = affecting[sec][day].get(p, [])
                        # find the bool for this specific session at this period
                        for b in aff:
                            conds.append(b)
                if conds:
                    model.AddMaxEquality(any_day, conds)
                else:
                    model.Add(any_day == 0)
                day_bools.append(any_day)
            distinct = model.NewIntVar(0, 5, f"distinct_{sec}_{cid}")
            model.Add(distinct == sum(day_bools))
            # ideal distinct days = len(sess_list) (<=5). penalty = max(0, len - distinct)
            pen = model.NewIntVar(0, 5, f"pen_spread_{sec}_{cid}")
            model.Add(pen >= len(sess_list) - distinct)
            spread_terms.append(pen)
        if spread_terms:
            total_spread = model.NewIntVar(0, len(spread_terms)*5, "total_spread")
            model.Add(total_spread == sum(spread_terms))
            penalties["SC06"] = total_spread
            terms.append(weights["SC06_spread"] * total_spread)

    # --- SC08: undesirable slots (first and last period of each day) ---
    if weights.get("SC08_undesirable",0):
        und_terms = []
        und_slots = set()
        for s in data["time_slots.csv"]:
            if int(s["period_number"]) in (1, 7):
                und_slots.add(slot_to_idx[s["slot_id"]])
        for o in offerings:
            oid = o["offering_id"]
            for s in range(int(o["required_sessions"])):
                is_und = model.NewBoolVar(f"und_{oid}_{s}")
                model.AddAllowedAssignments([Start[(oid,s)]], [(v,) for v in und_slots]).OnlyEnforceIf(is_und)
                not_und = [v for v in slot_to_idx.values() if v not in und_slots]
                if not_und:
                    model.AddAllowedAssignments([Start[(oid,s)]], [(v,) for v in not_und]).OnlyEnforceIf(is_und.Not())
                und_terms.append(is_und)
        total_und = model.NewIntVar(0, len(und_terms), "total_und")
        model.Add(total_und == sum(und_terms))
        penalties["SC08"] = total_und
        terms.append(weights["SC08_undesirable"] * total_und)

    # --- SC03b / SC_facgaps: faculty idle gaps per day ---
    if weights.get("SC_facgaps",0):
        fac_gap_terms = []
        faculty_rows = {r["faculty_id"]: r for r in data["faculty.csv"]}
        # per faculty, per day: occupied periods via Teacher assignment
        fac_to_idx_map = fac_to_idx
        # hoist: is_ass per (faculty, offering, session) reused across days/periods
        is_ass_lut = {}
        for o in offerings:
            oid = o["offering_id"]
            dur = int(courses_by_id[o["course_id"]]["session_duration"])
            eligible_fac = meta["eligible"].get(o["course_id"], set())
            for s in range(int(o["required_sessions"])):
                for fac_id in eligible_fac:
                    fac_idx = fac_to_idx_map[fac_id]
                    is_ass = model.NewBoolVar(f"fass_{oid}_{s}_{fac_id}")
                    model.Add(Teacher[oid] == fac_idx).OnlyEnforceIf(is_ass)
                    model.Add(Teacher[oid] != fac_idx).OnlyEnforceIf(is_ass.Not())
                    is_ass_lut[(oid, s, fac_id)] = is_ass
        for fac_id, fac_idx in fac_to_idx_map.items():
            for day in days:
                occ_bools = []
                for p in range(1,8):
                    b = model.NewBoolVar(f"focc_{fac_id}_{day}_{p}")
                    conds = []
                    slot_idx_p = day_period_to_idx.get((day, p))
                    for o in offerings:
                        if fac_id not in meta["eligible"].get(o["course_id"], set()):
                            continue
                        oid = o["offering_id"]
                        dur = int(courses_by_id[o["course_id"]]["session_duration"])
                        for s in range(int(o["required_sessions"])):
                            is_ass = is_ass_lut[(oid, s, fac_id)]
                            if slot_idx_p is not None:
                                b_start = model.NewBoolVar(f"fass_{oid}_{s}_at_{day}_{p}")
                                model.Add(Start[(oid,s)] == slot_idx_p).OnlyEnforceIf(b_start)
                                model.Add(Start[(oid,s)] != slot_idx_p).OnlyEnforceIf(b_start.Not())
                                conj = model.NewBoolVar(f"fass_ab_{oid}_{s}_{day}_{p}")
                                model.AddBoolAnd([is_ass, b_start]).OnlyEnforceIf(conj)
                                model.AddBoolOr([is_ass.Not(), b_start.Not()]).OnlyEnforceIf(conj.Not())
                                conds.append(conj)
                            if dur==2 and p>1:
                                prev_slot = day_period_to_idx.get((day, p-1))
                                if prev_slot is not None:
                                    b_prev = model.NewBoolVar(f"fass_{oid}_{s}_at_{day}_{p-1}_dur2")
                                    model.Add(Start[(oid,s)] == prev_slot).OnlyEnforceIf(b_prev)
                                    model.Add(Start[(oid,s)] != prev_slot).OnlyEnforceIf(b_prev.Not())
                                    conj = model.NewBoolVar(f"fass_ab_{oid}_{s}_{day}_{p}_2")
                                    model.AddBoolAnd([is_ass, b_prev]).OnlyEnforceIf(conj)
                                    model.AddBoolOr([is_ass.Not(), b_prev.Not()]).OnlyEnforceIf(conj.Not())
                                    conds.append(conj)
                    if conds:
                        model.AddMaxEquality(b, conds)
                    else:
                        model.Add(b == 0)
                    occ_bools.append(b)
                # gaps for this faculty/day using same min/max technique
                has_any = model.NewBoolVar(f"fhas_{fac_id}_{day}")
                model.AddMaxEquality(has_any, occ_bools)
                first = model.NewIntVar(0, 8, f"ffirst_{fac_id}_{day}")
                last = model.NewIntVar(0, 8, f"flast_{fac_id}_{day}")
                min_candidates = []
                max_candidates = []
                for p in range(1,8):
                    cand_min = model.NewIntVar(1, 8, f"fcmin_{fac_id}_{day}_{p}")
                    cand_max = model.NewIntVar(0, 7, f"fcmax_{fac_id}_{day}_{p}")
                    model.Add(cand_min == p).OnlyEnforceIf(occ_bools[p-1])
                    model.Add(cand_min == 8).OnlyEnforceIf(occ_bools[p-1].Not())
                    min_candidates.append(cand_min)
                    model.Add(cand_max == p).OnlyEnforceIf(occ_bools[p-1])
                    model.Add(cand_max == 0).OnlyEnforceIf(occ_bools[p-1].Not())
                    max_candidates.append(cand_max)
                model.AddMinEquality(first, min_candidates)
                model.AddMaxEquality(last, max_candidates)
                first_corr = model.NewIntVar(0, 7, f"ffirstc_{fac_id}_{day}")
                last_corr = model.NewIntVar(0, 7, f"flastc_{fac_id}_{day}")
                model.Add(first_corr == 0).OnlyEnforceIf(has_any.Not())
                model.Add(first_corr == first).OnlyEnforceIf(has_any)
                model.Add(last_corr == 0).OnlyEnforceIf(has_any.Not())
                model.Add(last_corr == last).OnlyEnforceIf(has_any)
                occ_sum = sum(occ_bools)
                gaps = model.NewIntVar(0, 7, f"fgaps_{fac_id}_{day}")
                tmp = model.NewIntVar(-7, 7, f"ftmp_{fac_id}_{day}")
                model.Add(tmp == last_corr - first_corr + 1 - occ_sum)
                model.Add(gaps == tmp).OnlyEnforceIf(has_any)
                model.Add(gaps == 0).OnlyEnforceIf(has_any.Not())
                fac_gap_terms.append(gaps)
        if fac_gap_terms:
            total_fgaps = model.NewIntVar(0, len(fac_gap_terms)*7, "total_fgaps")
            model.Add(total_fgaps == sum(fac_gap_terms))
            penalties["SC_facgaps"] = total_fgaps
            terms.append(weights["SC_facgaps"] * total_fgaps)

    # --- SC11: building movement (section has consecutive periods in different buildings) ---
    if weights.get("SC11_building",0):
        building_idx = {}
        building_list = sorted({r["building"].strip() for r in rooms_by_id.values() if r.get("building")})
        for i, b in enumerate(building_list):
            building_idx[b] = i + 1  # 0 = unoccupied
        room_building_idx = {}
        for r in rooms_by_id.values():
            room_building_idx[r["room_id"]] = building_idx.get(r["building"].strip(), 0)
        all_room_ids = sorted(meta["room_to_idx"], key=lambda x: meta["room_to_idx"][x])
        building_arr = [room_building_idx[rid] for rid in all_room_ids]
        move_terms = []
        for sec in sections:
            for day in days:
                if not occ[sec][day]:
                    continue
                # building var per period
                building_at = {}
                for p in range(1,8):
                    bvar = model.NewIntVar(0, max(building_idx.values()) or 1, f"build_{sec}_{day}_{p}")
                    # building var = element over Room for the session that occupies p
                    # (HC03 guarantees at most one session per (sec, day, period)).
                    cand_build = []
                    for o in offerings:
                        if o["section_id"] != sec:
                            continue
                        oid = o["offering_id"]
                        dur = int(courses_by_id[o["course_id"]]["session_duration"])
                        for ss in range(int(o["required_sessions"])):
                            s_p = day_period_to_idx.get((day, p))
                            s_prev = day_period_to_idx.get((day, p-1))
                            occ_b = None
                            if dur==1 and s_p is not None:
                                b_start = model.NewBoolVar(f"bocc_{oid}_{ss}_{day}_{p}")
                                model.Add(Start[(oid,ss)] == s_p).OnlyEnforceIf(b_start)
                                model.Add(Start[(oid,ss)] != s_p).OnlyEnforceIf(b_start.Not())
                                occ_b = b_start
                            elif dur==2:
                                # occupies p if it starts at p (first half) or at p-1 (second half)
                                conds = []
                                if s_p is not None:
                                    b1 = model.NewBoolVar(f"bocc2a_{oid}_{ss}_{day}_{p}")
                                    model.Add(Start[(oid,ss)] == s_p).OnlyEnforceIf(b1)
                                    model.Add(Start[(oid,ss)] != s_p).OnlyEnforceIf(b1.Not())
                                    conds.append(b1)
                                if p>1 and s_prev is not None:
                                    b2 = model.NewBoolVar(f"bocc2b_{oid}_{ss}_{day}_{p}")
                                    model.Add(Start[(oid,ss)] == s_prev).OnlyEnforceIf(b2)
                                    model.Add(Start[(oid,ss)] != s_prev).OnlyEnforceIf(b2.Not())
                                    conds.append(b2)
                                if conds:
                                    occ_b = model.NewBoolVar(f"bocc2_{oid}_{ss}_{day}_{p}")
                                    model.AddMaxEquality(occ_b, conds)
                            if occ_b is not None:
                                raw_bld = model.NewIntVar(0, max(building_idx.values()) or 1, f"rawbld_{oid}_{ss}_{day}_{p}")
                                model.AddElement(Room[(oid,ss)], building_arr, raw_bld)
                                bld = model.NewIntVar(0, max(building_idx.values()) or 1, f"bld_{oid}_{ss}_{day}_{p}")
                                model.Add(bld == raw_bld).OnlyEnforceIf(occ_b)
                                model.Add(bld == 0).OnlyEnforceIf(occ_b.Not())
                                cand_build.append((occ_b, bld))
                    if cand_build:
                        model.Add(bvar == sum(bld for _, bld in cand_build))
                    else:
                        model.Add(bvar == 0)
                    building_at[p] = bvar
                # movement penalty for consecutive periods with different nonzero buildings
                for p in range(1,7):
                    both = model.NewBoolVar(f"both_{sec}_{day}_{p}")
                    model.AddBoolAnd([occ[sec][day][p], occ[sec][day][p+1]]).OnlyEnforceIf(both)
                    model.AddBoolOr([occ[sec][day][p].Not(), occ[sec][day][p+1].Not()]).OnlyEnforceIf(both.Not())
                    diff = model.NewBoolVar(f"diff_{sec}_{day}_{p}")
                    model.Add(building_at[p] != building_at[p+1]).OnlyEnforceIf(diff)
                    model.Add(building_at[p] == building_at[p+1]).OnlyEnforceIf(diff.Not())
                    move = model.NewBoolVar(f"move_{sec}_{day}_{p}")
                    model.AddBoolAnd([both, diff]).OnlyEnforceIf(move)
                    model.AddBoolOr([both.Not(), diff.Not()]).OnlyEnforceIf(move.Not())
                    move_terms.append(move)
        if move_terms:
            total_move = model.NewIntVar(0, len(move_terms), "total_move")
            model.Add(total_move == sum(move_terms))
            penalties["SC11"] = total_move
            terms.append(weights["SC11_building"] * total_move)

    # --- SC01: Faculty preference (preferred boolean) ---
    if weights.get("SC01_pref",0):
        pref_terms = []
        for o in offerings:
            oid = o["offering_id"]
            cid = o["course_id"]
            pref_set = preferred_by_course.get(cid, set())
            if not pref_set:
                continue
            is_pref = model.NewBoolVar(f"is_pref_{oid}")
            pref_indices = [fac_to_idx[f] for f in pref_set if f in fac_to_idx]
            if not pref_indices:
                continue
            allowed_pref = [(fi,1) for fi in pref_indices]
            non_pref = [fac_to_idx[f] for f in meta["eligible"].get(cid, set()) if f not in pref_set]
            allowed_not = [(fi,0) for fi in non_pref]
            allowed_all = allowed_pref + allowed_not
            model.AddAllowedAssignments([Teacher[oid], is_pref], allowed_all)
            pref_terms.append(1 - is_pref)
        if pref_terms:
            total_pref_pen = model.NewIntVar(0, len(offerings), "total_pref_pen")
            model.Add(total_pref_pen == sum(pref_terms))
            penalties["SC01"] = total_pref_pen
            terms.append(weights["SC01_pref"] * total_pref_pen)

    # --- SC09: Balance faculty workload (deviation from midpoint) ---
    if weights.get("SC09_balance",0):
        workload_penalties = []
        faculty_rows = {r["faculty_id"]: r for r in data["faculty.csv"]}
        for fac_id, fac_idx in fac_to_idx.items():
            min_w = int(faculty_rows[fac_id]["min_hours_per_week"])
            max_w = int(faculty_rows[fac_id]["max_hours_per_week"])
            mid = (min_w + max_w)//2
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
            abs_pen = model.NewIntVar(0, 40, f"pen_work_{fac_id}")
            model.Add(abs_pen >= total - mid)
            model.Add(abs_pen >= mid - total)
            workload_penalties.append(abs_pen)
        if workload_penalties:
            total_work_pen = model.NewIntVar(0, 2000, "total_work_pen")
            model.Add(total_work_pen == sum(workload_penalties))
            penalties["SC09"] = total_work_pen
            terms.append(weights["SC09_balance"] * total_work_pen)

    # --- SC03: Room wastage (lowest) ---
    if weights.get("SC03_wastage",0):
        wastage_terms = []
        for o in offerings:
            oid = o["offering_id"]
            cnt = int(o["student_count"])
            for s in range(int(o["required_sessions"])):
                cap_var = model.NewIntVar(0, 200, f"cap_{oid}_{s}")
                all_room_ids_sorted = sorted(meta["room_to_idx"], key=lambda x: meta["room_to_idx"][x])
                idx_to_room_sorted = [None]*len(all_room_ids_sorted)
                for rid, idx in meta["room_to_idx"].items():
                    idx_to_room_sorted[idx]=rid
                caps = [int(rooms_by_id[rid]["capacity"]) for rid in idx_to_room_sorted]
                model.AddElement(Room[(oid,s)], caps, cap_var)
                waste = model.NewIntVar(0, 200, f"waste_{oid}_{s}")
                model.Add(waste >= cap_var - cnt)
                # waste >=0 already via domain; minimizing pushes it to max(0, cap-cnt)
                wastage_terms.append(waste)
        if wastage_terms:
            total_waste = model.NewIntVar(0, 200*len(wastage_terms), "total_waste")
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
    if "consecutive" in comment:
        new_weights["SC05_consecutive"] = new_weights.get("SC05_consecutive",4)+1
    if "spread" in comment or "day" in comment:
        new_weights["SC06_spread"] = new_weights.get("SC06_spread",4)+1
    if "undesirable" in comment:
        new_weights["SC08_undesirable"] = new_weights.get("SC08_undesirable",2)+1
    if "building" in comment or "movement" in comment:
        new_weights["SC11_building"] = new_weights.get("SC11_building",2)+1
    return new_weights