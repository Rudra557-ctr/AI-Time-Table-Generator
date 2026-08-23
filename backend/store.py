"""Backend data store — Phase C.

Persists wizard data as `uploads/{job_id}/data.json` (canonical dataset->rows).
Also handles import from legacy `normalized/*.csv` and export for the solver.

The store is the single source of truth for a job; `normalized/` is derived.
"""
from __future__ import annotations

import csv
import json
import pathlib
import tempfile
import os
from typing import Dict, List

from sih_solver.schema import SCHEMAS

# Job id lives under uploads/{job_id}
# data.json shape: {dataset: [row_dict,...], ...}   e.g. {"courses": [{"course_id":"C001",...}, ...]}


def job_data_path(job_dir: pathlib.Path) -> pathlib.Path:
    return job_dir / "data.json"


def normalized_dir(job_dir: pathlib.Path) -> pathlib.Path:
    return job_dir / "normalized"


def init_store(job_dir: pathlib.Path) -> Dict[str, List[Dict[str, str]]]:
    """Create empty store with all datasets as [] and persist. Returns data."""
    job_dir.mkdir(parents=True, exist_ok=True)
    data: Dict[str, List[Dict[str, str]]] = {ds: [] for ds in SCHEMAS.keys()}
    save_store(job_dir, data)
    return data


def load_store(job_dir: pathlib.Path) -> Dict[str, List[Dict[str, str]]]:
    """Load data.json; if missing, try to import from normalized/, else init empty."""
    p = job_data_path(job_dir)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
        # normalize: ensure every dataset key exists as list
        data: Dict[str, List[Dict[str, str]]] = {}
        for ds in SCHEMAS.keys():
            v = raw.get(ds, [])
            # also accept "ds.csv" keys
            if ds not in raw and f"{ds}.csv" in raw:
                v = raw[f"{ds}.csv"]
            # ensure list of dicts with string values
            cleaned: List[Dict[str, str]] = []
            for r in (v or []):
                if isinstance(r, dict):
                    cleaned.append({str(k): ("" if vv is None else str(vv)) for k, vv in r.items()})
            data[ds] = cleaned
        return data
    # no data.json — try normalized/ migration
    nd = normalized_dir(job_dir)
    if nd.exists() and any(nd.glob("*.csv")):
        return import_from_normalized(nd)
    # brand new job
    return {ds: [] for ds in SCHEMAS.keys()}


def save_store(job_dir: pathlib.Path, data: Dict[str, List[Dict[str, str]]]) -> None:
    """Atomic write of data.json (normalized keys, string values)."""
    job_dir.mkdir(parents=True, exist_ok=True)
    p = job_data_path(job_dir)
    # ensure string values and known datasets only
    to_save: Dict[str, List[Dict[str, str]]] = {}
    for ds in SCHEMAS.keys():
        rows = data.get(ds, [])
        # also accept ds.csv key fallback
        if not rows and f"{ds}.csv" in data:
            rows = data[f"{ds}.csv"]
        cleaned: List[Dict[str, str]] = []
        for r in (rows or []):
            if isinstance(r, dict):
                cleaned.append({str(k): ("" if v is None else str(v)) for k, v in r.items()})
        to_save[ds] = cleaned
    # atomic: write to temp then rename
    fd, tmp = tempfile.mkstemp(dir=str(job_dir), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(to_save, f, indent=2, ensure_ascii=False)
        pathlib.Path(tmp).replace(p)
    finally:
        # cleanup partial temp if replace failed
        tp = pathlib.Path(tmp)
        if tp.exists():
            try:
                tp.unlink()
            except Exception:
                pass


def export_to_normalized(data: Dict[str, List[Dict[str, str]]], dest: pathlib.Path) -> None:
    """Write data dict to CSV files under dest using SCHEMAS header order."""
    dest.mkdir(parents=True, exist_ok=True)
    for ds, fields in SCHEMAS.items():
        header = [f["name"] for f in fields]
        rows = data.get(ds, [])
        # also handle ds.csv key
        if not rows and f"{ds}.csv" in data:
            rows = data[f"{ds}.csv"]
        # skip writing entirely if no rows and dataset is not required? We still write header for required
        # to keep solver's load_all predictable, but it's optional — load_all handles missing file as [].
        # For clarity we write required datasets even when empty (header-only).
        from sih_solver.schema import required_datasets
        if not rows and ds not in required_datasets():
            # Remove stale file if previously existed but now empty (optional)
            stale = dest / f"{ds}.csv"
            if stale.exists():
                # keep header-only instead of deleting — either is fine; we choose to keep header for predictability
                pass
            # write header-only for consistency
        path = dest / f"{ds}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
            w.writeheader()
            for r in (rows or []):
                w.writerow({h: str(r.get(h, "")) for h in header})


def import_from_normalized(src: pathlib.Path) -> Dict[str, List[Dict[str, str]]]:
    """Read CSV files from src dir into data dict."""
    data: Dict[str, List[Dict[str, str]]] = {ds: [] for ds in SCHEMAS.keys()}
    for ds in SCHEMAS.keys():
        p = src / f"{ds}.csv"
        if not p.exists():
            # also try ds without extension case variations
            continue
        with open(p, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader) if reader.fieldnames else []
            # normalize values to strings, ensure expected keys exist
            cleaned: List[Dict[str, str]] = []
            for r in rows:
                cleaned.append({str(k): ("" if v is None else str(v)) for k, v in r.items()})
            data[ds] = cleaned
    return data


def set_dataset(data: Dict[str, List[Dict[str, str]]], dataset: str, rows: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    """Return new data dict with one dataset replaced (no mutation of input)."""
    nd = dict(data)
    # normalize dataset key (allow ds.csv)
    ds = dataset[:-4] if dataset.lower().endswith(".csv") else dataset
    if ds not in SCHEMAS:
        raise KeyError(f"Unknown dataset '{dataset}'. Known: {sorted(SCHEMAS.keys())}")
    nd[ds] = [{str(k): ("" if v is None else str(v)) for k, v in (r or {}).items()} for r in (rows or [])]
    return nd


def get_dataset(data: Dict[str, List[Dict[str, str]]], dataset: str) -> List[Dict[str, str]]:
    ds = dataset[:-4] if dataset.lower().endswith(".csv") else dataset
    if ds not in SCHEMAS:
        raise KeyError(f"Unknown dataset '{dataset}'")
    return data.get(ds, [])
