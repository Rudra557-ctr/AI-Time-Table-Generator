"""Export a solved timetable (offering/session rows) into the earlier
timetables_generated/ formats:

  1. generated_timetable.csv  – enriched flat rows (course/room/faculty names)
  2. S_<section>.csv          – per-section day x period grid
  3. S_<section>.txt          – same grid as aligned text

Usage:
  python scripts/export_timetable_formats.py <solved.csv> <out_dir> <dataset_root>
"""
import csv
import pathlib
import sys


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def export(solved_path, out_dir, root):
    root = pathlib.Path(root)
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    courses = {c["course_id"]: c for c in _read_csv(root / "courses.csv")}
    faculty = {f["faculty_id"]: f for f in _read_csv(root / "faculty.csv")}
    rooms = {r["room_id"]: r for r in _read_csv(root / "rooms.csv")}

    rows = _read_csv(solved_path)

    # 1. enriched flat CSV
    flat_path = out_dir / "generated_timetable.csv"
    fields = ["offering_id", "course_id", "course_name", "section_id", "session",
              "slot_id", "day", "start_time", "end_time", "room_id", "room_name",
              "faculty_id", "faculty_name"]
    with open(flat_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for r in rows:
            c = courses[r["course_id"]]
            rm = rooms[r["room_id"]]
            fa = faculty[r["faculty_id"]]
            w.writerow([r["offering_id"], r["course_id"], c["course_name"],
                        r["section_id"], r["session"], r["slot_id"], r["day"],
                        r["start_time"], r["end_time"], r["room_id"],
                        rm["room_name"], r["faculty_id"], fa["name"]])

    # period columns from actual time slots used
    periods = sorted({(r["start_time"], r["end_time"]) for r in rows})
    days = ["MON", "TUE", "WED", "THU", "FRI"]
    sections = sorted({r["section_id"] for r in rows})

    for sec in sections:
        grid = {(d, p): "—" for d in days for p in periods}
        for r in rows:
            if r["section_id"] != sec:
                continue
            c = courses[r["course_id"]]
            cell = f'{c["course_code"]} {r["room_id"]} {r["faculty_id"]}'
            grid[(r["day"], (r["start_time"], r["end_time"]))] = cell

        # 2. per-section csv
        csv_path = out_dir / f"{sec}.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Day/Period"] + [f"{s}-{e}" for s, e in periods])
            for d in days:
                w.writerow([d] + [grid[(d, p)] for p in periods])

        # 3. per-section txt
        txt_path = out_dir / f"{sec}.txt"
        header = "Day/Period | " + " | ".join(f"{s}-{e}" for s, e in periods)
        lines = [f"Section {sec}", header, "-" * len(header)]
        for d in days:
            lines.append(d + " | " + " | ".join(grid[(d, p)] for p in periods))
        txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {flat_path}")
    print(f"wrote {len(sections)} section grids to {out_dir}/")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    export(sys.argv[1], sys.argv[2], sys.argv[3])
