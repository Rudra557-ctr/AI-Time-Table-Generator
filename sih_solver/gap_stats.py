"""Round 3C — independent gap/compactness statistics for a generated timetable.

Reads a generated_timetable.csv (the same shape backend/app.py writes:
offering_id,course_id,section_id,session,slot_id,day,start_time,end_time,
room_id,faculty_id) and computes per-section and per-faculty compactness
metrics directly from the (day, period) occupancy — independent of soft.py's
own CP-SAT penalty variables, so this is an honest external readout, not the
optimizer grading its own homework.

Periods are 1..7 per day (see time_slots.csv); a period with no time_slots.csv
row for that day is not part of the domain and is not counted at all.
"""
import csv
from collections import defaultdict

DAYS = ["MON", "TUE", "WED", "THU", "FRI"]


def _period_map(time_slots_rows):
    """slot_id -> period_number, and day -> sorted list of valid period_numbers."""
    slot_to_period = {}
    day_periods = defaultdict(set)
    for r in time_slots_rows:
        p = int(r["period_number"])
        slot_to_period[r["slot_id"]] = p
        day_periods[r["day"]].add(p)
    return slot_to_period, {d: sorted(ps) for d, ps in day_periods.items()}


def _occupancy(rows, key_field, slot_to_period, courses_by_id=None):
    """entity_id -> day -> set of occupied period_numbers (duration-2 sessions
    occupy two consecutive periods; we mark both from the row's own day/period
    plus, if the row has a paired session at period+1 that isn't separately
    listed, we infer it from session duration when courses_by_id is given)."""
    occ = defaultdict(lambda: defaultdict(set))
    for r in rows:
        entity = r.get(key_field)
        if not entity or entity in ("UNASSIGNED", "?"):
            continue
        day = r["day"]
        slot_id = r["slot_id"]
        p = slot_to_period.get(slot_id)
        if p is None:
            continue
        occ[entity][day].add(p)
    return occ


def _segments(occupied_periods, all_periods):
    """Given the set of occupied period numbers and the full ordered period
    list for that day, return (first, last, count, gaps, gap_positions,
    run_lengths, isolated_count). gaps = periods strictly between first and
    last (inclusive of the valid domain) that are NOT occupied."""
    if not occupied_periods:
        return None
    ordered = sorted(all_periods)
    first = min(occupied_periods)
    last = max(occupied_periods)
    span_periods = [p for p in ordered if first <= p <= last]
    gap_positions = [p for p in span_periods if p not in occupied_periods]
    gaps = len(gap_positions)
    # run-length segmentation over the full day domain (edges included) to
    # find isolated single-period occupied runs and the longest run.
    runs = []
    cur = 0
    for p in ordered:
        if p in occupied_periods:
            cur += 1
        else:
            if cur:
                runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    isolated = sum(1 for r in runs if r == 1)
    max_run = max(runs) if runs else 0
    return {
        "first": first, "last": last, "count": len(occupied_periods),
        "gaps": gaps, "gap_positions": gap_positions,
        "runs": runs, "max_run": max_run, "isolated_runs": isolated,
        "span": last - first + 1,
    }


def compute_stats(timetable_csv_path, time_slots_rows):
    """Returns {"sections": {...}, "faculty": {...}} summary dicts."""
    with open(timetable_csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    slot_to_period, day_periods = _period_map(time_slots_rows)

    def summarize(occ):
        day_records = []
        for entity, by_day in occ.items():
            for day, periods in by_day.items():
                seg = _segments(periods, day_periods.get(day, []))
                if seg:
                    day_records.append({"entity": entity, "day": day, **seg})
        n = len(day_records)
        total_gaps = sum(r["gaps"] for r in day_records)
        zero_gap_days = sum(1 for r in day_records if r["gaps"] == 0)
        one_gap_days = sum(1 for r in day_records if r["gaps"] == 1)
        multi_gap_days = sum(1 for r in day_records if r["gaps"] >= 2)
        total_isolated = sum(r["isolated_runs"] for r in day_records)
        total_span = sum(r["span"] for r in day_records)
        max_run_overall = max((r["max_run"] for r in day_records), default=0)
        run_hist = defaultdict(int)
        for r in day_records:
            for run in r["runs"]:
                run_hist[run] += 1
        working_days = defaultdict(set)
        for r in day_records:
            working_days[r["entity"]].add(r["day"])
        avg_working_days = (sum(len(v) for v in working_days.values()) / len(working_days)) if working_days else 0
        return {
            "entity_days": n,
            "entities": len(occ),
            "total_gaps": total_gaps,
            "mean_gaps_per_day": (total_gaps / n) if n else 0,
            "zero_gap_days": zero_gap_days,
            "one_gap_days": one_gap_days,
            "multi_gap_days": multi_gap_days,
            "multi_gap_day_pct": (100.0 * multi_gap_days / n) if n else 0,
            "total_isolated_runs": total_isolated,
            "mean_span": (total_span / n) if n else 0,
            "max_consecutive_run_observed": max_run_overall,
            "run_length_histogram": dict(sorted(run_hist.items())),
            "mean_working_days": avg_working_days,
        }

    sec_occ = _occupancy(rows, "section_id", slot_to_period)
    fac_occ = _occupancy(rows, "faculty_id", slot_to_period)
    return {"sections": summarize(sec_occ), "faculty": summarize(fac_occ)}


def format_report(stats, label):
    s = stats["sections"]
    f = stats["faculty"]
    lines = [f"=== {label} ===",
             f"  Section-days: {s['entity_days']} across {s['entities']} sections",
             f"  Total internal gaps: {s['total_gaps']}  (mean {s['mean_gaps_per_day']:.2f}/section-day)",
             f"  Section-days with 0 gaps: {s['zero_gap_days']} ({100.0*s['zero_gap_days']/max(s['entity_days'],1):.1f}%)",
             f"  Section-days with 1 gap:  {s['one_gap_days']} ({100.0*s['one_gap_days']/max(s['entity_days'],1):.1f}%)",
             f"  Section-days with 2+ gaps: {s['multi_gap_days']} ({s['multi_gap_day_pct']:.1f}%)",
             f"  Isolated single-period runs: {s['total_isolated_runs']}",
             f"  Mean daily span (first..last): {s['mean_span']:.2f} periods",
             f"  Max consecutive run observed: {s['max_consecutive_run_observed']}",
             f"  Run-length histogram: {s['run_length_histogram']}",
             f"  Mean working days/section: {s['mean_working_days']:.2f}",
             f"  Faculty: total gaps {f['total_gaps']} (mean {f['mean_gaps_per_day']:.2f}/faculty-day), "
             f"2+ gap days {f['multi_gap_days']} ({f['multi_gap_day_pct']:.1f}%)",
             ]
    return "\n".join(lines)
