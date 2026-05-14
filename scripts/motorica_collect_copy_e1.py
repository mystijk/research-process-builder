"""
motorica_collect_copy_e1.py
Appends E1 copy columns to existing E2+LinkedIn sheet.
E1 cols go after LinkedIn cols (W-Y), starting at Z.

Usage:
    py scripts/motorica_collect_copy_e1.py
"""

import csv
import json
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
GWS = ["node", r"C:\Users\mitch\AppData\Roaming\npm\node_modules\@googleworkspace\cli\run-gws.js"]
TOTAL_BATCHES = 49
SHEET_ID = "1CoumzCXPyVg9WZcRokeuOWtTpqOJrNuO604y4x09m-0"
TAB = "Leads + E2 Copy"

# Existing cols: A-V (22 cols lead+E2) + W-Y (3 cols LinkedIn) = 25 cols
# E1 starts at Z (col 25, 0-indexed)
E1_START_COL_IDX = 25
NEW_HEADERS = [
    "e1_subject_animation_director", "e1_body_animation_director",
    "e1_subject_cto", "e1_body_cto",
    "e1_subject_founder", "e1_body_founder",
]


def col_letter(n):
    result = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        result = chr(65 + r) + result
    return result


def run_gws(args, body=None):
    cmd = GWS + args
    if body:
        cmd += ["--json", json.dumps(body, ensure_ascii=False)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        print(f"gws error: {result.stderr[:400]}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def expand_grid(total_cols: int):
    meta = run_gws(["sheets", "spreadsheets", "get", "--params",
                    json.dumps({"spreadsheetId": SHEET_ID})])
    tab_id = meta["sheets"][0]["properties"]["sheetId"]
    run_gws(
        ["sheets", "spreadsheets", "batchUpdate", "--params",
         json.dumps({"spreadsheetId": SHEET_ID})],
        {"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": tab_id, "gridProperties": {"columnCount": total_cols}},
            "fields": "gridProperties.columnCount",
        }}]},
    )
    print(f"Grid expanded to {total_cols} cols")


def main():
    e1_map = {}
    for i in range(TOTAL_BATCHES):
        p = ROOT / "temp" / f"motorica_copy_e1_batch_{i:02d}.json"
        if p.exists():
            for entry in json.loads(p.read_text(encoding="utf-8")):
                e1_map[entry["dev_name"]] = entry.get("copy", {})
    print(f"E1 entries loaded: {len(e1_map)}")

    csv_path = sorted(ROOT.glob("output/motorica-priority-outreach-*.csv"), reverse=True)[0]
    leads = [r["dev_name"] for r in csv.DictReader(open(csv_path, encoding="utf-8-sig"))]
    print(f"Lead order: {len(leads)} rows")

    start_col = col_letter(E1_START_COL_IDX)
    end_col = col_letter(E1_START_COL_IDX + len(NEW_HEADERS) - 1)
    total_cols = E1_START_COL_IDX + len(NEW_HEADERS)

    expand_grid(total_cols)

    values = [NEW_HEADERS]
    for dev in leads:
        copy = e1_map.get(dev, {})
        ad = copy.get("animation_director", {})
        cto = copy.get("cto", {})
        founder = copy.get("founder", {})
        values.append([
            ad.get("subject", ""), ad.get("body", ""),
            cto.get("subject", ""), cto.get("body", ""),
            founder.get("subject", ""), founder.get("body", ""),
        ])

    print(f"Writing {len(values)-1} rows to cols {start_col}-{end_col}...")
    chunk_size = 10
    for i in range(0, len(values), chunk_size):
        chunk = values[i:i + chunk_size]
        row_start = i + 1
        range_str = f"'{TAB}'!{start_col}{row_start}:{end_col}{row_start + len(chunk) - 1}"
        run_gws(
            ["sheets", "spreadsheets", "values", "update",
             "--params", json.dumps({
                 "spreadsheetId": SHEET_ID,
                 "range": range_str,
                 "valueInputOption": "RAW",
             })],
            {"range": range_str, "majorDimension": "ROWS", "values": chunk},
        )
        print(f"  chunk {i//chunk_size + 1}: rows {row_start}-{row_start + len(chunk) - 1}")
        time.sleep(1.5)

    print(f"\nDone. Sheet: https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")


if __name__ == "__main__":
    main()
