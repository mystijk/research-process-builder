"""
motorica_collect_copy_e2.py
Merges all E2 batch JSON files from temp/ and pushes to Google Sheet.
Run after all 49 worker agents complete.

Usage:
    py scripts/motorica_collect_copy_e2.py
    py scripts/motorica_collect_copy_e2.py --check
"""

import argparse
import csv
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
GWS = ["node", r"C:\Users\mitch\AppData\Roaming\npm\node_modules\@googleworkspace\cli\run-gws.js"]
TOTAL_BATCHES = 49

LEAD_COLUMNS = [
    "dev_name", "domain", "country", "employees", "firm_size",
    "outreach_moment", "sequence", "sender",
    "mocap_game", "game_signal_title", "game_signal_type", "game_signal_date",
    "personalization_note", "outreach_priority",
    "linkedin_url", "steamdb_url",
]

COPY_COLUMNS = [
    "e2_subject_animation_director", "e2_body_animation_director",
    "e2_subject_cto", "e2_body_cto",
    "e2_subject_founder", "e2_body_founder",
]


def check_batches() -> dict[int, bool]:
    status = {}
    for i in range(TOTAL_BATCHES):
        p = ROOT / "temp" / f"motorica_copy_e2_batch_{i:02d}.json"
        status[i] = p.exists()
    return status


def load_all_copy() -> dict[str, dict]:
    merged = {}
    for i in range(TOTAL_BATCHES):
        p = ROOT / "temp" / f"motorica_copy_e2_batch_{i:02d}.json"
        if not p.exists():
            continue
        for entry in json.loads(p.read_text(encoding="utf-8")):
            merged[entry["dev_name"]] = entry.get("copy", {})
    return merged


def run_gws(args, body=None):
    cmd = GWS + args
    if body:
        cmd += ["--json", json.dumps(body, ensure_ascii=False)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        print(f"gws error: {result.stderr[:400]}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def write_sheet(sid: str, tab: str, headers: list, rows: list):
    all_data = [headers] + rows
    chunk_size = 5  # email bodies are large; keep under Windows 32K CLI limit
    for i in range(0, len(all_data), chunk_size):
        chunk = all_data[i:i + chunk_size]
        run_gws(
            ["sheets", "spreadsheets", "values", "update",
             "--params", json.dumps({
                 "spreadsheetId": sid,
                 "range": f"'{tab}'!A{i + 1}",
                 "valueInputOption": "RAW",
             })],
            {"range": f"'{tab}'!A{i + 1}", "majorDimension": "ROWS", "values": chunk},
        )
    print(f"  wrote {len(rows)} rows")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Report batch status only")
    args = parser.parse_args()

    status = check_batches()
    done = sum(status.values())
    missing = [i for i, v in status.items() if not v]

    print(f"Batch status: {done}/{TOTAL_BATCHES} complete")
    if missing:
        print(f"Missing batches: {missing}")

    if args.check:
        return

    if missing:
        print(f"\nWARN: {len(missing)} batches missing. Proceeding with available data.")

    csv_path = sorted(ROOT.glob("output/motorica-priority-outreach-*.csv"), reverse=True)
    if not csv_path:
        print("ERROR: no motorica-priority-outreach CSV found", file=sys.stderr)
        sys.exit(1)

    with open(csv_path[0], encoding="utf-8-sig") as f:
        all_rows = list(csv.DictReader(f))

    copy_map = load_all_copy()
    print(f"Copy entries loaded: {len(copy_map)}")

    headers = LEAD_COLUMNS + COPY_COLUMNS
    sheet_rows = []
    no_copy = []

    for r in all_rows:
        name = r.get("dev_name", "")
        copy = copy_map.get(name, {})
        if not copy:
            no_copy.append(name)

        lead_vals = [r.get(c, "") for c in LEAD_COLUMNS]
        ad = copy.get("animation_director", {})
        cto = copy.get("cto", {})
        founder = copy.get("founder", {})
        copy_vals = [
            ad.get("subject", ""), ad.get("body", ""),
            cto.get("subject", ""), cto.get("body", ""),
            founder.get("subject", ""), founder.get("body", ""),
        ]
        sheet_rows.append(lead_vals + copy_vals)

    if no_copy:
        print(f"No copy for {len(no_copy)} leads: {no_copy[:5]}{'...' if len(no_copy) > 5 else ''}")

    print("Creating Google Sheet...")
    result = run_gws(
        ["sheets", "spreadsheets", "create"],
        {
            "properties": {"title": f"Motorica — E2 Copy {date.today()}"},
            "sheets": [{
                "properties": {
                    "title": "Leads + E2 Copy",
                    "index": 0,
                    "gridProperties": {
                        "rowCount": len(sheet_rows) + 5,
                        "columnCount": len(headers),
                    },
                }
            }],
        },
    )
    sid = result["spreadsheetId"]
    url = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    print(f"  ID: {sid}")
    write_sheet(sid, "Leads + E2 Copy", headers, sheet_rows)
    print(f"\nSheet: {url}")


if __name__ == "__main__":
    main()
