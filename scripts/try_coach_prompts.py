#!/usr/bin/env python3
"""Try the coach's prompts on several local models and write an org report.

Run this on the computer that serves the models, after pulling them, for
example with Ollama::

    ollama pull llama3.2
    ollama pull qwen2.5:7b
    ollama pull gemma2:9b
    python scripts/try_coach_prompts.py llama3.2 qwen2.5:7b gemma2:9b \\
        --out coach-trial.org

Each model gets the same sample facts for every task, so the report compares
the models side by side. Each reply is checked the way the package checks it:
whether a structured reply parses, whether the objectives stay at three or
fewer, whether a pattern sentence carries a number the facts do not hold, and
whether the plan-size note keeps the computed number. The timing of each call
is recorded too. Only the sample facts below are sent, never your records.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from writing_habit import coach, debrief  # noqa: E402

SAMPLES = {
    "objectives": coach.objective_facts(
        "work on the R01 resubmission", "1002RNAediting", 120,
        deadline="2027-02-05",
        waiting=["find three citations for the rigor section"],
        last_step="start with the second aim's rationale"),
    "grasscatcher": coach.grasscatcher_facts(
        [("B", "tidy the methods section"), ("A", "find three citations"),
         (None, "clean up the bib file")],
        {"A": "2026-11-01", "B": "2026-12-01"}, {"A": 240, "B": 120}),
    "debrief": debrief.prompt(debrief.BlockFacts(
        project="1006AIrxOpt", minutes=120,
        objectives=[("Draft the second aim paragraph", True),
                    ("Find three citations", False)],
        focus=4, interruptions=2, note="the phone rang twice")),
    "weeks": coach.weeks_facts(
        [{"kind": "weekday", "group": "Wednesday", "adherence": 0.25, "weeks": 6},
         {"kind": "schedule shape", "group": "gAeB", "adherence": 0.92, "weeks": 9}],
        0.61),
    "size": ("Suggested minutes for next week: 285\n"
             "Based on: your last 8 planned weeks\n"
             "Typical minutes planned in those weeks: 480\n"
             "Share of planned minutes kept in those weeks: 59%\n"
             "Minutes in next week's plan as it stands: 540"),
}


def check(task: str, reply) -> str:
    """Return a short verdict on one reply."""
    if task == "objectives":
        if not isinstance(reply, dict):
            return "not structured"
        items = reply.get("objectives") or []
        return f"{len(items)} objectives" + ("" if 1 <= len(items) <= 3 else ", out of range")
    if task == "grasscatcher":
        order = [i.get("index") for i in (reply or {}).get("order", [])]
        if sorted(order) == [0, 1, 2]:
            return "every task once"
        if not order:
            return "empty order, the app would use deadline order"
        return f"order {order}, the app fills in missing tasks"
    if task == "weeks":
        allowed = {int(n) for n in re.findall(r"\d+", SAMPLES["weeks"])} | {8}
        text = " ".join((reply or {}).get("patterns", []) + [(reply or {}).get("change", "")])
        extra = {int(n) for n in re.findall(r"\d+", text)} - allowed
        return "numbers match the facts" if not extra else f"invented numbers {sorted(extra)}"
    if task == "size":
        return "keeps 285" if "285" in reply or "4 h 45" in reply else "dropped the number"
    words = len(str(reply).split())
    return f"{words} words"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("models", nargs="+")
    parser.add_argument("--url", default="http://localhost:11434")
    parser.add_argument("--api", default="ollama", choices=coach.APIS)
    parser.add_argument("--out", default="coach-trial.org")
    args = parser.parse_args(argv)

    prompts = coach.load_prompts()
    lines = ["#+TITLE: Coach prompts tried on local models",
             "#+LaTeX_HEADER: \\usepackage[margin=0.5in]{geometry}", "",
             "#+CAPTION: Verdicts and seconds per reply.",
             "#+ATTR_LATEX: :booktabs t",
             "| Model | Task | Verdict | Seconds |", "|-"]
    details = []
    for model in args.models:
        client = coach.Client(model=model, url=args.url, api=args.api, timeout=180)
        for task, facts in SAMPLES.items():
            start = time.time()
            schema = coach.grasscatcher_schema(3) if task == "grasscatcher" else None
            try:
                reply = client.ask(task, facts, prompts, schema)
                verdict = check(task, reply)
            except coach.CoachError as exc:
                reply, verdict = None, f"error, {exc}"
            seconds = time.time() - start
            lines.append(f"| {model} | {task} | {verdict} | {seconds:.1f} |")
            shown = json.dumps(reply, indent=2) if isinstance(reply, (dict, list)) else str(reply)
            details += [f"** {model}, {task}", "#+begin_example", shown, "#+end_example", ""]
            print(f"{model:20s} {task:13s} {verdict} ({seconds:.1f} s)")
    lines += ["", "* Replies", ""] + details
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
