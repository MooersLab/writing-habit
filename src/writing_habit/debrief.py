"""The post-block debrief: a short coaching note after a writing block.

This is the first of the AI features the Ten Simple Rules outline proposes,
and it follows that outline's limits. The model coaches and never writes the
manuscript. It speaks after the block, never during it. It leads with what went
well, names one pattern at most, and ends with one small suggestion for the
next block. A missed objective is treated as information, not as a failure.

Privacy comes first. The debrief asks a model served on the writer's own
computer, through the Ollama HTTP interface at ``http://localhost:11434`` by
default, and sends only the block's review: the project name, the objectives
and whether each was met, the focus rating, the interruption count, and the
notes. Nothing is sent unless the writer turns the model on. A URL that does not
point at this computer is refused unless the caller passes ``allow_remote``.

When the model is off or cannot be reached, :func:`local_debrief` writes a plain
summary from the same facts with no model at all, so the button always gives an
answer.

The module needs only the standard library.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

#: The addresses that count as this computer.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}

#: Seconds to wait for the model. A small local model answers in a few.
TIMEOUT = 60

SYSTEM = (
    "You are a supportive writing coach for an academic scientist. You help "
    "the writer reflect on one writing block that just ended. You never write "
    "or rewrite the manuscript itself. Reply in three or four plain sentences "
    "with no headings, no lists, no colons joining clauses, and no dashes. "
    "First, name what went well, using the writer's own objectives. Second, if "
    "something got in the way, name it once, kindly, as information rather "
    "than failure. Third, suggest one small concrete first step for the next "
    "block on this project. Do not mention scores or ratings by number."
)


@dataclass
class BlockFacts:
    """What the debrief may see about one block.  Nothing else is sent."""

    project: str
    minutes: int
    objectives: List[Tuple[str, bool]] = field(default_factory=list)
    committed: Optional[int] = None
    met: Optional[int] = None
    focus: Optional[int] = None
    interruptions: Optional[int] = None
    output_units: Optional[str] = None
    next_step: Optional[str] = None
    note: Optional[str] = None

    def counts(self) -> Tuple[Optional[int], Optional[int]]:
        if self.objectives:
            return len(self.objectives), sum(1 for _t, done in self.objectives if done)
        return self.committed, self.met


def prompt(facts: BlockFacts) -> str:
    """Return the user message the model receives."""
    lines = [f"Project: {facts.project}", f"Planned length: {facts.minutes} minutes"]
    if facts.objectives:
        lines.append("Objectives:")
        lines += [f"  [{'met' if done else 'not met'}] {text}"
                  for text, done in facts.objectives]
    else:
        committed, met = facts.counts()
        if committed is not None:
            lines.append(f"Objectives met: {met or 0} of {committed}")
    if facts.focus is not None:
        lines.append(f"Self-rated focus: {facts.focus} of 5")
    if facts.interruptions is not None:
        lines.append(f"Interruptions counted: {facts.interruptions}")
    for label, value in (("Output", facts.output_units),
                         ("Writer's next step", facts.next_step),
                         ("Writer's note", facts.note)):
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def local_debrief(facts: BlockFacts) -> str:
    """Return a plain summary of the block written without any model."""
    committed, met = facts.counts()
    parts: List[str] = []
    done = [text for text, ok in facts.objectives if ok]
    if done:
        parts.append("You finished " + _join(done) + ".")
    elif committed and met:
        parts.append(f"You met {met} of the {committed} objectives you set.")
    else:
        parts.append(f"You showed up for {facts.minutes} minutes on "
                     f"{facts.project}, which is the habit itself.")
    if facts.focus is not None and facts.focus >= 4:
        parts.append("Your focus held well.")
    if facts.interruptions:
        parts.append(
            f"{facts.interruptions} interruption"
            f"{'' if facts.interruptions == 1 else 's'} broke in. Next time, "
            "write each urge on the grasscatcher list and carry on.")
    elif facts.focus is not None and facts.focus <= 2:
        parts.append("Focus was hard to hold this time. A smaller first "
                     "objective can make the start easier.")
    left = [text for text, ok in facts.objectives if not ok]
    if facts.next_step:
        parts.append("Start the next block where your own note points, "
                     f"{facts.next_step.rstrip('.')}.")
    elif left:
        parts.append(f"A good first step next time is {left[0]}.")
    else:
        parts.append("Before you close the file, write one sentence on where "
                     "to start next time.")
    return " ".join(parts)


def _join(items: List[str]) -> str:
    items = [i.rstrip(".") for i in items]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def is_local(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return host in LOCAL_HOSTS or host.startswith("127.")


def ask_model(facts: BlockFacts, model: str, url: str = "http://localhost:11434",
              timeout: float = TIMEOUT, allow_remote: bool = False,
              opener=urllib.request.urlopen) -> str:
    """Ask the local model for a debrief.  Raise :class:`RuntimeError` on failure.

    ``opener`` is the function that sends the request; a test replaces it.
    """
    if not model:
        raise RuntimeError("no model is named for the debrief")
    if not allow_remote and not is_local(url):
        raise RuntimeError(f"{url} is not on this computer, so the review stays here")
    body = json.dumps({
        "model": model,
        "system": SYSTEM,
        "prompt": prompt(facts),
        "stream": False,
        "options": {"temperature": 0.4},
    }).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/api/generate", data=body,
        headers={"Content-Type": "application/json"})
    try:
        with opener(request, timeout=timeout) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(f"the local model at {url} did not answer ({exc})") from exc
    text = (reply.get("response") or "").strip()
    if not text:
        raise RuntimeError("the local model sent an empty reply")
    return text


def debrief(facts: BlockFacts, use_model: bool, model: str = "",
            url: str = "http://localhost:11434", **kwargs) -> Tuple[str, str]:
    """Return ``(text, source)``, where source says who wrote the text.

    With ``use_model`` the local model is asked first. When it is off, or does
    not answer, the plain summary is returned and the source says why.
    """
    if use_model:
        try:
            return ask_model(facts, model, url, **kwargs), f"local model {model}"
        except RuntimeError as exc:
            return local_debrief(facts), f"summary without a model, because {exc}"
    return local_debrief(facts), "summary without a model"
