"""Run the full hard+soft solve pipeline on the synthetic dataset and
export results in the timetables_generated/ formats.

Usage:
  python scripts/run_synthetic.py [--time-limit 30] [--out-dir output/synthetic_timetables]
"""
import argparse
import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sih_solver.dataset import quick_solvability_check
from sih_solver.solve_pipeline import solve_hard_then_soft
from sih_solver.validate_output import validate

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYNTHETIC_ROOT = ROOT / "synthetic_data"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-limit", type=float, default=30.0)
    ap.add_argument("--out-dir", default="output/synthetic_timetables")
    args = ap.parse_args()

    print(f"[1] solvability check: {SYNTHETIC_ROOT}")
    chk = quick_solvability_check(SYNTHETIC_ROOT)
    print(f"    blockers={chk['blockers']} warnings={len(chk['warnings'])}")

    print(f"[2] solving (hard<= {args.time_limit}s, soft<= {args.time_limit}s)...")
    res = solve_hard_then_soft(SYNTHETIC_ROOT,
                               hard_time_limit=args.time_limit,
                               soft_time_limit=args.time_limit)
    print(f"    status={res['status']} hard={res['hard_status']} "
          f"soft={res['soft_status']} objective={res['objective']}")

    if res["solver"] is None:
        sys.exit("no solution found; stopping")

    # export flat rows
    meta = res["meta"]
    slots = {s["slot_id"]: s for s in meta["data"]["time_slots.csv"]}
    flat_path = ROOT / "output" / "synthetic_timetable.csv"
    flat_path.parent.mkdir(parents=True, exist_ok=True)
    with open(flat_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["offering_id", "course_id", "section_id", "session", "slot_id",
                    "day", "start_time", "end_time", "room_id", "faculty_id"])
        for o in meta["offerings"]:
            oid = o["offering_id"]
            fac = meta["idx_to_fac"][res["solver"].Value(res["Teacher"][oid])]
            for s in range(int(o["required_sessions"])):
                slot_id = meta["idx_to_slot"][res["solver"].Value(res["Start"][(oid, s)])]
                room_id = meta["idx_to_room"][res["solver"].Value(res["Room"][(oid, s)])]
                sl = slots[slot_id]
                w.writerow([oid, o["course_id"], o["section_id"], s + 1, slot_id,
                            sl["day"], sl["start_time"], sl["end_time"], room_id, fac])

    print(f"[3] validating {flat_path.name}...")
    vres = validate(flat_path, SYNTHETIC_ROOT)
    print(f"    sessions={vres.get('sessions_checked')} violations={len(vres['violations'])} "
          f"warnings={len(vres.get('warnings', []))}")
    for v in vres["violations"]:
        print("      !", v)

    print("[4] exporting section grids...")
    from export_timetable_formats import export
    export(flat_path, ROOT / args.out_dir, SYNTHETIC_ROOT)
    print("done.")


if __name__ == "__main__":
    main()
