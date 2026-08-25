"""FastAPI backend — legacy upload/solve flow (pre-wizard shape).

  POST /api/upload                  -> ZIP/CSV/XLSX -> normalize (adapter.py fuzzy mapping) -> report/audit
  POST /api/solve/{job_id}          -> full CP-SAT solve (hard, then hinted soft) on the job's normalized/ folder
                                        optional JSON body {"weights": {...}} overrides soft.DEFAULT_WEIGHTS
                                        (merged, not replaced -- omitted keys keep their default)
  POST /api/resolve/{job_id}        -> dynamic re-solve: upload only the changed file(s); re-solves
                                        minimizing deviation from the job's PREVIOUS solve
                                        (solve_pipeline.solve_incremental_resolve) instead of
                                        re-deciding the whole timetable -- requires /api/solve first
  POST /api/optimize/{job_id}       -> re-optimize an already-valid schedule for compactness
                                        (solve_pipeline.solve_deep_optimize): a Lantiv-inspired local
                                        gap-repair pass (lns_gap_repair -- worst-section-first, escalating
                                        time budget, CP-SAT proves every repair), warm-started throughout --
                                        NOT stability-constrained like /api/resolve, since the point is to
                                        let structure change freely. Default (?polish=false): gap-repair
                                        only, ~2-2.5min, validated ~80% fewer internal gaps on a real
                                        32-section dataset. ?polish=true also runs faculty-compactness +
                                        preference polish afterward (90s/90s budgets, the ones actually
                                        shown to converge) -- adds ~3min more; skip it under time pressure,
                                        it's an explicit opt-in either way, not the /api/solve default
                                        (which stays fast). Requires /api/solve first.
  GET  /api/jobs                    -> recent jobs across ALL uploads, newest first (job_id,
                                        created_at, status, publish_state, dataset audit,
                                        has_timetable) -- lets the admin reopen a past
                                        generated timetable, not just the most recent one
  DELETE /api/jobs/{job_id}         -> permanently deletes a job's directory (uploads,
                                        normalized data, generated timetable, edit history)
  PATCH  /api/jobs/{job_id}         -> {"name": "..."} sets a custom display name shown
                                        in /history instead of "Timetable N"/the raw job_id
  GET  /api/status/{job_id}
  GET  /api/download/{job_id}, /api/download_class/{job_id}/{section}
  GET  /api/weights/defaults        -> soft.DEFAULT_WEIGHTS, so the frontend never hardcodes them separately
  GET  /api/data/{job_id}/{dataset} -> normalized/{dataset}.csv as JSON rows (read-only; dataset in adapter.CANONICAL)
  GET  /api/report/{job_id}         -> gap_stats.compute_stats on the job's generated_timetable.csv (409 if no solve yet)
  GET  /api/precheck/{job_id}       -> quick_solvability_check standalone (no solve side effect)

  -- Admin manual timetable editing (sih_solver/manual_edit.py). All
     synchronous (no background_tasks/polling) -- every op here is a
     single-row CSV mutation plus a bounded validate() call, not a solve.
  POST /api/edit/{job_id}/check           -> preview a proposed move/room/faculty
                                              change: hard-constraint checklist +
                                              soft-quality delta, does NOT apply it
  POST /api/edit/{job_id}/apply           -> re-validates server-side (never trusts
                                              a prior /check call) and, if valid,
                                              commits the edit + regenerates grids
  POST /api/edit/{job_id}/alternatives    -> ranked valid (day/slot/room) candidates
                                              for one session, by soft-quality impact
  POST /api/edit/{job_id}/room-alternatives -> compatible rooms for one session,
                                              each flagged valid/invalid with why
  GET  /api/edit/{job_id}/history         -> this job's edit history
  POST /api/edit/{job_id}/undo            -> re-applies the inverse of the most
                                              recent edit, through the same /apply path
  POST /api/edit/{job_id}/validate        -> whole-timetable re-validation (not
                                              scoped to one edit) + soft-quality
                                              summary; 0 violations unlocks publish
  POST /api/edit/{job_id}/publish         -> marks the job's timetable published;
                                              409 unless the last whole-file validate
                                              was clean and no edits landed since

Use ?fill=true on upload to fill missing required datasets from the repo's base SIH
dataset (demo convenience); without it, missing datasets stay missing and the solve
will fail loudly with whatever error the solver itself raises on incomplete data.
"""
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Request, Body
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
import pathlib
import shutil
import uuid
import csv
import json
import os
import threading
import time as _time

BASE = pathlib.Path(__file__).resolve().parent.parent
UPLOAD_ROOT = BASE / "uploads"
TIMETABLE_ROOT = BASE / "timetables_generated"
UPLOAD_ROOT.mkdir(exist_ok=True)
TIMETABLE_ROOT.mkdir(exist_ok=True)

app = FastAPI(title="SIH Timetable Generator", version="1.0")
jobs: dict = {}  # in-memory solve status; persisted per-job to status.json as well

# Manual-edit machinery (see /api/edit/* below) reads-then-rewrites a job's
# generated_timetable.csv per request -- one lock per job_id guards against
# two concurrent edits on the same job racing each other.
_edit_locks: dict = {}
_edit_locks_guard = threading.Lock()


def _edit_lock(job_id: str) -> threading.Lock:
    with _edit_locks_guard:
        if job_id not in _edit_locks:
            _edit_locks[job_id] = threading.Lock()
        return _edit_locks[job_id]


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


def _next_job_sequence() -> int:
    """1-based creation order ("Timetable 1", "Timetable 2", ...), derived
    from disk (max existing sequence + 1) rather than an in-memory counter
    so it survives a server restart and never collides. Deliberately never
    reused/renumbered when an earlier job is deleted -- it's a permanent
    "this was the Nth dataset generated" label, not a live position index."""
    best = 0
    for d in UPLOAD_ROOT.iterdir():
        if not d.is_dir():
            continue
        state = _read_status(d)
        if state and isinstance(state.get("sequence"), int):
            best = max(best, state["sequence"])
    return best + 1


def _write_class_grids(job_dir: pathlib.Path, rows: list, time_slots: list, courses: dict) -> None:
    """Bake per-section class_timetables/{section}.csv grids from an
    already-materialized timetable row list (the same shape
    generated_timetable.csv has). Extracted out of _write_timetable_and_grids
    so both a fresh solver readout AND a manual-edit's mutated row list can
    produce grids through the exact same code -- no drift between
    solver-generated and admin-edited grids. `rows` with slot_id UNASSIGNED
    are treated as unplaced (left as "—"), same as before."""
    days = ["MON", "TUE", "WED", "THU", "FRI"]
    period_order = [1, 2, 3, 4, 5, 6, 7]
    period_headers = ["09:00-10:00", "10:00-11:00", "11:00-12:00", "12:00-13:00", "14:00-15:00", "15:00-16:00", "16:00-17:00"]
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
    sections = sorted(set(r["section_id"] for r in rows))
    class_dir = job_dir / "class_timetables"
    class_dir.mkdir(exist_ok=True)
    for sec in sections:
        grid = {d: {p: "—" for p in period_order} for d in days}
        for row in rows:
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
    if solved:
        time_slots = meta["data"]["time_slots.csv"]
        courses = {r["course_id"]: r for r in meta["data"]["courses.csv"]}
        rows = list(csv.DictReader(open(out_csv, newline="", encoding="utf-8")))
        _write_class_grids(job_dir, rows, time_slots, courses)
    return out_csv


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

_FRONTEND_DIST = BASE / "frontend" / "dist"
if (_FRONTEND_DIST / "assets").exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="frontend-assets")


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
    jobs[job_id] = {
        "status": "uploaded",
        "dir": str(job_dir),
        "report": report,
        "audit": audit,
        "created_at": _time.time(),
        "sequence": _next_job_sequence(),
    }
    _write_status(job_dir, jobs[job_id])
    return {"job_id": job_id, "report": report, "audit": audit, "next": f"/api/solve/{job_id}"}


# ---------------------------------------------------------------------------
# Solve
# ---------------------------------------------------------------------------

# Statuses that carry an actual, valid, conflict-free schedule worth writing out.
_SOLVED_STATUSES = {"OPTIMAL_SOFT", "FEASIBLE_SOFT", "HARD_ONLY_FALLBACK"}


@app.post("/api/solve/{job_id}")
async def solve(job_id: str, background_tasks: BackgroundTasks,
                 hard_time_limit: float = 150.0, soft_time_limit: float = 120.0,
                 weights: dict | None = Body(default=None)):
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

    from sih_solver.soft import DEFAULT_WEIGHTS
    # Merge over DEFAULT_WEIGHTS rather than replacing it outright — soft.py's
    # add_soft_objective looks up each term with weights.get(key, 0), so a
    # partial payload (e.g. a UI that only exposes 10 of the 12 keys) would
    # otherwise silently zero out the terms it didn't send.
    merged_weights = {**DEFAULT_WEIGHTS, **(weights or {})}

    # Optional warm-start: if the upload included a prior/historical timetable
    # (initial_schedule.csv), seed CP-SAT's search with it. Proven fix for
    # datasets whose hard model is too large to solve cold within any
    # reasonable budget (a real 555k-variable dataset came back UNKNOWN even
    # at 300s cold, but OPTIMAL at 34.8s warm-started from this exact file).
    initial_schedule_csv = normalized_dir / "initial_schedule.csv"
    initial_hint_csv = str(initial_schedule_csv) if initial_schedule_csv.exists() else None

    def run_solve():
        try:
            from sih_solver.solve_pipeline import solve_hard_then_soft

            result = solve_hard_then_soft(str(normalized_dir), hard_time_limit=hard_time_limit,
                                           soft_time_limit=soft_time_limit, weights=merged_weights,
                                           initial_hint_csv=initial_hint_csv)
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
                "weights_used": merged_weights,
                "warm_started": initial_hint_csv is not None,
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
    return {"job_id": job_id, "status": "solving", "poll": f"/api/status/{job_id}", "warnings": check["warnings"],
            "warm_started": initial_hint_csv is not None}


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


# ---------------------------------------------------------------------------
# Optimize further — re-optimize an ALREADY-VALID schedule for compactness
# (solve_deep_optimize), warm-started from it rather than re-solving hard
# constraints from scratch. Deliberately separate from /api/solve: validated
# on a real 32-section dataset to meaningfully cut gaps (25%) and isolated
# single-period classes, but takes ~8 minutes by default -- too slow to be
# the default path for every Generate click, so it's an explicit opt-in
# instead of a blended time-budget slider.
# ---------------------------------------------------------------------------

@app.post("/api/optimize/{job_id}")
async def optimize(job_id: str, background_tasks: BackgroundTasks,
                    lns_max_rounds: int = 20, tier2_time_limit: float = 90.0,
                    tier3_time_limit: float = 90.0, polish: bool = False):
    job_dir = UPLOAD_ROOT / job_id
    if not job_dir.exists():
        return JSONResponse({"error": "job not found"}, status_code=404)
    previous_csv = job_dir / "generated_timetable.csv"
    if not previous_csv.exists():
        return JSONResponse({"error": "no existing solve for this job — call /api/solve first"}, status_code=400)
    normalized_dir = job_dir / "normalized"
    previous_snapshot = job_dir / "generated_timetable_previous.csv"
    shutil.copy(previous_csv, previous_snapshot)

    def run_optimize():
        try:
            from sih_solver.solve_pipeline import solve_deep_optimize

            result = solve_deep_optimize(
                str(normalized_dir), str(previous_snapshot),
                lns_max_rounds=lns_max_rounds,
                tier_time_limits=(tier2_time_limit, tier3_time_limit),
                run_faculty_preference_polish=polish,
            )
            total_seconds = round(result["soft_seconds"], 1) if result.get("soft_seconds") is not None else None
            lns_info = {
                "lns_rounds": result.get("lns_rounds"),
                "lns_objective": result.get("lns_objective"),
                "lns_starting_objective": result.get("lns_starting_objective"),
                "lns_seconds": result.get("lns_seconds"),
            }
            if result["status"] == "OPTIMIZE_FAILED":
                payload = {
                    "status": "OPTIMIZE_FAILED",
                    "tier_results": result["tier_results"], "final_tier_reached": None,
                    "total_seconds": total_seconds,
                    "output": str(previous_csv), "dir": str(job_dir),
                    **lns_info,
                }
            else:
                solver, Start, Teacher, Room, meta = result["solver"], result["Start"], result["Teacher"], result["Room"], result["meta"]
                out_csv = _write_timetable_and_grids(job_dir, solver, Start, Teacher, Room, meta, solved=True)
                payload = {
                    "status": "OPTIMIZED",
                    "soft_status": result["soft_status"],
                    "objective": result["objective"],
                    "tier_results": result["tier_results"], "final_tier_reached": result["final_tier_reached"],
                    "total_seconds": total_seconds,
                    "output": str(out_csv), "dir": str(job_dir),
                    **lns_info,
                }
            jobs[job_id].update(payload)
            _write_status(job_dir, jobs[job_id])
        except Exception as e:
            import traceback
            payload = {"status": f"ERROR: {e}", "trace": traceback.format_exc(), "dir": str(job_dir)}
            jobs[job_id].update(payload)
            _write_status(job_dir, jobs[job_id])
            print(traceback.format_exc())

    background_tasks.add_task(run_optimize)
    jobs[job_id] = {**jobs.get(job_id, {}), "status": "optimizing", "dir": str(job_dir)}
    _write_status(job_dir, jobs[job_id])
    return {"job_id": job_id, "status": "optimizing", "poll": f"/api/status/{job_id}"}


@app.get("/api/jobs")
def list_jobs(limit: int = 5):
    """Recent jobs across ALL uploads, newest first. Reads status.json off
    disk (not the in-memory `jobs` dict) so this also works after a server
    restart -- every job directory under uploads/ is already permanent, this
    just exposes them instead of leaving the admin stuck on whichever job
    happens to still be in browser localStorage."""
    limit = max(1, min(limit, 50))
    entries = []
    for job_dir in UPLOAD_ROOT.iterdir():
        if not job_dir.is_dir():
            continue
        state = _read_status(job_dir)
        if state is None:
            continue
        created_at = state.get("created_at")
        if created_at is None:
            try:
                created_at = job_dir.stat().st_ctime
            except OSError:
                created_at = 0
        audit = state.get("audit") or {}
        entries.append({
            "job_id": job_dir.name,
            "created_at": created_at,
            "sequence": state.get("sequence"),
            "name": state.get("name"),
            "status": state.get("status"),
            "publish_state": state.get("publish_state"),
            "has_timetable": (job_dir / "generated_timetable.csv").exists(),
            "sections": audit.get("sections"),
            "faculty": audit.get("faculty"),
            "rooms": audit.get("rooms"),
            "courses": audit.get("courses"),
        })
    entries.sort(key=lambda e: e["created_at"], reverse=True)
    return {"jobs": entries[:limit]}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    """Permanently removes a job's directory (raw uploads, normalized data,
    generated timetable, edit history) -- lets the admin prune a job they no
    longer want cluttering /history. Irreversible; the frontend confirms
    before calling this."""
    job_dir = UPLOAD_ROOT / job_id
    if not job_dir.exists() or not job_dir.is_dir():
        return JSONResponse({"error": "job not found"}, status_code=404)
    shutil.rmtree(job_dir, ignore_errors=True)
    jobs.pop(job_id, None)
    with _edit_locks_guard:
        _edit_locks.pop(job_id, None)
    return {"job_id": job_id, "deleted": True}


@app.patch("/api/jobs/{job_id}")
def rename_job(job_id: str, body: dict = Body(...)):
    """Sets a custom display name for a job (shown in /history instead of
    "Timetable N"/the raw job_id) -- purely a label, doesn't touch anything
    solver- or dataset-related. Pass {"name": "..."} ; an empty/whitespace
    name clears the custom name back to the default Timetable-N display."""
    job_dir = UPLOAD_ROOT / job_id
    if not job_dir.exists() or not job_dir.is_dir():
        return JSONResponse({"error": "job not found"}, status_code=404)
    name = (body.get("name") or "").strip()[:60]
    state = _current_job_state(job_id, job_dir)
    jobs[job_id] = {**state, "name": name or None}
    _write_status(job_dir, jobs[job_id])
    return {"job_id": job_id, "name": name or None}


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


# ---------------------------------------------------------------------------
# Read-only helpers for the frontend: soft-weight defaults (so the UI never
# hardcodes them separately from soft.py), normalized dataset rows (so
# Sections/Faculty/Rooms/Courses views show real uploaded data, not
# fabricated placeholders), and post-solve gap/compactness stats (wraps the
# already-independent gap_stats.py module — same numbers PLAN.md's own
# validation runs use, not a UI-side recomputation).
# ---------------------------------------------------------------------------

@app.get("/api/weights/defaults")
def weights_defaults():
    from sih_solver.soft import DEFAULT_WEIGHTS
    return DEFAULT_WEIGHTS


@app.get("/api/precheck/{job_id}")
def precheck(job_id: str):
    """Same quick_solvability_check /api/solve runs before committing to a
    full CP-SAT solve, exposed standalone (GET, no side effects) so the
    Dashboard/Conflicts screens can show real blocker/warning counts without
    triggering a solve just to find out."""
    job_dir = UPLOAD_ROOT / job_id
    normalized_dir = job_dir / "normalized"
    if not normalized_dir.exists():
        return JSONResponse({"error": "no normalized data for this job yet — call /api/upload first"}, status_code=404)
    from sih_solver.dataset import quick_solvability_check
    check = quick_solvability_check(normalized_dir)
    return check


@app.get("/api/data/{job_id}/{dataset}")
def dataset_rows(job_id: str, dataset: str):
    from sih_solver.adapter import CANONICAL
    if dataset not in CANONICAL:
        return JSONResponse({"error": f"unknown dataset '{dataset}'"}, status_code=404)
    p = UPLOAD_ROOT / job_id / "normalized" / f"{dataset}.csv"
    if not p.exists():
        return JSONResponse({"error": f"{dataset}.csv not present for this job"}, status_code=404)
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {"dataset": dataset, "count": len(rows), "rows": rows}


@app.get("/api/report/{job_id}")
def report(job_id: str):
    job_dir = UPLOAD_ROOT / job_id
    timetable_csv = job_dir / "generated_timetable.csv"
    time_slots_csv = job_dir / "normalized" / "time_slots.csv"
    if not timetable_csv.exists():
        return JSONResponse({"error": "no completed solve for this job yet — call /api/solve first"}, status_code=409)
    if not time_slots_csv.exists():
        return JSONResponse({"error": "time_slots.csv missing from this job's normalized data"}, status_code=404)
    from sih_solver.gap_stats import compute_stats
    with open(time_slots_csv, newline="", encoding="utf-8") as f:
        time_slots_rows = list(csv.DictReader(f))
    stats = compute_stats(timetable_csv, time_slots_rows)
    return stats


# ---------------------------------------------------------------------------
# Admin manual timetable editing (sih_solver/manual_edit.py) — Dataset ->
# CP-SAT generate -> Admin edit -> Re-validate -> Final timetable. Every
# accept/reject decision routes through validate_output.validate() (via
# manual_edit.check_edit), the same independent hard-constraint validator
# the rest of the project already trusts — never a second rule set.
# ---------------------------------------------------------------------------

_EDIT_ROW_FIELDS = ["offering_id", "course_id", "section_id", "session", "slot_id",
                     "day", "start_time", "end_time", "room_id", "faculty_id"]
_EDIT_SNAPSHOT_FIELDS = ("slot_id", "room_id", "faculty_id", "day", "start_time", "end_time")


def _require_solved_job(job_id: str):
    job_dir = UPLOAD_ROOT / job_id
    if not job_dir.exists():
        return None, JSONResponse({"error": "job not found"}, status_code=404)
    if not (job_dir / "generated_timetable.csv").exists():
        return None, JSONResponse({"error": "no generated timetable for this job — call /api/solve first"}, status_code=409)
    return job_dir, None


def _current_job_state(job_id: str, job_dir: pathlib.Path) -> dict:
    j = jobs.get(job_id)
    if j:
        return j
    return _read_status(job_dir) or {}


def _load_current_rows(job_dir: pathlib.Path) -> list:
    with open(job_dir / "generated_timetable.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_current_rows(job_dir: pathlib.Path, rows: list) -> None:
    with open(job_dir / "generated_timetable.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_EDIT_ROW_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in _EDIT_ROW_FIELDS})


def _edit_history_path(job_dir: pathlib.Path) -> pathlib.Path:
    return job_dir / "edit_history.json"


def _read_edit_history(job_dir: pathlib.Path) -> list:
    p = _edit_history_path(job_dir)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _write_edit_history(job_dir: pathlib.Path, history: list) -> None:
    try:
        with open(_edit_history_path(job_dir), "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass


def _snapshot(row: dict | None) -> dict | None:
    return {k: row.get(k) for k in _EDIT_SNAPSHOT_FIELDS} if row else None


def _mark_draft(job_id: str, job_dir: pathlib.Path) -> None:
    """Any edit or undo invalidates the last "Validate Final Timetable" run
    and un-publishes -- a published artifact that no longer matches the
    current edits shouldn't silently keep claiming to be published."""
    jobs[job_id] = {**_current_job_state(job_id, job_dir), "publish_state": "draft", "last_validated_clean": False}
    _write_status(job_dir, jobs[job_id])


@app.post("/api/edit/{job_id}/check")
def edit_check(job_id: str, edit: dict = Body(...)):
    job_dir, err = _require_solved_job(job_id)
    if err:
        return err
    from sih_solver import manual_edit as me
    normalized_dir = job_dir / "normalized"
    with _edit_lock(job_id):
        rows = _load_current_rows(job_dir)
        try:
            ctx = me.load_edit_context(normalized_dir)
            result = me.check_edit(normalized_dir, rows, edit, ctx=ctx)
            delta = me.compute_soft_delta(normalized_dir, rows, result["candidate_rows"], edit, ctx=ctx)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
    return {
        "valid": result["valid"], "checks": result["checks"],
        "new_violations": result["new_violations"],
        "preexisting_violations": result["preexisting_violations"],
        "warnings": result["warnings"],
        "soft_delta": delta["items"], "weighted_delta": delta["weighted_delta"],
    }


@app.post("/api/edit/{job_id}/apply")
def edit_apply(job_id: str, edit: dict = Body(...)):
    job_dir, err = _require_solved_job(job_id)
    if err:
        return err
    from sih_solver import manual_edit as me
    normalized_dir = job_dir / "normalized"
    with _edit_lock(job_id):
        rows = _load_current_rows(job_dir)
        try:
            ctx = me.load_edit_context(normalized_dir)
            # Always re-validate here, independent of any prior /check call
            # — the client's earlier preview may be stale (another edit
            # could have landed in between).
            result = me.check_edit(normalized_dir, rows, edit, ctx=ctx)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        if not result["valid"]:
            return JSONResponse({
                "error": "Edit rejected — it would introduce a hard-constraint violation.",
                "checks": result["checks"], "violations": result["new_violations"],
            }, status_code=422)
        candidate_rows = result["candidate_rows"]
        delta = me.compute_soft_delta(normalized_dir, rows, candidate_rows, edit, ctx=ctx)
        _write_current_rows(job_dir, candidate_rows)
        _write_class_grids(job_dir, candidate_rows, ctx["time_slots"], ctx["courses"])

        before_row = next((r for r in rows if r["offering_id"] == edit["offering_id"] and str(r["session"]) == str(edit["session"])), None)
        after_row = next((r for r in candidate_rows if r["offering_id"] == edit["offering_id"] and str(r["session"]) == str(edit["session"])), None)
        history = _read_edit_history(job_dir)
        entry = {
            "id": str(uuid.uuid4())[:8], "timestamp": _time.time(),
            "kind": edit.get("kind", "move"),
            "offering_id": edit["offering_id"], "session": edit["session"],
            "before": _snapshot(before_row), "after": _snapshot(after_row),
            "soft_delta": delta["items"], "weighted_delta": delta["weighted_delta"],
        }
        history.append(entry)
        _write_edit_history(job_dir, history)
        _mark_draft(job_id, job_dir)
    return {"valid": True, "checks": result["checks"], "soft_delta": delta["items"],
            "weighted_delta": delta["weighted_delta"], "entry": entry}


@app.post("/api/edit/{job_id}/alternatives")
def edit_alternatives(job_id: str, body: dict = Body(...)):
    job_dir, err = _require_solved_job(job_id)
    if err:
        return err
    from sih_solver import manual_edit as me
    normalized_dir = job_dir / "normalized"
    with _edit_lock(job_id):
        rows = _load_current_rows(job_dir)
    try:
        results = me.find_alternative_slots(normalized_dir, rows, body["offering_id"], body["session"],
                                             max_results=int(body.get("max_results", 5)))
    except (ValueError, KeyError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"alternatives": results}


@app.post("/api/edit/{job_id}/room-alternatives")
def edit_room_alternatives(job_id: str, body: dict = Body(...)):
    job_dir, err = _require_solved_job(job_id)
    if err:
        return err
    from sih_solver import manual_edit as me
    normalized_dir = job_dir / "normalized"
    with _edit_lock(job_id):
        rows = _load_current_rows(job_dir)
    try:
        results = me.find_room_alternatives(normalized_dir, rows, body["offering_id"], body["session"])
    except (ValueError, KeyError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"rooms": results}


@app.get("/api/edit/{job_id}/history")
def edit_history(job_id: str):
    job_dir, err = _require_solved_job(job_id)
    if err:
        return err
    return {"history": _read_edit_history(job_dir)}


@app.post("/api/edit/{job_id}/undo")
def edit_undo(job_id: str):
    job_dir, err = _require_solved_job(job_id)
    if err:
        return err
    from sih_solver import manual_edit as me
    normalized_dir = job_dir / "normalized"
    with _edit_lock(job_id):
        history = _read_edit_history(job_dir)
        target = next((h for h in reversed(history) if h.get("kind") != "undo" and not h.get("undone")), None)
        if target is None:
            return JSONResponse({"error": "Nothing to undo."}, status_code=400)
        before = target.get("before")
        if not before:
            return JSONResponse({"error": "Cannot undo — no prior state recorded for this edit."}, status_code=400)
        rows = _load_current_rows(job_dir)
        ctx = me.load_edit_context(normalized_dir)
        undo_edit = {
            "offering_id": target["offering_id"], "session": target["session"],
            "new_slot_id": before.get("slot_id"), "new_room_id": before.get("room_id"),
            "new_faculty_id": before.get("faculty_id"),
        }
        try:
            # Undo is validated exactly like any other edit — not a
            # privileged bypass — since something else may have changed
            # since the edit being undone was applied.
            result = me.check_edit(normalized_dir, rows, undo_edit, ctx=ctx)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        if not result["valid"]:
            return JSONResponse({
                "error": "Undo rejected — reverting would introduce a hard-constraint violation "
                         "(something else likely changed since this edit was applied).",
                "checks": result["checks"], "violations": result["new_violations"],
            }, status_code=422)
        candidate_rows = result["candidate_rows"]
        delta = me.compute_soft_delta(normalized_dir, rows, candidate_rows, undo_edit, ctx=ctx)
        _write_current_rows(job_dir, candidate_rows)
        _write_class_grids(job_dir, candidate_rows, ctx["time_slots"], ctx["courses"])
        target["undone"] = True
        entry = {
            "id": str(uuid.uuid4())[:8], "timestamp": _time.time(), "kind": "undo",
            "offering_id": target["offering_id"], "session": target["session"],
            "before": target["after"], "after": target["before"],
            "soft_delta": delta["items"], "weighted_delta": delta["weighted_delta"],
            "undoes": target["id"],
        }
        history.append(entry)
        _write_edit_history(job_dir, history)
        _mark_draft(job_id, job_dir)
    return {"valid": True, "entry": entry}


@app.post("/api/edit/{job_id}/validate")
def edit_validate_all(job_id: str):
    """Whole-timetable re-validation (req. #12) — NOT scoped to one edit,
    the honest complete picture after however many edits have landed since
    generation. On 0 violations, unlocks /publish."""
    job_dir, err = _require_solved_job(job_id)
    if err:
        return err
    from sih_solver.validate_output import validate as validate_whole
    from sih_solver.gap_stats import compute_stats
    normalized_dir = job_dir / "normalized"
    with _edit_lock(job_id):
        result = validate_whole(job_dir / "generated_timetable.csv", normalized_dir)
        clean = len(result["violations"]) == 0
        stats = None
        time_slots_csv = normalized_dir / "time_slots.csv"
        if time_slots_csv.exists():
            with open(time_slots_csv, newline="", encoding="utf-8") as f:
                time_slots_rows = list(csv.DictReader(f))
            stats = compute_stats(job_dir / "generated_timetable.csv", time_slots_rows)
        jobs[job_id] = {**_current_job_state(job_id, job_dir), "last_validated_clean": clean}
        _write_status(job_dir, jobs[job_id])
    return {
        "violations": result["violations"], "warnings": result["warnings"],
        "sessions_checked": result["sessions_checked"], "clean": clean,
        "soft_quality": stats,
    }


@app.post("/api/edit/{job_id}/publish")
def edit_publish(job_id: str):
    job_dir, err = _require_solved_job(job_id)
    if err:
        return err
    state = _current_job_state(job_id, job_dir)
    if not state.get("last_validated_clean"):
        return JSONResponse(
            {"error": "Cannot publish — run \"Validate Final Timetable\" first and resolve any violations."},
            status_code=409,
        )
    jobs[job_id] = {**state, "publish_state": "published"}
    _write_status(job_dir, jobs[job_id])
    return {"publish_state": "published"}


# ---------------------------------------------------------------------------
# Frontend SPA fallback — MUST stay the last route registered. Every route
# above (including FastAPI's own /docs, /openapi.json, /redoc) is matched
# first; this only catches paths nothing else claimed, so a page refresh on
# a client-side route like /history or /timetable still gets index.html
# (React Router then takes over) instead of a 404.
# ---------------------------------------------------------------------------

@app.get("/{full_path:path}", response_class=HTMLResponse)
def spa(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    # Root-level public/ files (favicon.svg, icons.svg, ...) land directly
    # in dist/ alongside index.html, not under /assets/ -- serve them as
    # actual files (not the SPA shell) when the path matches one.
    candidate = (_FRONTEND_DIST / full_path).resolve()
    if full_path and candidate.is_file() and _FRONTEND_DIST in candidate.parents:
        return FileResponse(candidate)
    index_path = _FRONTEND_DIST / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return "<h1>SIH Timetable API running — see /docs</h1>"
