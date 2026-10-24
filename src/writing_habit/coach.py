"""The writing coach: a local language model in a supporting role.

The Ten Simple Rules paper puts AI in several rules. Rule 2 matches blocks to
the writer's energy through the day, and Rule 3 checks that projects due soon
have time in the week's plan. Rule 4 drafts a block's
objectives and ranks the grasscatcher list. Rule 5 writes the debrief after a
block (see :mod:`writing_habit.debrief`). Rule 7 reads patterns across weeks
and sizes next week's plan. Rule 8 drafts the Friday summary the writer sends
to an accountability partner. Rule 10 sets the guardrails, and this module
enforces them in code rather than leaving them to the writer's discipline.

Three layers keep the model in its place.

Facts
    The functions named ``*_facts`` and the pattern and size calculations
    take a small, fixed set of fields from the habit database or the weekly
    table. Every number is computed here, by the software, so the model only
    puts numbers into words and cannot report a trend that is not there.

Coach
    :class:`Client` sends one request to a model served on this computer,
    through the Ollama interface or the OpenAI-style interface that LM Studio,
    llama.cpp, and Ollama all offer. The prompts live in ``coach_prompts.json``,
    which the Emacs Lisp twin reads too. Structured tasks ask for JSON that
    matches a schema, and the reply is checked before it is used.

Guardrails (Rule 10)
    No manuscript text is ever sent, because no fact builder reads one. Only an
    address on this computer is allowed unless ``allow_remote`` is set. The
    coach refuses during a planned block unless the writer insists, and refuses
    in a week the writer has marked as an AI-off week. Every call is written to
    the ``ai_log`` table with the facts sent and the reply, so the writer can
    see exactly what left the database. Every task has a plain answer written
    without a model, so the coach is never required.

The module needs only the standard library.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import statistics
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

PROMPTS_PATH = Path(__file__).with_name("coach_prompts.json")

#: The addresses that count as this computer.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}

#: The two interfaces a local model server may offer.
APIS = ("ollama", "openai")

#: Seconds to wait for a reply. A small local model answers in a few.
TIMEOUT = 60

#: A group needs this many weeks before its adherence counts as a pattern.
MIN_WEEKS = 4

#: The number of past planned weeks the plan size is drawn from.
SIZE_WINDOW = 8

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


class CoachError(RuntimeError):
    """The coach could not, or would not, answer."""


def load_prompts(path: Optional[Path] = None) -> dict:
    """Return the shared prompts."""
    return json.loads((path or PROMPTS_PATH).read_text(encoding="utf-8"))


def is_local(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return host in LOCAL_HOSTS or host.startswith("127.")


# -- the client ------------------------------------------------------------------
@dataclass
class Client:
    """One local model behind an HTTP interface."""

    model: str
    url: str = "http://localhost:11434"
    api: str = "ollama"
    allow_remote: bool = False
    timeout: float = TIMEOUT
    opener: object = field(default=urllib.request.urlopen, repr=False)

    @property
    def label(self) -> str:
        return f"local model {self.model}"

    def _check(self) -> None:
        if not self.model:
            raise CoachError("no model is named for the coach")
        if self.api not in APIS:
            raise CoachError(f"unknown interface {self.api!r}; use ollama or openai")
        if not self.allow_remote and not is_local(self.url):
            raise CoachError(f"{self.url} is not on this computer, so the "
                             "records stay here")

    def request(self, system: str, user: str, schema=None) -> urllib.request.Request:
        """Build the HTTP request for one exchange."""
        self._check()
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        base = self.url.rstrip("/")
        if self.api == "ollama":
            body = {"model": self.model, "messages": messages, "stream": False,
                    "options": {"temperature": 0.3}}
            if schema is not None:
                body["format"] = schema
            endpoint = base + "/api/chat"
        else:
            body = {"model": self.model, "messages": messages, "temperature": 0.3}
            if schema is not None:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "reply", "schema": schema}}
            endpoint = base + "/v1/chat/completions"
        return urllib.request.Request(
            endpoint, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"})

    def chat(self, system: str, user: str, schema=None) -> str:
        """Send one exchange and return the reply text."""
        request = self.request(system, user, schema)
        try:
            with self.opener(request, timeout=self.timeout) as response:
                reply = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise CoachError(self._http_problem(exc)) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise CoachError(f"the local model at {self.url} did not answer "
                             f"({exc})") from exc
        if self.api == "ollama":
            text = (reply.get("message") or {}).get("content") or reply.get("response")
        else:
            choices = reply.get("choices") or [{}]
            text = (choices[0].get("message") or {}).get("content")
        text = (text or "").strip()
        if not text:
            raise CoachError("the local model sent an empty reply")
        return text

    def _http_problem(self, exc) -> str:
        """Explain an HTTP error, naming the fix for a model that is not pulled."""
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8"))
            detail = body.get("error") or ""
            if isinstance(detail, dict):
                detail = detail.get("message") or ""
        except Exception:                                # noqa: BLE001
            pass
        if exc.code == 404:
            hint = (f"run ollama pull {self.model}" if self.api == "ollama"
                    else f"load {self.model} in the server")
            return (f"the server at {self.url} has no model named {self.model}"
                    f"{' (' + detail + ')' if detail else ''}; {hint}")
        return (f"the local model at {self.url} refused the request "
                f"(HTTP {exc.code}{', ' + detail if detail else ''})")

    def ask(self, task: str, facts: str, prompts: Optional[dict] = None,
            schema: Optional[dict] = None):
        """Ask for one task.  Return the text, or the parsed JSON for a schema task.

        ``schema`` replaces the task's schema for this call, so a task can pin
        the reply to the size of its facts.
        """
        prompts = prompts or load_prompts()
        spec = prompts["tasks"][task]
        system = prompts["rules"] + " " + spec["system"]
        user = spec["instruction"] + "\n\n" + facts
        schema = schema if schema is not None else spec.get("schema")
        text = self.chat(system, user, schema)
        if schema is None:
            return text
        try:
            return json.loads(text)
        except ValueError as exc:
            raise CoachError("the local model did not reply in the expected "
                             "form") from exc


def list_models(url: str = "http://localhost:11434", api: str = "ollama",
                allow_remote: bool = False, timeout: float = 10,
                opener=urllib.request.urlopen) -> List[str]:
    """Return the names of the models the server has installed, sorted.

    Ollama lists them at ``/api/tags`` and the OpenAI-style servers at
    ``/v1/models``. Raise :class:`CoachError` when the server cannot be asked.
    """
    if api not in APIS:
        raise CoachError(f"unknown interface {api!r}; use ollama or openai")
    if not allow_remote and not is_local(url):
        raise CoachError(f"{url} is not on this computer")
    path = "/api/tags" if api == "ollama" else "/v1/models"
    request = urllib.request.Request(url.rstrip("/") + path)
    try:
        with opener(request, timeout=timeout) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CoachError(f"no model server answered at {url} ({exc})") from exc
    if api == "ollama":
        names = [m.get("name") or m.get("model") for m in reply.get("models") or []]
    else:
        names = [m.get("id") for m in reply.get("data") or []]
    return sorted({n for n in names if n})


@dataclass
class Answer:
    """What a coach task returns: the data, a readable text, and who wrote it."""

    data: object
    text: str
    source: str
    facts: str = ""
    log_id: Optional[int] = None


# -- guardrails ------------------------------------------------------------------
def monday_of(day: _dt.date) -> _dt.date:
    return day - _dt.timedelta(days=day.weekday())


def block_now(blocks: Iterable, monday: Optional[_dt.date],
              now: _dt.datetime):
    """Return the planned block the clock is inside, or ``None``.

    ``blocks`` are :class:`~writing_habit.gui.weekly_table.Block` objects of the
    week that starts on ``monday``.
    """
    if monday is None:
        return None
    offset = (now.date() - monday).days
    minute = now.hour * 60 + now.minute
    for block in blocks:
        if block.offset != offset:
            continue
        first = int(block.start[:2]) * 60 + int(block.start[3:5])
        last = int(block.end[:2]) * 60 + int(block.end[3:5])
        if last <= first:
            last += 24 * 60
        if first <= minute < last:
            return block
    return None


def check_allowed(today: _dt.date, off_week: str = "", in_block=None,
                  insist: bool = False) -> None:
    """Raise :class:`CoachError` when Rule 10 says the coach should stay quiet."""
    if off_week and off_week == monday_of(today).isoformat():
        raise CoachError("this is an AI-off week, so the coach stays quiet "
                         "and the habit runs on its own")
    if in_block is not None and not insist:
        raise CoachError(
            f"you are inside the {in_block.letter} {in_block.start}-{in_block.end} "
            "block, and the coach stays silent during deep work")


# -- the log -------------------------------------------------------------------------
def log_call(con, task: str, source: str, facts: str, reply: str,
             week_start: Optional[str] = None) -> int:
    cur = con.execute(
        "INSERT INTO ai_log(task, source, facts, reply, week_start)"
        " VALUES (?, ?, ?, ?, ?)", (task, source, facts, reply, week_start))
    con.commit()
    return int(cur.lastrowid)


def mark_accepted(con, log_id: Optional[int], accepted: bool) -> None:
    if log_id is None:
        return
    con.execute("UPDATE ai_log SET accepted = ? WHERE log_id = ?",
                (int(bool(accepted)), log_id))
    con.commit()


def _run(task: str, client: Optional[Client], facts: str, fallback, parse,
         con=None, week_start: Optional[str] = None,
         prompts: Optional[dict] = None, schema: Optional[dict] = None) -> Answer:
    """Ask the model when there is one, fall back to ``fallback`` otherwise."""
    source = "plain summary written without a model"
    data = None
    if client is not None:
        try:
            data = parse(client.ask(task, facts, prompts, schema))
            source = client.label
        except CoachError as exc:
            source = f"plain summary written without a model, because {exc}"
            data = None
    if data is None:
        data = fallback()
    answer = Answer(data=data, text=_as_text(task, data), source=source, facts=facts)
    if con is not None:
        answer.log_id = log_call(con, task, source, facts, answer.text, week_start)
    return answer


def _as_text(task: str, data) -> str:
    if isinstance(data, str):
        return data
    if task == "objectives":
        lines = [f"- {o}" for o in data.get("objectives", [])]
        if data.get("if_then"):
            lines.append(data["if_then"])
        return "\n".join(lines)
    if task == "grasscatcher":
        return "\n".join(f"{i + 1}. {item['text']} ({item['reason']})"
                         for i, item in enumerate(data))
    if task == "capture":
        return data.entry_text()
    if task == "weeks":
        return "\n".join(data.get("patterns", []) + [data.get("change", "")]).strip()
    return json.dumps(data)


def _clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


# -- Rule 4: objectives ------------------------------------------------------------
def objective_facts(task: str, project: str, minutes: int,
                    deadline: Optional[str] = None,
                    waiting: Sequence[str] = (),
                    last_step: Optional[str] = None,
                    stuck: Optional[str] = None) -> str:
    """Return the facts the objectives task may see.  Nothing else is sent.

    ``stuck`` is the sentence of :mod:`writing_habit.stuck` when the project
    keeps missing its objectives, so the model breaks the task down further.
    """
    lines = [f"Task: {_clean(task)}", f"Project: {_clean(project)}",
             f"Block length: {minutes} minutes"]
    if stuck:
        lines.append(f"Stuck: {_clean(stuck)} Break the task into smaller steps.")
    if deadline:
        lines.append(f"Project deadline: {deadline}")
    if last_step:
        lines.append(f"Last next-step note: {_clean(last_step)}")
    if waiting:
        lines.append("Waiting tasks for this project:")
        lines += [f"  - {_clean(w)}" for w in waiting]
    return "\n".join(lines)


def _parse_objectives(reply) -> dict:
    if not isinstance(reply, dict):
        raise CoachError("the reply held no objectives")
    items = [_clean(o) for o in reply.get("objectives") or [] if _clean(o)]
    if not items:
        raise CoachError("the reply held no objectives")
    return {"objectives": items[:3], "if_then": _clean(reply.get("if_then"))}


def suggest_objectives(client: Optional[Client], facts: str, con=None,
                       week_start=None, prompts=None) -> Answer:
    """Draft one to three objectives and an if-then plan for a block.

    Without a model there is nothing sensible to draft, so the plain answer
    is the advice to write one visible result per objective.
    """
    def fallback():
        return {"objectives": [],
                "if_then": "Write one to three objectives, each a result you "
                           "could show someone at the end of the block."}
    return _run("objectives", client, facts, fallback, _parse_objectives,
                con, week_start, prompts)


# -- Rule 4: the grasscatcher -------------------------------------------------------
def capture_task(client: Optional[Client], text: str, projects, con=None,
                 week_start: Optional[str] = None, prompts=None) -> Answer:
    """Turn a captured thought into a grasscatcher task (Rule 4).

    ``projects`` are :class:`writing_habit.capture.Project` objects. The plain
    reading is always made first. A model's project and wording replace it only
    where :func:`writing_habit.capture.confirm` can check them against the words.
    """
    from . import capture

    plain = capture.plain(text, projects)
    if client is None:
        answer = Answer(data=plain, text=plain.entry_text(),
                        source="plain summary written without a model")
        return answer

    def parse(reply):
        if not isinstance(reply, dict):
            raise CoachError("the reply held no task")
        return capture.confirm(reply, text, projects, plain)

    answer = _run("capture", client, capture.facts(text, projects), lambda: plain,
                  parse, con, week_start, prompts)
    answer.text = answer.data.entry_text()
    return answer


def grasscatcher_facts(tasks: Sequence[Tuple[Optional[str], str]],
                       deadlines: Dict[str, Optional[str]],
                       planned: Dict[str, int]) -> str:
    """Return the facts for ranking: each task, its project's deadline and minutes."""
    lines = []
    for index, (code, text) in enumerate(tasks):
        parts = [f"{index}. {_clean(text)}"]
        if code:
            parts.append(f"project {code}")
            if deadlines.get(code):
                parts.append(f"deadline {deadlines[code]}")
            parts.append(f"{planned.get(code, 0)} minutes planned this week")
        lines.append(", ".join(parts))
    count = len(tasks)
    return (f"There are {count} tasks, numbered 0 to {count - 1}. Rank all "
            f"{count}, using each number once.\nTasks:\n" + "\n".join(lines))


def grasscatcher_schema(count: int) -> dict:
    """Return the ranking schema pinned to ``count`` tasks.

    A small model given only the general schema may answer with an empty list,
    so the reply is held to exactly ``count`` entries and to known numbers.
    """
    return {
        "type": "object",
        "properties": {
            "order": {
                "type": "array", "minItems": count, "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": {"index": {"type": "integer",
                                             "enum": list(range(count))},
                                   "reason": {"type": "string"}},
                    "required": ["index", "reason"]}}},
        "required": ["order"]}


def plain_rank(tasks, deadlines, planned) -> List[dict]:
    """Order tasks by the nearest deadline, then by minutes planned this week."""
    def key(index):
        code = tasks[index][0]
        deadline = deadlines.get(code) or "9999-99-99"
        return (deadline, -planned.get(code, 0), index)
    out = []
    for index in sorted(range(len(tasks)), key=key):
        code = tasks[index][0]
        if code and deadlines.get(code):
            reason = f"deadline {deadlines[code]}"
        elif code and planned.get(code):
            reason = f"{planned[code]} minutes planned this week"
        else:
            reason = "no deadline or planned time"
        out.append({"index": index, "text": tasks[index][1], "reason": reason})
    return out


def rank_grasscatcher(client: Optional[Client], tasks, deadlines, planned,
                      con=None, week_start=None, prompts=None) -> Answer:
    """Return the tasks in a suggested order, each with a short reason."""
    def parse(reply):
        order = (reply or {}).get("order") if isinstance(reply, dict) else None
        if not order:
            raise CoachError("the reply held no order")
        seen, out = set(), []
        for item in order:
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError, AttributeError):
                continue
            if 0 <= index < len(tasks) and index not in seen:
                seen.add(index)
                out.append({"index": index, "text": tasks[index][1],
                            "reason": _clean(item.get("reason")) or "ranked"})
        for index in range(len(tasks)):           # the model may drop a task
            if index not in seen:
                out.append({"index": index, "text": tasks[index][1],
                            "reason": "left where it was"})
        return out
    facts = grasscatcher_facts(tasks, deadlines, planned)
    return _run("grasscatcher", client, facts,
                lambda: plain_rank(tasks, deadlines, planned), parse,
                con, week_start, prompts, grasscatcher_schema(len(tasks)))


# -- Rule 7: patterns across weeks ---------------------------------------------------
def weekday_rows(con, end_week: Optional[str] = None) -> List[dict]:
    """Return adherence by weekday, over every week up to ``end_week``."""
    clause, params = "", []
    if end_week:
        clause, params = " AND week_start <= ?", [end_week]
    planned = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT (CAST(strftime('%w', day) AS INTEGER) + 6) % 7, SUM(planned_min),"
        " COUNT(DISTINCT week_start) FROM plan_block WHERE 1" + clause +
        " GROUP BY 1", params)}
    actual = {r[0]: r[1] for r in con.execute(
        "SELECT (CAST(strftime('%w', day) AS INTEGER) + 6) % 7, SUM(actual_min)"
        " FROM session WHERE 1" + clause + " GROUP BY 1", params)}
    rows = []
    for day, (minutes, weeks) in sorted(planned.items()):
        if minutes:
            rows.append({"kind": "weekday", "group": DAY_NAMES[day],
                         "adherence": round(min(actual.get(day, 0) / minutes, 9.99), 2),
                         "weeks": weeks})
    return rows


def group_rows(con, end_week: Optional[str] = None) -> List[dict]:
    """Return every grouping the dashboards show, as one list."""
    rows = weekday_rows(con, end_week)
    queries = [
        ("month", "SELECT month, adherence, weeks FROM v_month_overall"),
        ("event", "SELECT tag, adherence, weeks FROM v_context_overall"),
        ("schedule shape", "SELECT schedule_code, adherence, weeks FROM v_schedule_overall"),
    ]
    for kind, sql in queries:
        try:
            for r in con.execute(sql):
                if r[1] is not None:
                    rows.append({"kind": kind, "group": r[0],
                                 "adherence": r[1], "weeks": r[2]})
        except Exception:                                # pragma: no cover
            continue
    return rows


def overall_adherence(con, end_week: Optional[str] = None) -> Optional[float]:
    clause, params = "", []
    if end_week:
        clause, params = " WHERE week_start <= ?", [end_week]
    row = con.execute("SELECT SUM(planned_min), SUM(actual_min) FROM v_week_overall"
                      + clause, params).fetchone()
    if not row or not row[0]:
        return None
    return round(row[1] / row[0], 2)


def strongest_patterns(rows, overall: float, min_weeks: int = MIN_WEEKS,
                       top: int = 2) -> List[dict]:
    """Return the groups whose adherence differs most from the overall mean.

    A group with fewer than ``min_weeks`` weeks behind it is not a pattern yet.
    """
    usable = [r for r in rows if r["weeks"] >= min_weeks and r["adherence"] is not None]
    return sorted(usable, key=lambda r: (-abs(r["adherence"] - overall),
                                         r["kind"], str(r["group"])))[:top]


def _pct(value: float) -> int:
    return int(round(value * 100))


def group_label(row: dict) -> str:
    """Name a group the way a writer would say it."""
    kind, group = row["kind"], row["group"]
    if kind == "weekday":
        return f"your {group} blocks"
    if kind == "month":
        return f"your weeks in {group}"
    if kind == "event":
        return f"your weeks tagged {group}"
    return f"your weeks planned with the {group} schedule"


def pattern_sentence(row: dict, overall: float) -> str:
    """Write one pattern plainly, from its numbers."""
    side = "more" if row["adherence"] >= overall else "less"
    weeks = row["weeks"]
    label = group_label(row)
    text = (f"{label[0].upper() + label[1:]} kept {_pct(row['adherence'])}% of their "
            f"planned minutes over {weeks} weeks, {side} than your overall "
            f"{_pct(overall)}%.")
    if weeks < 8:
        text += f" {weeks} weeks of one writer is a small sample."
    return text


def plain_change(patterns: List[dict], overall: float) -> str:
    low = [p for p in patterns if p["adherence"] < overall]
    high = [p for p in patterns if p["adherence"] >= overall]
    if low:
        return (f"Plan fewer minutes for {group_label(low[0])} next week, and move "
                "the rest to times you keep more often.")
    if high:
        return (f"Build more of next week's template like {group_label(high[0])}, "
                "because those are the blocks you keep.")
    return "Keep the template as it is for a few more weeks and look again."


def weeks_facts(patterns: List[dict], overall: float) -> str:
    lines = [f"Overall share of planned minutes kept: {_pct(overall)}%"]
    for p in patterns:
        lines.append(f"Pattern: {p['kind']} {p['group']}, kept {_pct(p['adherence'])}%"
                     f" of planned minutes over {p['weeks']} weeks")
    return "\n".join(lines)


def _numbers(text: str) -> set:
    return {int(n) for n in re.findall(r"\d+", text)}


def read_weeks(client: Optional[Client], con, end_week: Optional[str] = None,
               log: bool = True, prompts=None) -> Answer:
    """Describe the two strongest patterns and propose one template change.

    The patterns are found here. The model only words them, and a sentence that
    carries a number the facts do not hold is replaced by the plain sentence.
    """
    overall = overall_adherence(con, end_week)
    if overall is None:
        return Answer(data={"patterns": [], "change": "", "rows": []},
                      text="There are no planned weeks to read yet.",
                      source="no data")
    patterns = strongest_patterns(group_rows(con, end_week), overall)
    if not patterns:
        text = (f"No group has {MIN_WEEKS} weeks behind it yet, so there is no "
                "pattern to report. Keep planning and tracking, and look again.")
        return Answer(data={"patterns": [], "change": "", "rows": []}, text=text,
                      source="no pattern yet")
    facts = weeks_facts(patterns, overall)
    allowed = _numbers(facts) | {8}

    def plain():
        return {"patterns": [pattern_sentence(p, overall) for p in patterns],
                "change": plain_change(patterns, overall)}

    def parse(reply):
        if not isinstance(reply, dict):
            raise CoachError("the reply held no patterns")
        sentences = [_clean(s) for s in reply.get("patterns") or []]
        out, used = [], set()
        for pattern in patterns:
            # A sentence must state this pattern's percentage and add no number
            # of its own; a bare label such as "Wednesday" says nothing.
            match = next((i for i, text in enumerate(sentences)
                          if i not in used and str(_pct(pattern["adherence"])) in text
                          and _numbers(text) <= allowed), None)
            if match is None:
                out.append(pattern_sentence(pattern, overall))
            else:
                used.add(match)
                out.append(sentences[match])
        change = _clean(reply.get("change"))
        if not change or not _numbers(change) <= allowed:
            change = plain_change(patterns, overall)
        return {"patterns": out, "change": change}

    answer = _run("weeks", client, facts, plain, parse,
                  con if log else None, end_week, prompts)
    answer.data["rows"] = patterns
    answer.data["overall"] = overall
    return answer


# -- Rule 7: sizing next week -------------------------------------------------------
def size_next_week(con, week_start: str, schedule_code: Optional[str] = None,
                   tags: Sequence[str] = ()) -> Optional[dict]:
    """Suggest how many minutes to plan for the week starting ``week_start``.

    The suggestion is the median of the minutes actually written in up to
    eight recent planned weeks before it, rounded to 15 minutes. When at least
    three earlier weeks share the schedule code, or at least two share an event
    tag of the coming week, those weeks are used instead, because they are the
    best guide to a week of that kind.
    """
    weeks = [dict(r) for r in con.execute(
        "SELECT o.week_start, o.planned_min, o.actual_min, w.schedule_code"
        " FROM v_week_overall o LEFT JOIN plan_week w USING(week_start)"
        " WHERE o.week_start < ? AND o.planned_min > 0"
        " ORDER BY o.week_start DESC", (week_start,))]
    if not weeks:
        return None
    basis = f"your last {min(len(weeks), SIZE_WINDOW)} planned weeks"
    chosen = weeks[:SIZE_WINDOW]
    tagged = []
    for tag in tags:
        tagged_weeks = {r[0] for r in con.execute(
            "SELECT week_start FROM week_context WHERE tag = ?", (tag,))}
        tagged = [w for w in weeks if w["week_start"] in tagged_weeks]
        if len(tagged) >= 2:
            chosen, basis = tagged[:SIZE_WINDOW], f"your {len(tagged[:SIZE_WINDOW])} earlier {tag} weeks"
            break
    else:
        if schedule_code:
            same = [w for w in weeks if w["schedule_code"] == schedule_code]
            if len(same) >= 3:
                chosen = same[:SIZE_WINDOW]
                basis = f"your {len(chosen)} earlier weeks with the {schedule_code} plan"
    actual = [w["actual_min"] for w in chosen]
    planned = [w["planned_min"] for w in chosen]
    suggestion = int(round(statistics.median(actual) / 15.0)) * 15
    current = con.execute("SELECT planned_min FROM v_week_overall WHERE week_start = ?",
                          (week_start,)).fetchone()
    return {"minutes": suggestion, "basis": basis, "weeks": len(chosen),
            "median_planned": int(statistics.median(planned)),
            "kept": round(sum(actual) / sum(planned), 2) if sum(planned) else None,
            "current": current[0] if current else None}


def _hours(minutes: int) -> str:
    hours, rest = divmod(int(minutes), 60)
    return f"{hours} h {rest:02d} min" if hours else f"{rest} min"


def plain_size(size: dict) -> str:
    text = (f"Plan about {_hours(size['minutes'])} of writing next week. That is "
            f"what you actually wrote in a typical week of {size['basis']}, where "
            f"you planned {_hours(size['median_planned'])}.")
    if size.get("current") is not None and size["current"] > size["minutes"]:
        text += (f" The week as planned holds {_hours(size['current'])}, so trimming "
                 "it toward the suggestion makes the plan easier to keep.")
    return text


def explain_size(client: Optional[Client], size: dict, con=None, week_start=None,
                 prompts=None) -> Answer:
    """Explain the suggested plan size.  The number itself never changes."""
    facts = (f"Suggested minutes for next week: {size['minutes']}\n"
             f"Based on: {size['basis']}\n"
             f"Typical minutes planned in those weeks: {size['median_planned']}\n"
             f"Share of planned minutes kept in those weeks: "
             f"{_pct(size['kept']) if size.get('kept') is not None else 'unknown'}%")
    if size.get("current") is not None:
        facts += f"\nMinutes in next week's plan as it stands: {size['current']}"

    def parse(reply):
        text = _clean(reply)
        if str(size["minutes"]) not in text and _hours(size["minutes"]) not in text:
            text = plain_size(size) + " " + text
        return text
    answer = _run("size", client, facts, lambda: plain_size(size), parse,
                  con, week_start, prompts)
    answer.data = {"text": answer.data, **size}
    return answer


# -- Rule 8: the Friday summary for a partner -----------------------------------
#: At most this many finished objectives are named in the summary. A partner
#: needs the gist of the week, not the full log.
PARTNER_DONE = 3
#: At most this many personal bests are named, so the message stays short.
PARTNER_BESTS = 2


def partner_week(con, week_start: str, today: Optional[str] = None) -> Optional[dict]:
    """Collect the numbers of the week starting ``week_start`` for a partner.

    Return ``None`` when the week has no plan in the database. Everything is
    computed here from the habit database, so the model only puts it into
    words. The record is a summary: totals, block counts, objectives met
    against those committed, a few finished objectives in the writer's words,
    any personal best the week set, and next week's planned minutes.
    """
    from . import review

    row = con.execute("SELECT planned_min, actual_min FROM v_week_overall"
                      " WHERE week_start = ?", (week_start,)).fetchone()
    if row is None or not row[0]:
        return None
    planned, actual = int(row[0]), int(row[1] or 0)
    counts = {"kept": 0, "partial": 0, "missed": 0, "ahead": 0}
    for block in review.block_outcomes(con, week_start, today):
        counts[block["status"]] += 1
    review.ensure(con)
    committed, met = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(done), 0) FROM block_objective"
        " WHERE week_start = ?", (week_start,)).fetchone()
    done = [_clean(item["text"]) for item in review.done_list(con, week_start)]
    # In the first planned week every mark is a best, which says nothing.
    bests = ([(b.label, b.value) for b in review.personal_bests(con, week_start)
              if b.this_week][:PARTNER_BESTS]
             if review.planned_weeks(con, week_start) >= 2 else [])
    monday = _dt.date.fromisoformat(week_start)
    before = con.execute(
        "SELECT planned_min, actual_min FROM v_week_overall WHERE week_start = ?",
        ((monday - _dt.timedelta(days=7)).isoformat(),)).fetchone()
    restart = bool(before and before[0] and not before[1] and actual)
    after = con.execute(
        "SELECT planned_min FROM v_week_overall WHERE week_start = ?",
        ((monday + _dt.timedelta(days=7)).isoformat(),)).fetchone()
    return {"week_start": week_start, "planned": planned, "actual": actual,
            "kept_pct": _pct(actual / planned), "blocks": counts,
            "committed": int(committed), "met": int(met),
            "done": done[:PARTNER_DONE], "done_total": len(done),
            "bests": bests, "restart": restart,
            "next_planned": int(after[0]) if after and after[0] else None}


def partner_facts(week: dict) -> str:
    """Write the week's numbers as the facts the model receives."""
    b = week["blocks"]
    lines = [f"Week starting: {week['week_start']}",
             f"Minutes planned: {week['planned']} ({_hours(week['planned'])})",
             f"Minutes written: {week['actual']} ({_hours(week['actual'])})",
             f"Share of the plan kept: {week['kept_pct']}%",
             f"Blocks kept: {b['kept']}",
             f"Blocks kept in part: {b['partial']}",
             f"Blocks missed: {b['missed']}",
             f"Blocks still ahead this week: {b['ahead']}"]
    if week["committed"]:
        lines += [f"Objectives committed: {week['committed']}",
                  f"Objectives met: {week['met']}"]
    lines += [f"Objective met: {text}" for text in week["done"]]
    lines += [f"Personal best set this week: {label}, {value}"
              for label, value in week["bests"]]
    if week["restart"]:
        lines.append("Back on the plan after a planned week with no writing: yes")
    if week["next_planned"]:
        lines.append(f"Minutes planned for next week: {week['next_planned']}"
                     f" ({_hours(week['next_planned'])})")
    return "\n".join(lines)


def _series(items: Sequence[str]) -> str:
    items = [i.rstrip(".") for i in items]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (", and " if len(items) > 2 else " and ") + items[-1]


def _date_words(week_start: str) -> str:
    day = _dt.date.fromisoformat(week_start)
    return f"{day.strftime('%B')} {day.day}"


def plain_partner(week: dict) -> str:
    """Write the summary without a model, in the writer's own voice.

    The message has up to three short paragraphs: the time, the work, and
    anything worth celebrating or planned next.
    """
    b = week["blocks"]
    passed = b["kept"] + b["partial"] + b["missed"]
    time = [f"Here is my writing week of {_date_words(week['week_start'])}.",
            f"I planned {_hours(week['planned'])} of writing and wrote "
            f"{_hours(week['actual'])}, which is {week['kept_pct']}% of the plan."]
    if passed:
        text = f"I kept {b['kept']} of the {passed} planned blocks that have passed"
        if b["partial"]:
            text += f" and kept {b['partial']} more in part"
        time.append(text + ".")
    if b["ahead"]:
        time.append(f"{b['ahead']} more block{'' if b['ahead'] == 1 else 's'} "
                    f"{'is' if b['ahead'] == 1 else 'are'} still ahead this week.")
    work = []
    met, committed = week["met"], week["committed"]
    if committed == 1:
        work.append("I met the one objective I committed to." if met else
                    "I did not meet the one objective I committed to.")
    elif committed and met == committed:
        work.append(f"I met all {committed} objectives I committed to.")
    elif committed:
        work.append(f"I met {met} of the {committed} objectives I committed to.")
    if week["done"]:
        # The objectives are quoted, because they are the writer's own words.
        quoted = ['"' + text.rstrip(".") + '"' for text in week["done"]]
        label = ("The objective I met was" if len(quoted) == 1
                 else "Objectives I met include")
        work.append(f"{label} {_series(quoted)}.")
    more = []
    if week["restart"]:
        more.append("This week put me back on the plan after a week without writing.")
    if week["bests"]:
        marks = [f"{label.lower()} at {value}" for label, value in week["bests"]]
        noun = "a personal best" if len(marks) == 1 else "personal bests"
        more.append(f"This week set {noun} for {_series(marks)}.")
    if week["next_planned"]:
        more.append(f"Next week I have planned {_hours(week['next_planned'])}.")
    return "\n\n".join(" ".join(p) for p in (time, work, more) if p)


def partner_summary(client: Optional[Client], con, week_start: str,
                    today: Optional[str] = None, log: bool = True,
                    prompts=None) -> Answer:
    """Draft the short weekly message the writer sends to a partner (Rule 8).

    The draft is the writer's to edit and send. Nothing is sent to the
    partner from here. A model's draft is used only when it states the share
    of the plan kept and carries no number that the facts do not hold.
    """
    week = partner_week(con, week_start, today)
    if week is None:
        return Answer(data=None,
                      text=("The week has no plan in the habit database yet, so "
                            "there is nothing to summarize. Import the plan first."),
                      source="no data")
    facts = partner_facts(week)
    allowed = _numbers(facts)

    def parse(reply):
        text = _clean(reply)
        if not text:
            raise CoachError("the local model sent an empty draft")
        if f"{week['kept_pct']}%" not in text:
            raise CoachError("the draft left out the share of the plan kept")
        if not _numbers(text) <= allowed:
            raise CoachError("the draft held a number that is not in your record")
        return text

    answer = _run("partner", client, facts, lambda: plain_partner(week), parse,
                  con if log else None, week_start, prompts)
    answer.data = {"text": answer.data, **week}
    return answer


# -- Rules 2 and 3: planning checks the software makes ----------------------------
def _note(task: str, client: Optional[Client], facts: str, plain_text: str,
          con=None, week_start: Optional[str] = None, prompts=None) -> Answer:
    """Word a planning check.  The proposals themselves never come from the model.

    The model writes a short note around proposals the software made. A note
    that carries a number the facts do not hold is replaced by the plain note.
    """
    allowed = _numbers(facts)

    def parse(reply):
        text = _clean(reply)
        if not text:
            raise CoachError("the local model sent an empty note")
        if not _numbers(text) <= allowed:
            raise CoachError("the note held a number that is not in the plan")
        return text

    return _run(task, client, facts, lambda: plain_text, parse, con, week_start, prompts)


def cover_deadlines(client: Optional[Client], result, con=None,
                    week_start: Optional[str] = None, prompts=None) -> Answer:
    """Explain a deadline coverage check (Rule 3).

    ``result`` is a :class:`writing_habit.deadlines.Coverage`. With nothing at
    risk the plain note is enough, so no model is asked and nothing is logged.
    """
    from . import deadlines

    plain_text = deadlines.plain(result)
    if not result.risks:
        return Answer(data={"note": plain_text, "result": result}, text=plain_text,
                      source="plain summary written without a model")
    answer = _note("coverage", client, deadlines.facts(result), plain_text,
                   con, week_start, prompts)
    answer.data = {"note": answer.data, "result": result}
    return answer


def match_energy(client: Optional[Client], profile, found, proposed, con=None,
                 week_start: Optional[str] = None, prompts=None) -> Answer:
    """Explain the blocks that do not fit the energy profile (Rule 2)."""
    from . import energy

    plain_text = energy.plain(profile, found, proposed)
    if not found:
        return Answer(data={"note": plain_text, "misfits": [], "swaps": []},
                      text=plain_text, source="plain summary written without a model")
    answer = _note("energy", client, energy.facts(profile, found, proposed),
                   plain_text, con, week_start, prompts)
    answer.data = {"note": answer.data, "misfits": list(found), "swaps": list(proposed)}
    return answer


# -- does the coach help? -----------------------------------------------------------
def ai_week_comparison(con, end_week: Optional[str] = None) -> Optional[dict]:
    """Compare adherence in weeks with coach calls against weeks without.

    Return ``None`` until each side has at least two planned weeks, because a
    comparison of one week against one week says nothing.
    """
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "ai_log" not in have:
        return None
    with_ai = {r[0] for r in con.execute(
        "SELECT DISTINCT week_start FROM ai_log WHERE week_start IS NOT NULL")}
    clause, params = "", []
    if end_week:
        clause, params = " AND week_start <= ?", [end_week]
    rows = [dict(r) for r in con.execute(
        "SELECT week_start, planned_min, actual_min FROM v_week_overall"
        " WHERE planned_min > 0" + clause, params)]
    on = [r for r in rows if r["week_start"] in with_ai]
    off = [r for r in rows if r["week_start"] not in with_ai]
    if len(on) < 2 or len(off) < 2:
        return None

    def kept(group):
        return round(sum(r["actual_min"] for r in group)
                     / sum(r["planned_min"] for r in group), 2)
    return {"with_ai": len(on), "with_ai_kept": kept(on),
            "without_ai": len(off), "without_ai_kept": kept(off)}
