"""Append LinkedIn questions as new columns to the existing E2 campaign sheet."""
import csv, json, subprocess, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
GWS = ["node", r"C:\Users\mitch\AppData\Roaming\npm\node_modules\@googleworkspace\cli\run-gws.js"]
TOTAL_BATCHES = 49
SHEET_ID = "1BKfdq2RH3RGckQllwaV5Vjn34INQh50gi4TaeYT1v98"
TAB = "Leads + E2 Copy"

# E2 sheet has 16 lead cols + 6 copy cols = 22 cols (A-V). LinkedIn goes at W.
LINKEDIN_START_COL = "W"
NEW_HEADERS = ["li_question_animation_director", "li_question_cto", "li_question_founder"]


def col_letter(n):
    """0-indexed column number to letter (0=A, 22=W, etc.)"""
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


def main():
    # Load LinkedIn questions
    li_map = {}
    for i in range(TOTAL_BATCHES):
        p = ROOT / "temp" / f"motorica_linkedin_batch_{i:02d}.json"
        if p.exists():
            for entry in json.loads(p.read_text(encoding="utf-8")):
                li_map[entry["dev_name"]] = entry.get("copy", {})
    print(f"LinkedIn entries loaded: {len(li_map)}")

    # Load lead order from CSV (matches sheet row order)
    csv_path = sorted(ROOT.glob("output/motorica-priority-outreach-*.csv"), reverse=True)[0]
    leads = [r["dev_name"] for r in csv.DictReader(open(csv_path, encoding="utf-8-sig"))]
    print(f"Lead order: {len(leads)} rows")

    # Build column data: header row + one row per lead
    start_col = col_letter(22)  # 0-indexed col 22 = W
    end_col = col_letter(24)    # col 24 = Y

    values = [NEW_HEADERS]
    for dev in leads:
        copy = li_map.get(dev, {})
        values.append([
            copy.get("animation_director", ""),
            copy.get("cto", ""),
            copy.get("founder", ""),
        ])

    print(f"Writing {len(values)-1} rows to columns {start_col}-{end_col}...")
    chunk_size = 25
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
    print(f"\nDone. Sheet: https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")


if __name__ == "__main__":
    main()
