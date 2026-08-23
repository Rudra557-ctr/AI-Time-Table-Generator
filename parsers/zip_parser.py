import zipfile, pathlib, shutil

def extract_zip(zip_path, dest_dir):
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(dest_dir)
    # Handle nested folder (like sih_timetable_dataset_corrected/ inside)
    # If dest contains single folder, move its contents up
    subdirs = [p for p in dest_dir.iterdir() if p.is_dir()]
    if len(subdirs)==1 and len(list(dest_dir.glob("*.csv")))==0:
        for f in subdirs[0].iterdir():
            shutil.move(str(f), str(dest_dir / f.name))
        subdirs[0].rmdir()
    return dest_dir

def handle_xlsx_in_folder(folder):
    """Convert any XLSX in folder to CSV sidecar."""
    from .xlsx_parser import xlsx_to_csv
    for xlsx in list(folder.rglob("*.xlsx")) + list(folder.rglob("*.XLSX")):
        csv_path = xlsx.with_suffix(".csv")
        try:
            xlsx_to_csv(xlsx, csv_path)
        except Exception as e:
            print(f"XLSX convert failed {xlsx}: {e}")
    return folder
