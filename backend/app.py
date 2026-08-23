"""FastAPI backend — Phase C: store + schema + validation gate.

New flow (wizard):
  POST /api/jobs                    -> create empty job (data.json)
  GET  /api/jobs/{id}               -> full store + validate_all() summary + solve status
  GET/PUT /api/jobs/{id}/data/{ds}  -> per-dataset CRUD (strict L1 + FK check)
  GET  /api/schema, /api/schema/{ds}
  GET  /api/templates/{ds}, /api/templates/all.zip   (ALL canonical columns + example row)
  POST /api/jobs/{id}/import/{ds}   -> CSV/XLSX file -> fuzzy map -> validate -> merge

Legacy flow kept (now store-backed, no silent synthetic fallback):
  POST /api/upload                  -> ZIP/CSV/XLSX -> normalize -> store -> validate
  POST /api/solve/{id}              -> validate gate (BLOCKER => 400) -> export -> CP-SAT
  GET  /api/status/{id}
  GET  /api/download/{id} etc.

Fallback removal: /api/solve no longer injects /tmp or repo CSVs. What was uploaded/generated is what is solved.
Use ?fill=true on upload to explicitly re-enable legacy base-dataset filler (demo mode).
"""
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Body, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
import pathlib
import shutil
import uuid
import csv
import json
import io
import os
import zipfile

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


def _load_validation_for_job(job_id: str) -> dict:
    """Run validate_all on the job's store. Returns validator result dict."""
    from backend.store import load_store
    from sih_solver.validator import validate_all
    jd = UPLOAD_ROOT / job_id
    if not jd.exists():
        return {"blockers": [], "warnings": [], "all_issues": [], "per_dataset": {}, "summary": {"total_blockers": 0, "total_warnings": 0, "can_solve": True}}
    data = load_store(jd)
    return validate_all(data)


# ---------------------------------------------------------------------------
# Static / index
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index():
    frontend = BASE / "frontend" / "index.html"
    if frontend.exists():
        return frontend.read_text(encoding="utf-8")
    return "<h1>SIH Timetable API running — see /docs</h1>"


# Serve frontend assets for the new multi-file wizard (if present)
# Keep this after the "/" route so "/" still returns index.html content-type correctly.
try:
    if (BASE / "frontend").exists():
        # mount at /frontend so index.html can use <script src="/frontend/js/app.js">
        # Also handle legacy GET / returning file; clients can still use /frontend/* directly.
        app.mount("/frontend", StaticFiles(directory=str(BASE / "frontend")), name="frontend-static")
except Exception:
    pass


# ---------------------------------------------------------------------------
# New API: schema + templates
# ---------------------------------------------------------------------------

@app.get("/api/schema")
def get_schema_all():
    from sih_solver.schema import SCHEMAS, required_datasets, optional_datasets
    return {
        "datasets": SCHEMAS,
        "required": required_datasets(),
        "optional": optional_datasets(),
    }


@app.get("/api/schema/{dataset}")
def get_schema_one(dataset: str):
    from sih_solver.schema import get_schema
    try:
        fields = get_schema(dataset)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    return {"dataset": dataset, "fields": fields}


@app.get("/api/templates/all.zip")
def get_all_templates():
    from sih_solver.schema import template_csv, SCHEMAS
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for ds in SCHEMAS.keys():
            z.writestr(f"{ds}.csv", template_csv(ds, include_example=True))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="sih_templates_all.zip"'},
    )


@app.get("/api/templates/{dataset}")
def get_template(dataset: str):
    from sih_solver.schema import template_csv, SCHEMAS
    key = dataset[:-4] if dataset.lower().endswith(".csv") else dataset
    if key not in SCHEMAS:
        return JSONResponse({"error": f"Unknown dataset '{dataset}'"}, status_code=404)
    csv_str = template_csv(key, include_example=True)
    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{key}.csv"'},
    )


# ---------------------------------------------------------------------------
# New API: jobs + per-dataset CRUD
# ---------------------------------------------------------------------------

@app.post("/api/jobs")
def create_job():
    job_id = str(uuid.uuid4())[:8]
    jd = _job_dir(job_id)
    from backend.store import init_store
    init_store(jd)
    jobs[job_id] = {"status": "created", "dir": str(jd)}
    _write_status(jd, jobs[job_id])
    validation = _load_validation_for_job(job_id)
    return {"job_id": job_id, "status": "created", "validation": validation, "next": f"/api/jobs/{job_id}"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    jd = UPLOAD_ROOT / job_id
    if not jd.exists():
        return JSONResponse({"error": "job not found"}, status_code=404)
    from backend.store import load_store
    data = load_store(jd)
    validation = _load_validation_for_job(job_id)
    # counts: rows per dataset
    counts = {ds: len(rows) for ds, rows in data.items()}
    # merge in-memory solve status if present, else disk status
    st = jobs.get(job_id) or _read_status(jd) or {"status": "created", "dir": str(jd)}
    # keep jobs dict warm for polling after restart
    jobs[job_id] = st
    return {
        "job_id": job_id,
        "status": st.get("status"),
        "objective": st.get("objective"),
        "dir": str(jd),
        "counts": counts,
        "validation": validation,
        "output": st.get("output"),
    }


@app.get("/api/jobs/{job_id}/data/{dataset}")
def get_dataset(job_id: str, dataset: str):
    jd = UPLOAD_ROOT / job_id
    if not jd.exists():
        return JSONResponse({"error": "job not found"}, status_code=404)
    from sih_solver.schema import SCHEMAS
    key = dataset[:-4] if dataset.lower().endswith(".csv") else dataset
    if key not in SCHEMAS:
        return JSONResponse({"error": f"Unknown dataset '{dataset}'"}, status_code=404)
    from backend.store import load_store
    data = load_store(jd)
    rows = data.get(key, [])
    return {"job_id": job_id, "dataset": key, "rows": rows, "count": len(rows)}


@app.put("/api/jobs/{job_id}/data/{dataset}")
async def put_dataset(job_id: str, dataset: str, request: Request):
    jd = UPLOAD_ROOT / job_id
    if not jd.exists():
        return JSONResponse({"error": "job not found"}, status_code=404)
    from sih_solver.schema import SCHEMAS
    key = dataset[:-4] if dataset.lower().endswith(".csv") else dataset
    if key not in SCHEMAS:
        return JSONResponse({"error": f"Unknown dataset '{dataset}'"}, status_code=404)
    # Accept either {"rows": [...]} or raw [...]
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Expected JSON body"}, status_code=400)
    if isinstance(body, list):
        rows = body
    elif isinstance(body, dict) and "rows" in body:
        rows = body["rows"]
    elif isinstance(body, dict) and not body:
        rows = []
    else:
        # dict-shaped single row? wrap
        return JSONResponse({"error": "Expected JSON array or {\"rows\": [...] }"}, status_code=400)
    if not isinstance(rows, list):
        return JSONResponse({"error": "rows must be a list"}, status_code=400)
    # Normalize rows to string values
    cleaned = []
    for r in rows:
        if not isinstance(r, dict):
            return JSONResponse({"error": "each row must be an object"}, status_code=400)
        cleaned.append({str(k): ("" if v is None else str(v)) for k, v in r.items()})

    from backend.store import load_store, save_store
    from sih_solver.validator import validate_single_dataset
    data = load_store(jd)
    # validate before save (strict per-tab: BLOCKERs reject)
    single = validate_single_dataset(key, cleaned, whole_store=data)
    if single["summary"]["total_blockers"] > 0:
        return JSONResponse(
            {
                "error": "Validation failed — fix BLOCKERs before saving",
                "validation": single,
                "dataset": key,
            },
            status_code=422,
        )
    # save
    new_data = dict(data)
    new_data[key] = cleaned
    save_store(jd, new_data)
    # also export warnings back for UI
    validation = _load_validation_for_job(job_id)
    return {"job_id": job_id, "dataset": key, "count": len(cleaned), "validation": single, "overall_validation": validation}


@app.post("/api/jobs/{job_id}/import/{dataset}")
async def import_dataset(job_id: str, dataset: str, file: UploadFile = File(...)):
    jd = UPLOAD_ROOT / job_id
    if not jd.exists():
        return JSONResponse({"error": "job not found"}, status_code=404)
    from sih_solver.schema import SCHEMAS
    key = dataset[:-4] if dataset.lower().endswith(".csv") else dataset
    if key not in SCHEMAS:
        return JSONResponse({"error": f"Unknown dataset '{dataset}'"}, status_code=404)

    # Save uploaded file to temp
    raw_bytes = await file.read()
    # handle XLSX pass-through
    rows: list[dict] = []
    headers: list[str] = []
    mapping: dict = {}
    tmp_path = jd / f"_import_{key}{pathlib.Path(file.filename or '').suffix}"
    try:
        tmp_path.write_bytes(raw_bytes)
        if tmp_path.suffix.lower() in (".xlsx", ".xls"):
            # convert via xlsx_parser to a temp CSV sidecar
            from parsers.xlsx_parser import xlsx_to_csv
            csv_tmp = tmp_path.with_suffix(".csv")
            try:
                xlsx_to_csv(tmp_path, csv_tmp)
            except Exception as e:
                return JSONResponse({"error": f"XLSX parse failed: {e}"}, status_code=400)
            tmp_path = csv_tmp
        # read CSV with utf-8-sig
        with open(tmp_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = list(reader.fieldnames or [])
            raw_rows = list(reader)
        if not headers:
            return JSONResponse({"error": "CSV has no header row"}, status_code=400)

        # Fuzzy map to canonical using same logic as adapter but driven by SCHEMAS header order
        from sih_solver.adapter import infer_column_mapping
        canonical_fields = [fl["name"] for fl in SCHEMAS[key]]
        mapping = infer_column_mapping(headers, canonical_fields)
        # Build canonical rows
        cleaned_rows: list[dict] = []
        for r in raw_rows:
            out = {}
            for canon in canonical_fields:
                user_col = mapping.get(canon)
                if user_col and user_col in r and str(r[user_col]).strip() != "":
                    out[canon] = str(r[user_col]).strip()
                else:
                    out[canon] = ""
            cleaned_rows.append(out)
        rows = cleaned_rows
    except Exception as e:
        return JSONResponse({"error": f"Import failed: {e}"}, status_code=400)
    finally:
        # cleanup temp
        try:
            if tmp_path.exists() and tmp_path.name.startswith("_import_"):
                tmp_path.unlink()
        except Exception:
            pass

    # validate in context of whole store
    from backend.store import load_store, save_store
    from sih_solver.validator import validate_single_dataset
    data = load_store(jd)
    single = validate_single_dataset(key, rows, whole_store=data)
    if single["summary"]["total_blockers"] > 0:
        return JSONResponse(
            {
                "error": "Import validation failed — fix BLOCKERs and re-upload",
                "dataset": key,
                "headers": headers,
                "mapping": mapping,
                "rows_preview": rows[:3],
                "validation": single,
            },
            status_code=422,
        )
    # merge (replace) and save
    new_data = dict(data)
    new_data[key] = rows
    save_store(jd, new_data)
    overall = _load_validation_for_job(job_id)
    return {
        "job_id": job_id,
        "dataset": key,
        "imported": len(rows),
        "headers": headers,
        "mapping": mapping,
        "validation": single,
        "overall_validation": overall,
    }


# ---------------------------------------------------------------------------
# Legacy upload (now store-backed, no silent base-data injection)
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

    # Normalize via adapter (keeps fuzzy header mapping), but now also validates via schema
    from sih_solver.adapter import normalize_upload_folder
    from backend.store import import_from_normalized, save_store
    from sih_solver.validator import validate_all as _validate_all
    # Use adapter's filler only when explicitly requested
    # We temporarily monkey-patch or pass through by replicating its filler logic here.
    # Easiest: call normalize_upload_folder then, if not fill, remove filler files that were auto-copied.
    from sih_solver.schema import SCHEMAS as _SCH
    normalized_dir = job_dir / "normalized"
    report = normalize_upload_folder(raw_dir, normalized_dir)
    if not fill:
        # report["warnings"] may contain "Missing X.csv – filled from base SIH dataset"
        # Purge those filler files and strip the corresponding warnings so caller sees they are missing.
        # NOTE: must match the dataset name exactly (regex on "Missing <name>.csv"), not via
        # `ds in w` substring search — "faculty" is a substring of "faculty_availability", so a
        # filled faculty_availability.csv used to make this code delete the user's real,
        # correctly-uploaded faculty.csv. Confirmed by reproducing an upload of just faculty.csv
        # (no faculty_availability.csv): faculty ended up with 0 rows.
        import re as _re
        filler_datasets = []
        for w in list(report.get("warnings", [])):
            if "filled from base SIH dataset" in w:
                m = _re.match(r"Missing (\w+)\.csv", w)
                if m and m.group(1) in _SCH:
                    filler_datasets.append(m.group(1))
        for ds in filler_datasets:
            p = normalized_dir / f"{ds}.csv"
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        # clean report warnings to only keep non-filler ones
        report["warnings"] = [w for w in report.get("warnings", []) if "filled from base SIH dataset" not in w]
        if filler_datasets:
            report["warnings"].append(
                f"Validation will flag missing datasets as BLOCKERs (fill with templates or PUT /api/jobs/{job_id}/data/{{dataset}}). Use ?fill=true to auto-fill demo data."
            )
    # Load normalized into store's data.json
    data = import_from_normalized(normalized_dir) if normalized_dir.exists() else {ds: [] for ds in _SCH.keys()}
    save_store(job_dir, data)
    # also keep a copy exported via store (canonical headers)
    from backend.store import export_to_normalized
    export_to_normalized(data, normalized_dir)

    validation = _validate_all(data)
    # also compute simple audit counts for backward-compat display
    audit = {ds: len(rows) for ds, rows in data.items()}
    jobs[job_id] = {"status": "uploaded", "dir": str(job_dir), "report": report, "audit": audit, "validation": validation}
    _write_status(job_dir, jobs[job_id])
    return {"job_id": job_id, "report": report, "audit": audit, "validation": validation, "next": f"/api/solve/{job_id}"}


# ---------------------------------------------------------------------------
# Solve (now with validation gate + no synthetic fallback)
# ---------------------------------------------------------------------------

@app.post("/api/solve/{job_id}")
async def solve(job_id: str, background_tasks: BackgroundTasks, time_limit: int = 60):
    job_dir = UPLOAD_ROOT / job_id
    if not job_dir.exists():
        return JSONResponse({"error": "job not found"}, status_code=404)
    # Validation gate: refuse if BLOCKERs exist
    validation = _load_validation_for_job(job_id)
    if validation["summary"]["total_blockers"] > 0:
        return JSONResponse(
            {
                "error": "Cannot solve — fix BLOCKERs first",
                "validation": validation,
                "per_dataset": validation.get("per_dataset"),
            },
            status_code=422,
        )
    normalized_dir = job_dir / "normalized"
    # Ensure normalized is up to date (export from store)
    from backend.store import load_store, export_to_normalized
    data = load_store(job_dir)
    export_to_normalized(data, normalized_dir)

    def run_solve():
        try:
            from sih_solver.full_model import build_full_hard_model
            from sih_solver.soft import add_soft_objective, DEFAULT_WEIGHTS
            from ortools.sat.python import cp_model

            # NO fallback to /tmp or repo root — what was uploaded/generated is what is solved.
            model, Start, Teacher, Room, meta = build_full_hard_model(str(normalized_dir))
            penalties = add_soft_objective(model, Start, Teacher, Room, meta, DEFAULT_WEIGHTS)
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = time_limit
            solver.parameters.num_search_workers = 8
            status = solver.Solve(model)
            names = {0: "UNKNOWN", 2: "FEASIBLE", 3: "INFEASIBLE", 4: "OPTIMAL"}
            import csv as csv2
            out_csv = job_dir / "generated_timetable.csv"
            slots = {s["slot_id"]: s for s in meta["data"]["time_slots.csv"]}
            with open(out_csv, "w", newline="") as f:
                w = csv2.writer(f)
                w.writerow(["offering_id","course_id","section_id","session","slot_id","day","start_time","end_time","room_id","faculty_id"])
                for o in meta["offerings"]:
                    oid = o["offering_id"]
                    fac = meta["idx_to_fac"][solver.Value(Teacher[oid])] if status in (2, 4) else "UNASSIGNED"
                    for s in range(int(o["required_sessions"])):
                        try:
                            slot_id = meta["idx_to_slot"][solver.Value(Start[(oid, s)])] if status in (2, 4) else "UNASSIGNED"
                            room_id = meta["idx_to_room"][solver.Value(Room[(oid, s)])] if status in (2, 4) else "UNASSIGNED"
                            sl = slots.get(slot_id, {"day": "?","start_time": "?","end_time": "?"})
                            w.writerow([oid, o["course_id"], o["section_id"], s+1, slot_id, sl["day"], sl["start_time"], sl["end_time"], room_id, fac])
                        except Exception:
                            w.writerow([oid, o["course_id"], o["section_id"], s+1, "UNASSIGNED","?","?","?","UNASSIGNED", fac])
            # class-wise grids
            days = ["MON","TUE","WED","THU","FRI"]
            period_order = [1,2,3,4,5,6,7]
            period_headers = ["09:00-10:00","10:00-11:00","11:00-12:00","12:00-13:00","14:00-15:00","15:00-16:00","16:00-17:00"]
            time_slots = meta["data"]["time_slots.csv"]
            courses = {r["course_id"]: r for r in meta["data"]["courses.csv"]}
            from datetime import datetime as _dt
            def parse(t): return _dt.strptime(t.strip(), "%H:%M")
            by_day: dict = {}
            for s in time_slots:
                by_day.setdefault(s["day"], []).append(s)
            slot_next: dict = {}
            for day, lst in by_day.items():
                lst_sorted = sorted(lst, key=lambda x: parse(x["start_time"]))
                for i in range(len(lst_sorted)-1):
                    if parse(lst_sorted[i]["end_time"]) == parse(lst_sorted[i+1]["start_time"]):
                        slot_next[lst_sorted[i]["slot_id"]] = lst_sorted[i+1]["slot_id"]
            sections = sorted(set(o["section_id"] for o in meta["offerings"]))
            class_dir = job_dir / "class_timetables"
            class_dir.mkdir(exist_ok=True)
            if status in (2, 4):
                import csv as _csv
                timetable = list(_csv.DictReader(open(out_csv, newline="", encoding="utf-8")))
                for sec in sections:
                    grid = {d: {p: "—" for p in period_order} for d in days}
                    for row in timetable:
                        if row["section_id"] != sec: continue
                        if row["slot_id"] == "UNASSIGNED": continue
                        sl = next((s for s in time_slots if s["slot_id"] == row["slot_id"]), None)
                        if not sl: continue
                        d = sl["day"]; p = int(sl["period_number"])
                        ccode = courses.get(row["course_id"], {}).get("course_code", row["course_id"])
                        entry = f"{ccode} {row['room_id']} {row['faculty_id']}"
                        grid[d][p] = entry
                        dur = int(courses.get(row["course_id"], {}).get("session_duration", "1") or 1)
                        if dur == 2 and row["slot_id"] in slot_next:
                            nxt = slot_next[row["slot_id"]]
                            sl2 = next((s for s in time_slots if s["slot_id"] == nxt), None)
                            if sl2: grid[sl2["day"]][int(sl2["period_number"])] = entry
                    with open(class_dir / f"{sec}.csv","w",newline="",encoding="utf-8") as f:
                        w = csv2.writer(f)
                        w.writerow(["Day/Period"]+period_headers)
                        for d in days:
                            w.writerow([d]+[grid[d][p] for p in period_order])
            payload = {"status": names.get(status, str(status)), "objective": (solver.ObjectiveValue() if status in (2,4) else None), "output": str(out_csv), "dir": str(job_dir)}
            # merge validation so /api/status can surface it
            payload["validation"] = validation
            jobs[job_id].update(payload)
            _write_status(job_dir, jobs[job_id])
        except Exception as e:
            import traceback
            payload = {"status": f"ERROR: {e}", "trace": traceback.format_exc(), "dir": str(job_dir)}
            jobs[job_id].update(payload)
            _write_status(job_dir, jobs[job_id])
            print(traceback.format_exc())
    background_tasks.add_task(run_solve)
    jobs[job_id] = {"status": "solving", "dir": str(job_dir)}
    # persist solving state
    _write_status(job_dir, jobs[job_id])
    return {"job_id": job_id, "status": "solving", "poll": f"/api/status/{job_id}"}


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
