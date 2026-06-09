"""
Unified outreach signal aggregator for Motorica.

Pulls from three Supabase tables + developer CSV, produces one row per studio
with all active signals, sequence assignment, and personalization variables.

Usage:
    py scripts/signal_aggregator.py
    py scripts/signal_aggregator.py --top 200 --dry-run
    py scripts/signal_aggregator.py --top 200
    py scripts/signal_aggregator.py --moment hiring_mocap
    py scripts/signal_aggregator.py --min-signals 2

Output: output/signal_aggregator_YYYY-MM-DD.csv
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

SUPABASE_URL = os.environ.get("SUPABASE_PROJECT_URL") or os.environ.get("SUPABASE_URL") or ""
if SUPABASE_URL and not SUPABASE_URL.startswith("http"):
    SUPABASE_URL = ""
SUPABASE_KEY = (
    os.environ.get("SUPABASE_KEY")
    or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_ANON_KEY")
    or ""
)

DEFAULT_DEV_FILE = r"C:\Users\mitch\Downloads\Telegram Desktop\developers_full_enriched_clay.csv"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

QUALIFYING_TAGS = {
    "action rpg", "soulslike", "souls-like", "open world", "open-world",
    "hack and slash", "hack-and-slash", "third-person", "third person",
    "action", "adventure", "rpg", "metroidvania", "fighting",
    "character action", "action adventure", "looter shooter",
    "third-person shooter", "monster hunter", "co-op", "coop",
}

DISQUALIFYING_TAGS = {
    "casual", "puzzle", "visual novel", "sports", "racing", "simulation",
    "strategy", "turn-based", "card game", "board game", "2d", "pixel",
    "horror", "walking simulator", "idle", "mobile", "anime",
    "vn", "eroge", "adult", "nudity",
}

# outreach_moment → sequence + persona cell + sender assignment
MOMENT_MAP = {
    "active_preproduction": {
        "sequence": "game-signals-v4",
        "cell_ad": "A2",
        "cell_cto_founder": "C1/C2",
        "cell_producer": "",
        "sender_animation": "Jose Luis Garcia Camara",
        "sender_exec": "Willem Demmers",
    },
    "fresh_announced": {
        "sequence": "game-signals-v4",
        "cell_ad": "A2",
        "cell_cto_founder": "C1/C2",
        "cell_producer": "",
        "sender_animation": "Jose Luis Garcia Camara",
        "sender_exec": "Willem Demmers",
    },
    "just_funded": {
        "sequence": "founders-and-ctos-v1",
        "cell_ad": "",
        "cell_cto_founder": "C1/C2",
        "cell_producer": "",
        "sender_animation": "Jamie O'Flanagan",
        "sender_exec": "Willem Demmers",
    },
    "hiring_mocap": {
        "sequence": "v10-ship",
        "cell_ad": "A1",
        "cell_cto_founder": "",
        "cell_producer": "B1",
        "sender_animation": "Jose Luis Garcia Camara",
        "sender_exec": "Jamie O'Flanagan",
    },
    "post_launch": {
        "sequence": "v10-ship",
        "cell_ad": "A1",
        "cell_cto_founder": "",
        "cell_producer": "B1",
        "sender_animation": "Jose Luis Garcia Camara",
        "sender_exec": "Jamie O'Flanagan",
    },
    "back_catalog": {
        "sequence": "v10-ship",
        "cell_ad": "A2",
        "cell_cto_founder": "",
        "cell_producer": "B2",
        "sender_animation": "Jose Luis Garcia Camara",
        "sender_exec": "Jamie O'Flanagan",
    },
}

# Priority order for signal selection (lower index = higher priority)
MOMENT_PRIORITY = [
    "active_preproduction",
    "fresh_announced",
    "just_funded",
    "hiring_mocap",
    "post_launch",
    "back_catalog",
    "no_signal",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def supabase_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def supabase_get_all(table: str, params: str) -> list[dict]:
    """Fetch all rows from a Supabase table with pagination."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print(f"  ERROR: SUPABASE_URL / SUPABASE_KEY not set", file=sys.stderr)
        return []

    headers = supabase_headers()
    headers["Prefer"] = "count=exact"
    page_size = 1000
    offset = 0
    all_rows = []

    while True:
        url = f"{SUPABASE_URL}/rest/v1/{table}?{params}&limit={page_size}&offset={offset}"
        resp = requests.get(url, headers=headers, timeout=30)
        if not resp.ok:
            print(f"  ERROR fetching {table}: HTTP {resp.status_code} — {resp.text[:200]}", file=sys.stderr)
            break
        rows = resp.json()
        if not isinstance(rows, list):
            print(f"  ERROR: unexpected response from {table}: {str(rows)[:200]}", file=sys.stderr)
            break
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size

    return all_rows


def tags_qualify(tags_str: str) -> bool:
    if not tags_str:
        return False
    tags_lower = tags_str.lower()
    if any(t in tags_lower for t in DISQUALIFYING_TAGS):
        return False
    return any(t in tags_lower for t in QUALIFYING_TAGS)


def parse_date(date_str: str) -> datetime | None:
    """Parse ISO date strings from Supabase."""
    if not date_str:
        return None
    cleaned = date_str.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(cleaned[:26], fmt[:len(cleaned)])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    # Fallback: just parse the date part
    try:
        return datetime.strptime(cleaned[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def normalize_name(name: str) -> str:
    return name.strip().lower()


def names_match(dev_name: str, signal_name: str) -> bool:
    """Company name matching: exact only. Substring removed — was causing false positives."""
    if not dev_name or not signal_name:
        return False
    return normalize_name(dev_name) == normalize_name(signal_name)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_developers(filepath: str, top_n: int | None) -> tuple[dict, dict]:
    """Load CSV and group games by developer. Returns (devs, dev_meta)."""
    devs: dict[str, list[dict]] = defaultdict(list)
    dev_meta: dict[str, dict] = {}

    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dev_name = (row.get("dev_name") or row.get("developer") or "").strip()
            if not dev_name:
                continue

            if dev_name not in dev_meta:
                rank_raw = row.get("dev_rank") or ""
                rank = int(rank_raw) if rank_raw.isdigit() else None
                if top_n and rank and rank > top_n:
                    continue
                dev_meta[dev_name] = {
                    "dev_rank": rank,
                    "dev_slug": row.get("dev_slug") or "",
                    "dev_url": row.get("dev_url") or row.get("developer_steamdb_url") or "",
                    "dev_product_count": row.get("dev_product_count") or "",
                    "dev_rating": row.get("dev_rating") or "",
                }
            else:
                rank_val = dev_meta[dev_name]["dev_rank"]
                if top_n and rank_val and rank_val > top_n:
                    continue

            devs[dev_name].append(dict(row))

    return devs, dev_meta


def fetch_steam_signals(dry_run: bool) -> list[dict]:
    """Fetch animation-relevant games from steam_games (prerelease or last 24 months)."""
    if dry_run:
        return []

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=730)).strftime("%Y-%m-%d")

    # We can't filter tags server-side in Supabase REST without full-text search,
    # so fetch prerelease + recent-released rows and filter locally
    params = f"select=dev_name,developer,name,release_state,release_date,tags,genres,appid,followers_count&or=(release_state.eq.prerelease,release_date.gte.{cutoff})"
    print("  Fetching steam_games (prerelease + last 24mo)...")
    rows = supabase_get_all("steam_games", params)
    # Filter to animation-relevant tags
    filtered = [r for r in rows if tags_qualify(r.get("tags") or "")]
    print(f"  steam_games: {len(rows)} rows fetched, {len(filtered)} animation-relevant")
    return filtered


def fetch_game_signals(dry_run: bool) -> list[dict]:
    """Fetch game_signals from last 90 days."""
    if dry_run:
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S")
    params = f"select=signal_type,developer,developer_domain,game_title,funding_amount,genre,platform,article_date,source_url,summary,date_detected&date_detected=gte.{cutoff}"
    print("  Fetching game_signals (last 90 days)...")
    rows = supabase_get_all("game_signals", params)
    print(f"  game_signals: {len(rows)} rows")
    return rows


def fetch_job_signals(dry_run: bool) -> list[dict]:
    """Fetch game_job_signals from last 60 days."""
    if dry_run:
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S")
    params = f"select=job_id,job_title,company_name,company_domain,signal_strength,signal_keywords,job_url,date_detected&date_detected=gte.{cutoff}"
    print("  Fetching game_job_signals (last 60 days)...")
    rows = supabase_get_all("game_job_signals", params)
    print(f"  game_job_signals: {len(rows)} rows")
    return rows


# ---------------------------------------------------------------------------
# Signal matching
# ---------------------------------------------------------------------------

def match_steam_signals(dev_name: str, steam_rows: list[dict]) -> list[dict]:
    return [
        r for r in steam_rows
        if names_match(dev_name, r.get("dev_name") or r.get("developer") or "")
    ]


def match_game_signals(dev_name: str, game_signal_rows: list[dict]) -> list[dict]:
    matched = []
    for r in game_signal_rows:
        sig_dev = r.get("developer") or ""
        if names_match(dev_name, sig_dev):
            matched.append(r)
    return matched


def match_job_signals(dev_name: str, job_rows: list[dict]) -> list[dict]:
    return [
        r for r in job_rows
        if names_match(dev_name, r.get("company_name") or "")
    ]


# ---------------------------------------------------------------------------
# Outreach moment classification
# ---------------------------------------------------------------------------

def classify_moment(
    dev_name: str,
    games: list[dict],          # CSV rows for this developer
    steam_signals: list[dict],  # matching steam_games rows
    funding_signals: list[dict],
    announcement_signals: list[dict],
    job_signals: list[dict],
) -> str:
    now = datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=30)
    cutoff_60d = now - timedelta(days=60)
    cutoff_24mo = now - timedelta(days=730)

    # active_preproduction: prerelease game in steam_games with animation tags.
    # Hard filter: followers_count must be known AND > 500. Removes noise from tiny/unknown
    # studios that inflated the count to 89/200 via substring matching + no follower gate.
    _sample_prerelease = [r for r in steam_signals if (r.get("release_state") or "").lower() == "prerelease"]
    prerelease = [
        r for r in _sample_prerelease
        if r.get("followers_count") is not None and (r.get("followers_count") or 0) > 500
    ]
    if prerelease:
        return "active_preproduction"

    # fresh_announced: game_announcement in game_signals < 30 days
    for sig in announcement_signals:
        detected = parse_date(sig.get("date_detected") or sig.get("article_date") or "")
        if detected and detected >= cutoff_30d:
            return "fresh_announced"

    # just_funded: studio_funding in game_signals < 60 days
    for sig in funding_signals:
        detected = parse_date(sig.get("date_detected") or sig.get("article_date") or "")
        if detected and detected >= cutoff_60d:
            return "just_funded"

    # hiring_mocap: high-signal job in game_job_signals
    high_jobs = [j for j in job_signals if (j.get("signal_strength") or "").lower() == "high"]
    if high_jobs:
        return "hiring_mocap"

    # post_launch: shipped animation game < 24 months (from steam_signals)
    recent_released = [
        r for r in steam_signals
        if (r.get("release_state") or "").lower() != "prerelease"
    ]
    for r in recent_released:
        rd = parse_date(r.get("release_date") or "")
        if rd and rd >= cutoff_24mo:
            return "post_launch"

    # back_catalog: shipped animation game > 24 months (from steam_signals)
    if steam_signals:
        return "back_catalog"

    # Check CSV games as fallback (when dry_run skips Supabase)
    for game in games:
        state = (game.get("release_state") or "").lower()
        tags = game.get("tags") or ""
        if not tags_qualify(tags):
            continue
        if state == "prerelease":
            return "active_preproduction"
        from stage_classifier import parse_release_date
        rd = parse_release_date(game.get("release_date") or "")
        if rd:
            if rd >= cutoff_24mo:
                return "post_launch"
            else:
                return "back_catalog"

    return "no_signal"


# ---------------------------------------------------------------------------
# Output row builder
# ---------------------------------------------------------------------------

def pick_primary_game(
    steam_signals: list[dict],
    announcement_signals: list[dict],
    moment: str,
) -> tuple[str, str]:
    """Return (game_title, prior_game_title)."""
    if moment in ("active_preproduction",):
        prerelease = [r for r in steam_signals if (r.get("release_state") or "").lower() == "prerelease"]
        released = [r for r in steam_signals if (r.get("release_state") or "").lower() != "prerelease"]
        primary = prerelease[0]["name"] if prerelease else ""
        prior = released[0]["name"] if released else ""
        return primary, prior

    if moment == "fresh_announced":
        primary = announcement_signals[0].get("game_title") or "" if announcement_signals else ""
        # prior from steam
        released = [r for r in steam_signals if (r.get("release_state") or "").lower() != "prerelease"]
        prior = released[0].get("name") or "" if released else ""
        return primary, prior

    # post_launch / back_catalog / hiring_mocap / just_funded
    released = sorted(
        [r for r in steam_signals if r.get("release_date")],
        key=lambda r: r.get("release_date") or "",
        reverse=True,
    )
    primary = released[0].get("name") or "" if released else ""
    prior = released[1].get("name") or "" if len(released) > 1 else ""
    return primary, prior


def personalization_note(
    moment: str,
    game_title: str,
    prior_game: str,
    funding_amount: str,
    job_title: str,
    announcement_summary: str,
) -> str:
    if moment == "active_preproduction":
        return (
            f"Studio building {game_title} — unreleased title with animation demands. "
            f"Prior shipped: {prior_game or 'none found'}. Game title as entry point."
        )
    if moment == "fresh_announced":
        return (
            f"Just announced {game_title or 'new game'}. "
            + (f"Summary: {announcement_summary[:100]}." if announcement_summary else "Pre-production window — high mocap evaluation intent.")
        )
    if moment == "just_funded":
        amt = f"({funding_amount}) " if funding_amount else ""
        return (
            f"Recently funded {amt}— do-more-with-less mandate in play. "
            f"Reference {game_title or 'prior title'} as production scope signal."
        )
    if moment == "hiring_mocap":
        return (
            f"Actively hiring: {job_title or 'animation/mocap role'}. "
            f"Live hiring signal = evaluation window. {game_title or ''}"
        ).strip()
    if moment == "post_launch":
        return (
            f"Shipped {game_title} recently. Post-launch = animation system already stress-tested. "
            f"Prior: {prior_game or 'none'}."
        )
    if moment == "back_catalog":
        return (
            f"Prior title {game_title} is the proof point. "
            "No active release — prior work signals animation investment appetite."
        )
    return ""


def build_row(
    dev_name: str,
    meta: dict,
    moment: str,
    steam_signals: list[dict],
    funding_sigs: list[dict],
    announce_sigs: list[dict],
    job_sigs: list[dict],
) -> dict:
    seq = MOMENT_MAP.get(moment, {})
    game_title, prior_game = pick_primary_game(steam_signals, announce_sigs, moment)

    funding_amount = funding_sigs[0].get("funding_amount") or "" if funding_sigs else ""
    job_title = job_sigs[0].get("job_title") or "" if job_sigs else ""
    def _kw_str(val):
        if isinstance(val, list):
            return ", ".join(str(v) for v in val if v)
        return str(val) if val else ""
    signal_keywords = ", ".join(filter(None, [
        _kw_str(j.get("signal_keywords")) for j in job_sigs
    ])) if job_sigs else ""
    announcement_summary = announce_sigs[0].get("summary") or "" if announce_sigs else ""
    if announce_sigs:
        article_url = announce_sigs[0].get("source_url") or ""
    elif funding_sigs:
        article_url = funding_sigs[0].get("source_url") or ""
    else:
        article_url = ""

    signal_count = (
        len(steam_signals) + len(funding_sigs) + len(announce_sigs) + len(job_sigs)
    )

    return {
        "dev_name": dev_name,
        "dev_rank": meta.get("dev_rank") or "",
        "dev_url": meta.get("dev_url") or "",
        "dev_rating": meta.get("dev_rating") or "",
        "outreach_moment": moment,
        "sequence": seq.get("sequence") or "",
        "cell_ad": seq.get("cell_ad") or "",
        "cell_cto_founder": seq.get("cell_cto_founder") or "",
        "cell_producer": seq.get("cell_producer") or "",
        "sender_animation": seq.get("sender_animation") or "",
        "sender_exec": seq.get("sender_exec") or "",
        "game_title": game_title,
        "prior_game_title": prior_game,
        "funding_amount": funding_amount,
        "job_title": job_title,
        "signal_keywords": signal_keywords,
        "announcement_summary": announcement_summary[:200] if announcement_summary else "",
        "article_url": article_url,
        "signal_count": signal_count,
        "personalization_note": personalization_note(
            moment, game_title, prior_game, funding_amount, job_title, announcement_summary
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Motorica signal aggregator — unified outreach routing")
    parser.add_argument("--dev-file", default=DEFAULT_DEV_FILE)
    parser.add_argument("--top", type=int, default=None, help="Only process top N developers by rank")
    parser.add_argument("--moment", help="Filter output to specific outreach_moment")
    parser.add_argument("--min-signals", type=int, default=1, help="Min active signals required (default: 1)")
    parser.add_argument("--dry-run", action="store_true", help="Skip Supabase queries, use CSV data only")
    args = parser.parse_args()

    dev_file = args.dev_file
    if not Path(dev_file).exists():
        print(f"ERROR: Dev file not found: {dev_file}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {dev_file}...")
    devs, dev_meta = load_developers(dev_file, args.top)
    print(f"Loaded {len(devs)} unique developers" + (f" (top {args.top})" if args.top else ""))

    if args.dry_run:
        print("DRY RUN — skipping Supabase queries")
        steam_rows, game_signal_rows, job_signal_rows = [], [], []
    else:
        if not SUPABASE_URL or not SUPABASE_KEY:
            print("ERROR: SUPABASE_URL and SUPABASE_KEY required (or use --dry-run)", file=sys.stderr)
            sys.exit(1)
        steam_rows = fetch_steam_signals(args.dry_run)
        game_signal_rows = fetch_game_signals(args.dry_run)
        job_signal_rows = fetch_job_signals(args.dry_run)

    funding_rows = [r for r in game_signal_rows if r.get("signal_type") == "studio_funding"]
    announce_rows = [r for r in game_signal_rows if r.get("signal_type") == "game_announcement"]

    rows = []
    moment_counts: dict[str, int] = defaultdict(int)

    for dev_name, games in devs.items():
        meta = dev_meta.get(dev_name, {})

        steam_signals = match_steam_signals(dev_name, steam_rows)
        funding_sigs = match_game_signals(dev_name, funding_rows)
        announce_sigs = match_game_signals(dev_name, announce_rows)
        job_sigs = match_job_signals(dev_name, job_signal_rows)

        moment = classify_moment(
            dev_name, games, steam_signals, funding_sigs, announce_sigs, job_sigs
        )
        moment_counts[moment] += 1

        if moment == "no_signal":
            continue

        signal_count = len(steam_signals) + len(funding_sigs) + len(announce_sigs) + len(job_sigs)
        if signal_count < args.min_signals:
            # In dry-run, CSV-classified rows have signal_count=0 from Supabase perspective
            # but we still want to see them; only enforce when we have live data
            if not args.dry_run:
                continue

        if args.moment and moment != args.moment:
            continue

        rows.append(build_row(dev_name, meta, moment, steam_signals, funding_sigs, announce_sigs, job_sigs))

    # Sort by moment priority then dev_rank
    rows.sort(key=lambda r: (
        MOMENT_PRIORITY.index(r["outreach_moment"]) if r["outreach_moment"] in MOMENT_PRIORITY else 99,
        int(r["dev_rank"]) if str(r["dev_rank"]).isdigit() else 9999,
    ))

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = OUTPUT_DIR / f"signal_aggregator_{today}.csv"

    if rows:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nOutput: {out_path}")
    else:
        print("\nNo rows matched — output file not written")

    print(f"Total output rows: {len(rows)}")
    print("\nOutreach moment breakdown (all developers):")
    for m in MOMENT_PRIORITY:
        count = moment_counts.get(m, 0)
        seq = MOMENT_MAP.get(m, {}).get("sequence", "-")
        print(f"  {m:<25} {count:>5}  ->  {seq}")

    if rows:
        print("\nTop 10 studios:")
        for r in rows[:10]:
            print(f"  [{r['outreach_moment']:<22}] {r['dev_name']:<35} game={r['game_title'] or '—'}")


if __name__ == "__main__":
    main()
