"""Collect all LinkedIn batch files into a Google Sheet."""
import csv, json, math, os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

ROOT = Path(__file__).resolve().parent.parent
TOTAL_BATCHES = 49

def main():
    batches = [ROOT / "temp" / f"motorica_linkedin_batch_{i:02d}.json" for i in range(TOTAL_BATCHES)]
    complete = sum(1 for b in batches if b.exists())
    print(f"Batch status: {complete}/{TOTAL_BATCHES} complete")

    entries = []
    for b in batches:
        if b.exists():
            entries.extend(json.loads(b.read_text(encoding="utf-8")))
    print(f"Entries loaded: {len(entries)}")

    # Load CSV for metadata
    csv_path = sorted(ROOT.glob("output/motorica-priority-outreach-*.csv"), reverse=True)[0]
    meta = {r["dev_name"]: r for r in csv.DictReader(open(csv_path, encoding="utf-8-sig"))}

    rows = []
    for entry in entries:
        dev = entry["dev_name"]
        m = meta.get(dev, {})
        copy = entry.get("copy", {})
        rows.append({
            "dev_name": dev,
            "outreach_moment": m.get("outreach_moment", ""),
            "mocap_game": m.get("mocap_game", ""),
            "game_signal_title": m.get("game_signal_title", ""),
            "linkedin_url": m.get("linkedin_url", ""),
            "animation_director_question": copy.get("animation_director", ""),
            "cto_question": copy.get("cto", ""),
            "founder_question": copy.get("founder", ""),
        })

    import subprocess, tempfile, datetime
    date_str = datetime.date.today().isoformat()
    sheet_title = f"Motorica LinkedIn Questions {date_str}"

    # Write via gws
    payload = {
        "title": sheet_title,
        "sheets": [{
            "name": "LinkedIn Questions",
            "headers": list(rows[0].keys()),
            "rows": [[str(r.get(k, "")) for k in rows[0].keys()] for r in rows],
        }]
    }
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp, ensure_ascii=False)
    tmp.close()

    gws = "gws.cmd" if sys.platform == "win32" else "gws"
    result = subprocess.run([gws, "sheets", "create", "--from-json", tmp.name], capture_output=True, text=True)
    os.unlink(tmp.name)

    if result.returncode != 0:
        print("gws error:", result.stderr)
        # Fallback: write CSV
        out = ROOT / "output" / f"motorica-linkedin-questions-{date_str}.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote CSV: {out}")
        return

    for line in result.stdout.splitlines():
        if "spreadsheets" in line or "ID" in line or "wrote" in line.lower():
            print(line)

if __name__ == "__main__":
    main()
