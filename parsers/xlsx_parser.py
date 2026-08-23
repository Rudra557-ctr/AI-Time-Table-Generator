"""XLSX -> CSV conversion for upload."""
import pathlib

def xlsx_to_csv(xlsx_path, csv_path):
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl not installed – pip install openpyxl")
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Empty XLSX")
    headers = [str(c).strip() if c else "" for c in rows[0]]
    import csv
    with open(csv_path, "w", newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows[1:]:
            if all(v is None for v in r):
                continue
            w.writerow({h: (str(v).strip() if v is not None else "") for h,v in zip(headers, r)})
    return csv_path
