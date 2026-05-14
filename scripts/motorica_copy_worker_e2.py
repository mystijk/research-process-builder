"""
motorica_copy_worker_e2.py
Generates E2 email copy × 3 personas for a slice of Motorica leads via Claude Haiku.
Called by Claude Code subagents, one per batch.

Usage:
    py scripts/motorica_copy_worker_e2.py --batch 0 --total-batches 49
    py scripts/motorica_copy_worker_e2.py --batch 7 --total-batches 49
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
load_dotenv(Path(__file__).resolve().parents[2] / "campaign-loop" / ".env", override=False)
load_dotenv(Path.home() / ".env", override=False)

import anthropic

ROOT = Path(__file__).resolve().parent.parent
MODEL_ANTHROPIC = "claude-haiku-4-5-20251001"
MODEL_OPENROUTER = "anthropic/claude-haiku-4-5"

SYSTEM_PROMPT = """\
You complete E2 cold email templates for Motorica. The fixed structure is provided — you write only the BRIDGE sentence and CHARACTER slot for each persona.

## Your only job per persona

1. BRIDGE: one sentence, 10-20 words, tied to the studio's signal and timeline.
2. CHARACTER: a specific character from their known game — name them if known (e.g. "Miles Morales", "Coen from Blood of Dawnwalker"). If no named character is known, describe by role and genre (e.g. "a third-person soulslike warrior", "a combat-heavy protagonist with weapon transitions"). Never invent a vague placeholder like "a lead character" or "a nimble protagonist" — be specific to genre and movement type.
3. SUBJECT: 3-5 words, lowercase, reads like internal Slack. No em dashes.

## BRIDGE rules by timeline

- **post_launch**: what coverage got cut or felt compromised — regret + next project framing.
  animation_director: "looking back at [game], you'd have had more iteration cycles if reshoot risk was off the table."
  cto: "post-ship is the cheapest moment to make the next pipeline decision before architecture locks."
  founder: "you know exactly where motion prep consumed schedule on the last one."

- **active_preproduction** or ship date within 6 months: reshoot risk is live. every design change that goes back to capture costs weeks.
  animation_director: "with [game] in production, every design note that goes back to capture costs creative time you don't have."
  cto: "you're still in the window where motion pipeline decisions don't compound into reshoot debt."
  founder: "four months from ship, one scope change to capture can eat weeks of runway."

- **fresh_announced**: get ahead of coverage before architecture locks.
  animation_director: "with [game] just announced, you can scope the full motion library before anything locks."
  cto: "fresh_announced is when motion pipeline integration is cheapest — before architecture sets."
  founder: "the clock just started on [game] — motion decisions cost the least right now."

- **hiring_mocap**: what does the new hire land into.
  animation_director: "what does the new hire land into — a dataset that's ready or one they have to build from scratch."
  cto: "hiring for mocap means you're scaling a workflow — question is whether that workflow compounds or stays flat."
  founder: "a mocap hire multiplies faster when the dataset infrastructure is already there."

- **no_signal / back_catalog**: what are they building next.
  animation_director: "whatever you're building next, the transition coverage problem is the same."
  cto: "your next title's motion pipeline decision is the cheapest to make before scope locks."
  founder: "whatever comes next, scope stays predictable when you're not dependent on capture rounds."

- **just_funded**: clock starts now.
  animation_director: "fresh capital means scope gets bigger — this is when coverage decisions are cheapest to make."
  cto: "round close is when motion architecture decisions cost the least."
  founder: "clock starts now — motion pipeline locked at round close means schedule stays intact from day one."

## Output format
Return valid JSON only. No markdown fences. No extra keys.
{
  "animation_director": {"subject": "...", "bridge": "...", "character": "..."},
  "cto": {"subject": "...", "bridge": "...", "character": "..."},
  "founder": {"subject": "...", "bridge": "...", "character": "..."}
}
"""


TEMPLATE_ANIMATION_DIRECTOR = (
    'i totally forgot to mention {{FIRST_NAME}}, "motion matching datasets in days" probably sounds a little crazy.\n\n'
    'our founders are actually motion researchers from KTH in Stockholm who spent five years capturing high-quality motion data '
    'to build the dataset behind all of this. that\'s why the output holds up to a creative director\'s eye, it\'s not approximating movement, '
    'it\'s cloning real captured motion.\n\n'
    '{bridge}\n\n'
    'you scope the feel, we generate what you need, and the scope stays predictable.\n\n'
    'want to walk through a live demo? we can show you output on a character like {character}.'
)

TEMPLATE_CTO = (
    'i totally forgot to mention {{FIRST_NAME}}, worth knowing where the output actually comes from.\n\n'
    'our founders are motion researchers out of KTH Stockholm who spent five years building one of the largest high-quality mocap datasets '
    'in the world, and that\'s what the style system trains against. SIGGRAPH-awarded research on motion synthesis, not a wrapper on open source data.\n\n'
    '{bridge}\n\n'
    'FBX straight into your pipeline. you configure the parameters, run generation, data never leaves your environment.\n\n'
    'want me to walk you through how it integrates?'
)

TEMPLATE_FOUNDER = (
    'i totally forgot to mention {{FIRST_NAME}}, that "days not months" thing probably sounds a little crazy.\n\n'
    'our founders actually spent five years in Stockholm capturing one of the biggest high-quality motion datasets in the world. '
    'that\'s what the style cloning trains against and why the output holds up.\n\n'
    '{bridge}\n\n'
    'you scope the work, we deliver the dataset, your schedule stays intact. Platinum Games and Quantic Dream run this workflow now.\n\n'
    'want to walk through a live demo? we can show you output on a character like {character}.'
)


GAME_SHORTS = {
    "DRAGON QUEST VII Reimagined": "DQ7",
    "DRAGON QUEST": "Dragon Quest",
    "Marvel's Spider-Man 2": "Spider-Man 2",
    "Marvel's Spider-Man": "Spider-Man",
    "DOOM: The Dark Ages": "Dark Ages",
    "DOOM Eternal": "DOOM Eternal",
    "Mafia: The Old Country": "The Old Country",
    "The Last of Us Part II Remastered": "TLOU2",
    "The Last of Us™ Part II Remastered": "TLOU2",
    "The Last of Us Part II": "TLOU2",
    "The Last of Us™ Part II": "TLOU2",
    "The Last of Us Part I": "TLOU1",
    "The Last of Us™ Part I": "TLOU1",
    "Lords of the Fallen 2": "LOTF2",
    "Lords of the Fallen": "LOTF",
    "Resident Evil Village": "RE Village",
    "Resident Evil 4": "RE4",
    "Resident Evil Requiem": "RE Requiem",
    "Blood of Dawnwalker": "Dawnwalker",
}


def colloquial(title: str) -> str:
    if not title:
        return title
    if title in GAME_SHORTS:
        return GAME_SHORTS[title]
    if title == title.upper() and len(title) > 3:
        title = title.title()
    if ": " in title:
        main, sub = title.split(": ", 1)
        generic_mains = {"mafia", "call of duty", "far cry", "assassin's creed", "halo", "gears"}
        if main.lower() in generic_mains:
            return sub
        return main
    return title


MOMENT_LABELS = {
    "post_launch": "game already shipped — regret/next project angle",
    "active_preproduction": "in active preproduction — reshoot risk is live",
    "fresh_announced": "just announced — get ahead of scope before architecture locks",
    "hiring_mocap": "hiring for mocap — what does the hire land into",
    "no_signal": "no clear signal — next title framing",
    "back_catalog": "back catalog — next title framing",
    "just_funded": "just raised funding — clock starts now",
}


def build_prompt(row: dict) -> str:
    moment = row.get("outreach_moment", "no_signal")
    game = row.get("mocap_game", "") or ""
    signal_title = row.get("game_signal_title", "") or ""
    note = row.get("personalization_note", "") or ""
    dev = row.get("dev_name", "")
    signal_type = row.get("game_signal_type", "") or ""
    hook_game = signal_title if signal_title and moment in ("fresh_announced", "active_preproduction") else game
    moment_label = MOMENT_LABELS.get(moment, moment)
    hook_short = colloquial(hook_game or game)
    game_short = colloquial(game)

    return (
        f"Studio: {dev}\n"
        f"Situation: {moment_label}\n"
        f"Portfolio game (mocap): {game_short or 'none'}\n"
        f"New/announced game: {colloquial(signal_title) or 'none'}\n"
        f"Hook game (use this exact name in copy): {hook_short or game_short or 'their portfolio'}\n"
        f"Additional context: {note or 'none'}\n"
        f"Signal subtype: {signal_type or 'none'}\n\n"
        f"Write BRIDGE and CHARACTER for all 3 personas.\n"
        f"BRIDGE: one natural sentence using the Hook game name as given. No em dashes. "
        f"No internal labels or jargon. Lowercase except proper nouns and game titles."
    )


def normalize_titles(text: str) -> str:
    for formal, short in sorted(GAME_SHORTS.items(), key=lambda x: -len(x[0])):
        text = re.sub(re.escape(formal), short, text, flags=re.IGNORECASE)
    return text


def assemble_body(template: str, bridge: str, character: str) -> str:
    body = template.format(bridge=bridge.strip(), character=character.strip())
    body = normalize_titles(body)
    return re.sub(r'\s*—\s*', ', ', body)


def generate_copy(client, row: dict, use_openrouter: bool = False) -> dict | None:
    try:
        if use_openrouter:
            resp = client.chat.completions.create(
                model=MODEL_OPENROUTER,
                max_tokens=600,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(row)},
                ],
            )
            raw = resp.choices[0].message.content.strip()
        else:
            msg = client.messages.create(
                model=MODEL_ANTHROPIC,
                max_tokens=600,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_prompt(row)}],
            )
            raw = msg.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        slots = json.loads(raw)

        result = {}
        for persona, template in [
            ("animation_director", TEMPLATE_ANIMATION_DIRECTOR),
            ("cto", TEMPLATE_CTO),
            ("founder", TEMPLATE_FOUNDER),
        ]:
            p = slots.get(persona, {})
            result[persona] = {
                "subject": p.get("subject", ""),
                "body": assemble_body(template, p.get("bridge", ""), p.get("character", "")),
            }
        return result
    except Exception as e:
        print(f"  ERROR {row.get('dev_name')}: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, required=True, help="0-indexed batch number")
    parser.add_argument("--total-batches", type=int, required=True, help="total number of batches")
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

    out_path = ROOT / "temp" / f"motorica_copy_e2_batch_{args.batch:02d}.json"

    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        done = {r["dev_name"] for r in existing if r.get("copy")}
        my_rows = [r for r in my_rows if r["dev_name"] not in done]
        existing = [r for r in existing if r.get("copy")]
        if not my_rows:
            print(f"Batch {args.batch}: all {batch_size} leads cached, skipping")
            return
    else:
        existing = []

    if use_openrouter:
        import openai as openai_sdk
        client = openai_sdk.OpenAI(
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
        )
        print(f"Using OpenRouter (no ANTHROPIC_API_KEY found)")
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
    print(f"Batch {args.batch}: wrote {len(results)} results -> {out_path.name}")


if __name__ == "__main__":
    main()
