"""
motorica_copy_worker_e1.py
Generates E1 cold email copy × 3 personas for Motorica leads via Claude Haiku.
Model writes only: hook (2 sentences), question (1 sentence), character, subject.
Fixed Motorica pitch + CTA injected in Python per persona.

Usage:
    py scripts/motorica_copy_worker_e1.py --batch 0 --total-batches 49
    py scripts/motorica_copy_worker_e1.py --batch 7 --total-batches 49
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
You write E1 cold email slots for Motorica outreach. You write only: HOOK, QUESTION, CHARACTER, SUBJECT.

## Tone and length — this is everything

Short. Direct. One uncomfortable sentence, then one short question. Nothing analytical. No summaries of what the signal means. No multi-clause explanations.

**Bad hook (too analytical):**
"The Old Country locked a motion library for a specific historical period, which meant every character, every weapon, every vehicle interaction had to feel authentically 1920s."

**Good hook (tight, direct):**
"any animation on The Old Country you wish you could go back and reshoot?"

**Bad question:**
"if you're greenlighting the next project, how much earlier would you lock motion architecture to avoid the reshoot risk Old Country created?"

**Good question:**
"can your team realistically deliver both without something breaking?"

---

## HOOK: 1-2 sentences MAX

State the signal pressure or ask the gut-punch question. Never summarize context. Never explain what the signal means. Just name the uncomfortable thing.

- founder: scope or schedule crunch. "the alpha is public and co-op is promised. that means every locomotion state ships for two heroes, not one."
- cto: pipeline volume or architecture cost. "no stamina means full angular coverage for every speed, direction, and combat state. that's 500+ clips per hero through your pipeline."
- animation_director: can be a question: "any animation on [GAME] you wish you could go back and reshoot?" OR tight pressure: "no stamina means every transition has to work. a player can dodge mid-swing, chain a sprint into a combo, roll out of anything."

Post-launch angle: regret. "any animation on [GAME] you wish you could go back and reshoot?" works for animation_director and founder.
Active/fresh: scope and reshoot risk live now.
Hiring: what does the new hire land into.

## QUESTION: 1 sentence, under 15 words

Simple. Direct. Makes them feel seen. Ends with "?". No sub-clauses.

Good:
- "can your team realistically deliver both without something breaking?"
- "how much of that is capture and cleanup versus actual tuning?"
- "how much of your seniors' time is going to cleanup before they touch the stuff that actually matters?"

Bad:
- "if you could redesign the motion scope knowing what you know now, where would you cut first to protect your schedule?"

## CHARACTER: name only

Just the character's name. "Coen". "Ellie". "Miles Morales". "[CHARACTER]" if unknown.
Never: "Tommy Angelo and the crime families of 1920s Don City" — that's 12 words, not a name.
If no named character is known: "a soulslike warrior" (3 words max).

## SUBJECT: MAX 5 WORDS. lowercase. NO colons. NO "reimagined", NO subtitles.

Sounds like an internal Slack thread title or an email a producer forwarded.
Describes the situation or problem — not our product, not emotional framing.
Use the hook game name EXACTLY as given in the prompt (already shortened). Never append "reimagined" or subtitles.

Gold standard examples (count the words):
- "mortal shell 2 animation scope" — 5 words ✓
- "dawnwalker september reshoot math" — 4 words ✓
- "lotf2 co-op scope is committed" — 5 words ✓
- "co-op motion matching pipeline" — 4 words ✓
- "two heroes need to feel different" — 6 words (absolute max, only if perfect)

Bad:
- "dq7 reimagined shipped scope locked at capture" — 7 words, has "reimagined" ✗
- "old country shipped scope and what's next" — 7 words ✗
- any subject with a colon ✗
- anything over 6 words ✗

If the hook game title uses non-Latin characters, skip it — use genre + situation: "soulslike locomotion scope" or "shipped what gets cut next"

## Output format
Return valid JSON only. No markdown fences. No extra keys.
{
  "animation_director": {"subject": "...", "hook": "...", "question": "...", "character": "..."},
  "cto": {"subject": "...", "hook": "...", "question": "...", "character": "..."},
  "founder": {"subject": "...", "hook": "...", "question": "...", "character": "..."}
}
"""

TEMPLATE_FOUNDER = (
    '{{FIRST_NAME}} - {hook}\n\n'
    '{question}\n\n'
    'Motorica generates the motion matching datasets in days instead of months. '
    'your animators direct the feel, the tool handles the manufacturing, scope stays on track. '
    'Platinum Games runs this workflow now.\n\n'
    'want to walk through a live demo? we can show you output on a character like {character}.\n\n'
    '{{SENDER_FIRST_NAME}}'
)

TEMPLATE_CTO = (
    '{{FIRST_NAME}} - {hook}\n\n'
    '{question}\n\n'
    'Motorica generates the motion matching datasets in days. '
    'FBX output, straight into your pipeline, data stays private. '
    'you scope the parameters, run generation on your timeline. '
    'Platinum Games went from months of dataset prep to days.\n\n'
    'want to see how the output integrates with your pipeline?\n\n'
    '{{SENDER_FIRST_NAME}}'
)

TEMPLATE_ANIMATION_DIRECTOR = (
    '{{FIRST_NAME}} - {hook}\n\n'
    '{question}\n\n'
    'we built a system that generates the full motion matching dataset from your style parameters, '
    'so your team is directing how movement feels instead of manufacturing clips. '
    'days, not months. Maxi Keller from TLOU2 said the output is '
    '"better, more consistent results than mocap."\n\n'
    'want to walk through a live demo? we can show you output on a character like {character}.\n\n'
    '{{SENDER_FIRST_NAME}}'
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
    "Mortal Shell 2": "Mortal Shell 2",
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


def normalize_titles(text: str) -> str:
    for formal, short in sorted(GAME_SHORTS.items(), key=lambda x: -len(x[0])):
        text = re.sub(re.escape(formal), short, text, flags=re.IGNORECASE)
    return text


def clean_subject(text: str) -> str:
    text = normalize_titles(text)
    # strip non-ASCII words (Chinese/Japanese/Korean/Arabic game titles)
    text = re.sub(r'[^\x00-\x7F]+\s*', '', text).strip()
    return text


MOMENT_LABELS = {
    "post_launch": "game already shipped — regret/next project angle",
    "active_preproduction": "in active preproduction — reshoot risk is live",
    "fresh_announced": "just announced — scope angle, architecture locks soon",
    "hiring_mocap": "hiring for mocap — what does the hire land into",
    "no_signal": "no clear signal — craft/pipeline question tied to their known game",
    "back_catalog": "back catalog — what would they do differently",
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
        f"Write HOOK, QUESTION, CHARACTER, SUBJECT for all 3 personas.\n"
        f"HOOK: 2 sentences, uses Hook game name as given. No em dashes. Lowercase except proper nouns and game titles.\n"
        f"QUESTION: 1 sentence ending with '?'. No em dashes."
    )


def assemble_body(template: str, hook: str, question: str, character: str) -> str:
    body = template.format(
        hook=hook.strip(),
        question=question.strip(),
        character=character.strip(),
    )
    body = normalize_titles(body)
    return re.sub(r'\s*—\s*', ', ', body)


def generate_copy(client, row: dict, use_openrouter: bool = False) -> dict | None:
    try:
        if use_openrouter:
            resp = client.chat.completions.create(
                model=MODEL_OPENROUTER,
                max_tokens=700,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(row)},
                ],
            )
            raw = resp.choices[0].message.content.strip()
        else:
            msg = client.messages.create(
                model=MODEL_ANTHROPIC,
                max_tokens=700,
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
                "subject": clean_subject(p.get("subject", "")),
                "body": assemble_body(
                    template,
                    p.get("hook", ""),
                    p.get("question", ""),
                    p.get("character", ""),
                ),
            }
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

    out_path = ROOT / "temp" / f"motorica_copy_e1_batch_{args.batch:02d}.json"

    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        done = {r["dev_name"] for r in existing if r.get("copy")}
        my_rows = [r for r in my_rows if r["dev_name"] not in done]
        # remove empty-copy placeholders so we can replace them
        existing = [r for r in existing if r.get("copy")]
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
    print(f"Batch {args.batch}: wrote {len(results)} results -> {out_path.name}")


if __name__ == "__main__":
    main()
