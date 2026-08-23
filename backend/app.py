"""FastAPI backend — legacy upload/solve flow (pre-wizard shape).

  POST /api/upload                  -> ZIP/CSV/XLSX -> normalize (adapter.py fuzzy mapping) -> report/audit
  POST /api/solve/{job_id}          -> full CP-SAT solve (hard, then hinted soft) on the job's normalized/ folder
  POST /api/resolve/{job_id}        -> dynamic re-solve: upload only the changed file(s); re-solves
                                        minimizing deviation from the job's PREVIOUS solve
                                        (solve_pipeline.solve_incremental_resolve) instead of
                                        re-deciding the whole timetable -- requires /api/solve first
  GET  /api/status/{job_id}
  GET  /api/download/{job_id}, /api/download_class/{job_id}/{section}

Use ?fill=true on upload to fill missing required datasets from the repo's base SIH
dataset (demo convenience); without it, missing datasets stay missing and the solve
will fail loudly with whatever error the solver itself raises on incomplete data.
"""
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
import pathlib
import shutil
import uuid
import csv
import json
import os

BASE = pathlib.Path(__file__).resolve().parent.parent
UPLOAD_ROOT = BASE / "uploads"
TIMETABLE_ROOT = BASE / "timetables_generated"
UPLOAD_ROOT.mkdir(exist_ok=True)
TIMETABLE_ROOT.mkdir(exist_ok=True)

app = FastAPI(title="SIH Timetable Generator", version="1.0")
jobs: dict = {}  # in-memory solve status; persisted per-job to status.json as well


# ---------------------------------------------------------------------------
# Minimal access gate — not real auth. Set SIH_API_KEY before handing a URL
# to anyone outside your own machine; unset (the default) leaves the API
# open, matching existing local-dev / test behavior.
# ---------------------------------------------------------------------------

_API_KEY = os.environ.get("SIH_API_KEY", "").strip()


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    if _API_KEY and request.url.path.startswith("/api/"):
        if request.headers.get("x-api-key", "") != _API_KEY:
            return JSONResponse({"error": "Missing or invalid X-API-Key header"}, status_code=401)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Helpers: job dirs and status persistence
# ---------------------------------------------------------------------------

def _job_dir(job_id: str) -> pathlib.Path:
    d = UPLOAD_ROOT / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _status_path(job_dir: pathlib.Path) -> pathlib.Path:
    return job_dir / "status.json"


def _write_status(job_dir: pathlib.Path, payload: dict) -> None:
    try:
        with open(_status_path(job_dir), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass


def _read_status(job_dir: pathlib.Path) -> dict | None:
    p = _status_path(job_dir)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _count_rows(csv_path: pathlib.Path) -> int:
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            return sum(1 for _ in csv.DictReader(f))
    except FileNotFoundError:
        return 0


def _write_timetable_and_grids(job_dir: pathlib.Path, solver, Start, Teacher, Room, meta, solved: bool) -> pathlib.Path:
    """Write generated_timetable.csv + per-section class_timetables/*.csv for
    a solved (solver, Start, Teacher, Room, meta) tuple. Shared by /api/solve
    and /api/resolve so the two endpoints can't drift on output format."""
    out_csv = job_dir / "generated_timetable.csv"
    slots = {s["slot_id"]: s for s in meta["data"]["time_slots.csv"]}
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["offering_id", "course_id", "section_id", "session", "slot_id",
                    "day", "start_time", "end_time", "room_id", "faculty_id"])
        for o in meta["offerings"]:
            oid = o["offering_id"]
            fac = meta["idx_to_fac"][solver.Value(Teacher[oid])] if solved else "UNASSIGNED"
            for s in range(int(o["required_sessions"])):
                try:
                    slot_id = meta["idx_to_slot"][solver.Value(Start[(oid, s)])] if solved else "UNASSIGNED"
                    room_id = meta["idx_to_room"][solver.Value(Room[(oid, s)])] if solved else "UNASSIGNED"
                    sl = slots.get(slot_id, {"day": "?", "start_time": "?", "end_time": "?"})
                    w.writerow([oid, o["course_id"], o["section_id"], s + 1, slot_id, sl["day"], sl["start_time"], sl["end_time"], room_id, fac])
                except Exception:
                    w.writerow([oid, o["course_id"], o["section_id"], s + 1, "UNASSIGNED", "?", "?", "?", "UNASSIGNED", fac])
    # class-wise grids
    days = ["MON", "TUE", "WED", "THU", "FRI"]
    period_order = [1, 2, 3, 4, 5, 6, 7]
    period_headers = ["09:00-10:00", "10:00-11:00", "11:00-12:00", "12:00-13:00", "14:00-15:00", "15:00-16:00", "16:00-17:00"]
    time_slots = meta["data"]["time_slots.csv"]
    courses = {r["course_id"]: r for r in meta["data"]["courses.csv"]}
    from datetime import datetime as _dt

    def parse(t):
        return _dt.strptime(t.strip(), "%H:%M")

    by_day: dict = {}
    for s in time_slots:
        by_day.setdefault(s["day"], []).append(s)
    slot_next: dict = {}
    for day, lst in by_day.items():
        lst_sorted = sorted(lst, key=lambda x: parse(x["start_time"]))
        for i in range(len(lst_sorted) - 1):
            if parse(lst_sorted[i]["end_time"]) == parse(lst_sorted[i + 1]["start_time"]):
                slot_next[lst_sorted[i]["slot_id"]] = lst_sorted[i + 1]["slot_id"]
    sections = sorted(set(o["section_id"] for o in meta["offerings"]))
    class_dir = job_dir / "class_timetables"
    class_dir.mkdir(exist_ok=True)
    if solved:
        timetable = list(csv.DictReader(open(out_csv, newline="", encoding="utf-8")))
        for sec in sections:
            grid = {d: {p: "—" for p in period_order} for d in days}
            for row in timetable:
                if row["section_id"] != sec:
                    continue
                if row["slot_id"] == "UNASSIGNED":
                    continue
                sl = next((s for s in time_slots if s["slot_id"] == row["slot_id"]), None)
                if not sl:
                    continue
                d = sl["day"]
                p = int(sl["period_number"])
                ccode = courses.get(row["course_id"], {}).get("course_code", row["course_id"])
                entry = f"{ccode} {row['room_id']} {row['faculty_id']}"
                grid[d][p] = entry
                dur = int(courses.get(row["course_id"], {}).get("session_duration", "1") or 1)
                if dur == 2 and row["slot_id"] in slot_next:
                    nxt = slot_next[row["slot_id"]]
                    sl2 = next((s for s in time_slots if s["slot_id"] == nxt), None)
                    if sl2:
                        grid[sl2["day"]][int(sl2["period_number"])] = entry
            with open(class_dir / f"{sec}.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Day/Period"] + period_headers)
                for d in days:
                    w.writerow([d] + [grid[d][p] for p in period_order])
    return out_csv


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index():
    return "<h1>SIH Timetable API running — see /docs</h1>"


# ---------------------------------------------------------------------------
# Upload — normalize via adapter's fuzzy column/dataset-type detection
# ---------------------------------------------------------------------------

@app.post("/api/upload")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    # optional ?fill=true to explicitly re-enable legacy filler (demo convenience)
    fill = request.query_params.get("fill", "").lower() in ("1", "true", "yes")
    job_id = str(uuid.uuid4())[:8]
    job_dir = _job_dir(job_id)
    raw_dir = job_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        dest = raw_dir / (f.filename or f"file_{uuid.uuid4().hex[:4]}.csv")
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        if dest.suffix.lower() == ".zip":
            from parsers.zip_parser import extract_zip
            extract_zip(dest, raw_dir)
            try:
                dest.unlink()
            except Exception:
                pass
        elif dest.suffix.lower() in (".xlsx", ".xls"):
            from parsers.xlsx_parser import xlsx_to_csv
            csv_path = dest.with_suffix(".csv")
            try:
                xlsx_to_csv(dest, csv_path)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=400)
    from parsers.zip_parser import handle_xlsx_in_folder
    handle_xlsx_in_folder(raw_dir)

    from sih_solver.adapter import normalize_upload_folder, CANONICAL
    normalized_dir = job_dir / "normalized"
    # fill_missing=False (default) means normalize_upload_folder itself never
    # silently copies bundled sample data over a missing required file — it
    # just reports the file as missing so quick_solvability_check can block
    # the solve on it. ?fill=true opts into the demo-convenience fallback.
    report = normalize_upload_folder(raw_dir, normalized_dir, fill_missing=fill)

    audit = {ds: _count_rows(normalized_dir / f"{ds}.csv") for ds in CANONICAL.keys()}
    jobs[job_id] = {"status": "uploaded", "dir": str(job_dir), "report": report, "audit": audit}
    _write_status(job_dir, jobs[job_id])
    return {"job_id": job_id, "report": report, "audit": audit, "next": f"/api/solve/{job_id}"}


# ---------------------------------------------------------------------------
# Solve
# ---------------------------------------------------------------------------

# Statuses that carry an actual, valid, conflict-free schedule worth writing out.
_SOLVED_STATUSES = {"OPTIMAL_SOFT", "FEASIBLE_SOFT", "HARD_ONLY_FALLBACK"}


@app.post("/api/solve/{job_id}")
async def solve(job_id: str, background_tasks: BackgroundTasks,
                 hard_time_limit: float = 150.0, soft_time_limit: float = 120.0):
    job_dir = UPLOAD_ROOT / job_id
    if not job_dir.exists():
        return JSONResponse({"error": "job not found"}, status_code=404)
    normalized_dir = job_dir / "normalized"

    # PLAN.md §5.A2 — fail fast (sub-second) on data that would otherwise burn
    # the full time budget and come back INFEASIBLE/UNKNOWN or crash mid-solve
    # with no explanation.
    from sih_solver.dataset import quick_solvability_check
    check = quick_solvability_check(normalized_dir)
    if check["blockers"]:
        return JSONResponse(
            {"error": "Cannot solve — fix these first", "blockers": check["blockers"], "warnings": check["warnings"]},
            status_code=422,
        )

    def run_solve():
        try:
            from sih_solver.solve_pipeline import solve_hard_then_soft

            result = solve_hard_then_soft(str(normalized_dir), hard_time_limit=hard_time_limit,
                                           soft_time_limit=soft_time_limit)
            solver, Start, Teacher, Room, meta = result["solver"], result["Start"], result["Teacher"], result["Room"], result["meta"]
            solved = result["status"] in _SOLVED_STATUSES
            out_csv = _write_timetable_and_grids(job_dir, solver, Start, Teacher, Room, meta, solved)
            payload = {
                "status": result["status"],
                "hard_status": result["hard_status"], "soft_status": result["soft_status"],
                "seed_used": result["seed_used"],
                "hard_seconds": round(result["hard_seconds"], 1), "soft_seconds": round(result["soft_seconds"], 1),
                "objective": result["objective"],
                "warnings": check["warnings"],
                "output": str(out_csv) if solved else None, "dir": str(job_dir),
            }
            jobs[job_id].update(payload)
            _write_status(job_dir, jobs[job_id])
        except Exception as e:
            import traceback
            payload = {"status": f"ERROR: {e}", "trace": traceback.format_exc(), "dir": str(job_dir)}
            jobs[job_id].update(payload)
            _write_status(job_dir, jobs[job_id])
            print(traceback.format_exc())
    background_tasks.add_task(run_solve)
    jobs[job_id] = {**jobs.get(job_id, {}), "status": "solving", "dir": str(job_dir)}
    _write_status(job_dir, jobs[job_id])
    return {"job_id": job_id, "status": "solving", "poll": f"/api/status/{job_id}", "warnings": check["warnings"]}


# ---------------------------------------------------------------------------
# Resolve — dynamic re-solve after one or more inputs change, without
# re-deciding the whole timetable from scratch (PLAN.md: "every change to
# one section cascades through the rest" is the named pain point this
# answers). Upload ONLY the changed file(s); everything else in the job's
# existing normalized/ data is reused as-is.
# ---------------------------------------------------------------------------

@app.post("/api/resolve/{job_id}")
async def resolve(job_id: str, background_tasks: BackgroundTasks, files: list[UploadFile] = File(...),
                   stability_time_limit: float = 60.0, tier1_time_limit: float = 40.0,
                   tier2_time_limit: float = 30.0, tier3_time_limit: float = 30.0):
    job_dir = UPLOAD_ROOT / job_id
    if not job_dir.exists():
        return JSONResponse({"error": "job not found"}, status_code=404)
    previous_csv = job_dir / "generated_timetable.csv"
    if not previous_csv.exists():
        return JSONResponse({"error": "no previous solve for this job — call /api/solve first"}, status_code=400)
    # Snapshot the previous solve before it gets overwritten -- the stability
    # reference and the diff report both need "state as it was before this
    # resolve", not whatever generated_timetable.csv looks like mid-write.
    previous_snapshot = job_dir / "generated_timetable_previous.csv"
    shutil.copy(previous_csv, previous_snapshot)

    raw_dir = job_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        dest = raw_dir / (f.filename or f"file_{uuid.uuid4().hex[:4]}.csv")
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        if dest.suffix.lower() in (".xlsx", ".xls"):
            from parsers.xlsx_parser import xlsx_to_csv
            csv_path = dest.with_suffix(".csv")
            try:
                xlsx_to_csv(dest, csv_path)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=400)

    from sih_solver.adapter import normalize_upload_folder
    normalized_dir = job_dir / "normalized"
    # Re-normalize the WHOLE raw/ folder (the just-uploaded changed file(s)
    # overwrote the old copy of themselves in raw/; everything else is
    # untouched) -- cheap, deterministic, and avoids having two different
    # code paths for "first upload" vs "resolve".
    report = normalize_upload_folder(raw_dir, normalized_dir, fill_missing=False)

    from sih_solver.dataset import quick_solvability_check
    check = quick_solvability_check(normalized_dir)
    if check["blockers"]:
        return JSONResponse(
            {"error": "Cannot resolve — fix these first", "blockers": check["blockers"], "warnings": check["warnings"]},
            status_code=422,
        )

    def run_resolve():
        try:
            from sih_solver.solve_pipeline import solve_incremental_resolve

            result = solve_incremental_resolve(
                str(normalized_dir), str(previous_snapshot),
                stability_time_limit=stability_time_limit,
                tier_time_limits=(tier1_time_limit, tier2_time_limit, tier3_time_limit),
            )
            solver, Start, Teacher, Room, meta = result["solver"], result["Start"], result["Teacher"], result["Room"], result["meta"]
            out_csv = _write_timetable_and_grids(job_dir, solver, Start, Teacher, Room, meta, solved=True)
            payload = {
                "status": "RESOLVED",
                "tier_results": result["tier_results"],
                "final_tier_reached": result["final_tier_reached"],
                "total_seconds": round(result["total_seconds"], 1),
                "changed_count": len(result["changed"]),
                "changed": result["changed"],
                "warnings": check["warnings"],
                "output": str(out_csv), "dir": str(job_dir),
            }
            jobs[job_id].update(payload)
            _write_status(job_dir, jobs[job_id])
        except Exception as e:
            import traceback
            payload = {"status": f"ERROR: {e}", "trace": traceback.format_exc(), "dir": str(job_dir)}
            jobs[job_id].update(payload)
            _write_status(job_dir, jobs[job_id])
            print(traceback.format_exc())

    background_tasks.add_task(run_resolve)
    jobs[job_id] = {**jobs.get(job_id, {}), "status": "resolving", "dir": str(job_dir)}
    _write_status(job_dir, jobs[job_id])
    return {"job_id": job_id, "status": "resolving", "poll": f"/api/status/{job_id}", "warnings": check["warnings"]}


@app.get("/api/status/{job_id}")
def status(job_id: str):
    j = jobs.get(job_id)
    if j:
        return {**j, "job_id": job_id}
    job_dir = UPLOAD_ROOT / job_id
    if job_dir.exists():
        disk = _read_status(job_dir)
        if disk:
            jobs[job_id] = disk
            return {**disk, "job_id": job_id}
        return {"job_id": job_id, "status": "unknown (restarted)", "dir": str(job_dir)}
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/api/download/{job_id}")
def download(job_id: str):
    job_dir = UPLOAD_ROOT / job_id
    csv_path = job_dir / "generated_timetable.csv"
    if not csv_path.exists():
        return JSONResponse({"error": "not ready"}, status_code=404)
    return FileResponse(str(csv_path), filename="timetable.csv")


@app.get("/api/download_class/{job_id}/{section}")
def download_class(job_id: str, section: str):
    p = UPLOAD_ROOT / job_id / "class_timetables" / f"{section}.csv"
    if not p.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(p), filename=f"{section}.csv")
