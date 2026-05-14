"""
motorica_copy_worker_linkedin.py
Generates single-line LinkedIn questions × 3 personas for Motorica leads.
One uncomfortable, specific question per persona. No greeting, no name, no pitch.

Usage:
    py scripts/motorica_copy_worker_linkedin.py --batch 0 --total-batches 49
"""

import argparse
import csv
import json
import math
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

import anthropic

ROOT = Path(__file__).resolve().parent.parent
MODEL_ANTHROPIC = "claude-haiku-4-5-20251001"
MODEL_OPENROUTER = "anthropic/claude-haiku-4-5"

SYSTEM_PROMPT = """\
You write single-line LinkedIn questions for Motorica outreach. One question per persona.

## What these questions must do

Poke the bear. Make the reader feel seen. Reference something specific about their game, their production, or their pipeline. The question should be uncomfortable to ignore — it names a real problem they've lived through.

No greeting. No name. No Motorica mention. No pitch. Just the question. Lowercase throughout except game titles, studio names, character names.

## Persona angles

**animation_director**: craft and creative time — coverage that got cut, transitions that didn't get enough iteration, reshoots that ate the schedule, scope decisions that hurt the final feel. They care about what the game could have been.

**cto**: pipeline cost and architecture — capture time vs cleanup time, reshoot cycles as technical debt, what a design change costs in pipeline days. They care about what the production actually cost.

**founder**: schedule and scope predictability — weeks lost to mocap, scope that expanded beyond the budget, production decisions driven by capture limits not creative vision. They care about what it cost the studio.

## Signal rules

- **post_launch**: regret or cost framing. what got cut, what went twice, what consumed weeks. reference the specific game by name.
- **active_preproduction** or close to ship: pressure framing. how many cycles does this have, when does the window close, what does a direction change cost right now.
- **fresh_announced**: scope framing. how big is the motion library, when does architecture lock, how many states are you planning before scope creeps.
- **hiring_mocap**: inheritance framing. what does the hire land into, dataset ready or year-one rebuild, is the workflow they're hiring into already solved or still being built.
- **no_signal / back_catalog**: craft or pipeline question tied to their known game or genre. what would they do differently, what did the last one cost, what does their motion pipeline look like for whatever's next.
- **just_funded**: timing framing. clock started, when does the motion architecture decision get made, what's the cost if you make it in production vs now.

## Good examples

post_launch / animation_director:
- "how many transitions in Mafia: The Old Country did your team build twice?"
- "what coverage did you cut from Sniper Elite: Resistance before ship that you're still thinking about?"
- "how much of DOOM: The Dark Ages locomotion was first take vs rebuild?"

post_launch / cto:
- "what percentage of your DOOM: The Dark Ages capture budget went to cleanup vs content?"
- "how many pipeline days did a single direction change cost on Mafia: The Old Country?"

post_launch / founder:
- "how many weeks did mocap debt add to Sniper Elite: Resistance's schedule?"
- "what would you do differently on DOOM: The Dark Ages if the motion pipeline was already solved?"

fresh_announced / animation_director:
- "at what point in Resident Evil Requiem's production does the reshoot window close?"
- "how many locomotion states are you scoping for Resident Evil Requiem before the first design review?"

hiring_mocap / animation_director:
- "is the mocap pipeline your new Facial Character TD is inheriting at Insomniac already solved, or are they walking into a rebuild?"

## Variety rules

Each persona should use a different question structure — don't use "what percentage of X went to Y" for more than one persona. Don't repeat the same sentence skeleton across studios. Use different entry angles:
- regret framing: "what would you do differently on [GAME]..."
- count framing: "how many times did [CHARACTER/STATE] get rebuilt..."
- cost framing: "how many weeks did [X] add to [GAME]'s schedule..."
- inheritance framing: "what does [NEW HIRE / NEXT TITLE] walk into..."
- scope framing: "when does [GAME]'s motion library scope lock..."
- pressure framing: "what does a direction change cost [GAME]'s pipeline right now..."

Mix the angles. No two personas should use the same structure. The CTO question especially should NOT default to "what percentage of X went to Y" — use pipeline debt, architecture timing, or cost-of-change framing instead.

## Bad examples (never write these)

- "have you ever thought about your animation pipeline?" (too vague)
- "what's your current mocap process?" (no specificity, no pressure)
- "how do you handle motion matching at your studio?" (generic, no game reference)
- anything starting with "Hi", "Hey", a name, or a Motorica mention
- same question skeleton repeated across animation_director / cto / founder

## Output format

Return valid JSON only. No markdown fences. No extra keys.
{
  "animation_director": "single question here?",
  "cto": "single question here?",
  "founder": "single question here?"
}
"""

GAME_SHORTS = {
    "DRAGON QUEST VII Reimagined": "DQ7",
    "DRAGON QUEST": "Dragon Quest",
    "Marvel's Spider-Man 2": "Spider-Man 2",
    "Marvel's Spider-Man": "Spider-Man",
    "DOOM: The Dark Ages": "Dark Ages",
    "DOOM Eternal": "DOOM Eternal",
    "Mafia: The Old Country": "The Old Country",
    "The Last of Us Part II": "TLOU2",
    "The Last of Us Part I": "TLOU1",
    "Lords of the Fallen 2": "LOTF2",
    "Lords of the Fallen": "LOTF",
    "Resident Evil Village": "RE Village",
    "Resident Evil 4": "RE4",
    "Resident Evil Requiem": "RE Requiem",
    "Blood of Dawnwalker": "Dawnwalker",
    "Mortal Shell 2": "Mortal Shell 2",
}


def colloquial(title: str) -> str:
    """Return the natural short form a developer would use in conversation."""
    if not title:
        return title
    if title in GAME_SHORTS:
        return GAME_SHORTS[title]
    # All-caps title → title-case it
    if title == title.upper() and len(title) > 3:
        title = title.title()
    # Strip subtitle after colon if main title is recognizable (keep if subtitle is the famous part)
    if ": " in title:
        main, sub = title.split(": ", 1)
        # Keep subtitle if main is generic (e.g. "Mafia" keeps "The Old Country")
        generic_mains = {"mafia", "call of duty", "far cry", "assassin's creed", "halo", "gears"}
        if main.lower() in generic_mains:
            return sub  # "The Old Country" reads better
        return main  # "Sniper Elite" drops ": Resistance" for brevity
    return title


MOMENT_LABELS = {
    "post_launch": "game already shipped — regret/cost angle",
    "active_preproduction": "in active preproduction — pressure angle",
    "fresh_announced": "just announced — scope angle",
    "hiring_mocap": "hiring for mocap — what does the hire land into",
    "no_signal": "no clear signal — craft/pipeline question tied to their known game",
    "back_catalog": "back catalog — what would they do differently",
    "just_funded": "just raised — timing angle, clock started",
}


def build_prompt(row: dict) -> str:
    moment = row.get("outreach_moment", "no_signal")
    game = row.get("mocap_game", "") or ""
    signal_title = row.get("game_signal_title", "") or ""
    note = row.get("personalization_note", "") or ""
    dev = row.get("dev_name", "")
    job_title = row.get("job_title", "") or ""
    signal_type = row.get("game_signal_type", "") or ""
    hook_game = signal_title if signal_title and moment in ("fresh_announced", "active_preproduction") else game
    hook_game_short = colloquial(hook_game or game)
    game_short = colloquial(game)

    lines = [
        f"Studio: {dev}",
        f"Situation: {MOMENT_LABELS.get(moment, moment)}",
        f"Known game (portfolio): {game_short or 'none'}",
        f"New/announced game: {colloquial(signal_title) or 'none'}",
        f"Hook game (use this exact name in copy): {hook_game_short or game_short or 'none'}",
        f"Hiring signal: {job_title or 'none'}",
        f"Additional context: {note or 'none'}",
    ]
    lines.append("")
    lines.append(
        "Write one single-line LinkedIn question per persona. "
        "Use the 'Hook game' name exactly as given — it is already the natural short form a developer would say. "
        "Lowercase except game titles. No em dashes. Ends with '?'. No Motorica mention. No greeting."
    )
    return "\n".join(lines)


def generate_copy(client, row: dict, use_openrouter: bool = False) -> dict | None:
    try:
        if use_openrouter:
            resp = client.chat.completions.create(
                model=MODEL_OPENROUTER,
                max_tokens=300,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(row)},
                ],
            )
            raw = resp.choices[0].message.content.strip()
        else:
            msg = client.messages.create(
                model=MODEL_ANTHROPIC,
                max_tokens=300,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_prompt(row)}],
            )
            raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)
        # strip em dashes just in case
        for persona in result:
            if isinstance(result[persona], str):
                result[persona] = re.sub(r"\s*—\s*", ", ", result[persona])
        return result
    except Exception as e:
        print(f"  ERROR {row.get('dev_name')}: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, required=True)
    parser.add_argument("--total-batches", type=int, required=True)
    args = parser.parse_args()

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not anthropic_key and not openrouter_key:
        print("ERROR: ANTHROPIC_API_KEY or OPENROUTER_API_KEY must be set", file=sys.stderr)
        sys.exit(1)
    use_openrouter = not anthropic_key and bool(openrouter_key)

    csv_path = sorted(ROOT.glob("output/motorica-priority-outreach-*.csv"), reverse=True)
    if not csv_path:
        print("ERROR: no motorica-priority-outreach CSV found", file=sys.stderr)
        sys.exit(1)

    with open(csv_path[0], encoding="utf-8-sig") as f:
        all_rows = list(csv.DictReader(f))

    batch_size = math.ceil(len(all_rows) / args.total_batches)
    start = args.batch * batch_size
    end = min(start + batch_size, len(all_rows))
    my_rows = all_rows[start:end]

    out_path = ROOT / "temp" / f"motorica_linkedin_batch_{args.batch:02d}.json"

    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        done = {r["dev_name"] for r in existing}
        my_rows = [r for r in my_rows if r["dev_name"] not in done]
        if not my_rows:
            print(f"Batch {args.batch}: all cached, skipping")
            return
    else:
        existing = []

    if use_openrouter:
        import openai as openai_sdk
        client = openai_sdk.OpenAI(api_key=openrouter_key, base_url="https://openrouter.ai/api/v1")
        print("Using OpenRouter")
    else:
        client = anthropic.Anthropic(api_key=anthropic_key)
    results = list(existing)

    print(f"Batch {args.batch}: {len(my_rows)} leads (rows {start}-{end-1})")
    for row in my_rows:
        name = row["dev_name"]
        print(f"  generating: {name} ({row.get('outreach_moment', '?')})")
        copy = generate_copy(client, row, use_openrouter=use_openrouter)
        if copy:
            results.append({"dev_name": name, "copy": copy})
            print(f"    ok")
        else:
            results.append({"dev_name": name, "copy": {}})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Batch {args.batch}: wrote {len(results)} -> {out_path.name}")


if __name__ == "__main__":
    main()
