"""The coach: the local-only client, the facts, the guardrails, and the log."""

from __future__ import annotations

import datetime as dt
import io
import json
import urllib.error

import pytest

from writing_habit import coach, db, review
from writing_habit.coach import Client, CoachError
from writing_habit.track import manual


class _Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_model(content, api="ollama", sent=None):
    """Return an opener that answers every request with ``content``."""
    def opener(request, timeout):
        if sent is not None:
            sent.append((request.full_url, json.loads(request.data.decode())))
        text = content if isinstance(content, str) else json.dumps(content)
        if api == "ollama":
            body = {"message": {"role": "assistant", "content": text}}
        else:
            body = {"choices": [{"message": {"content": text}}]}
        return _Reply(json.dumps(body).encode())
    return opener


def down(request, timeout):
    raise urllib.error.URLError("connection refused")


@pytest.fixture()
def con(tmp_path):
    c = db.connect(str(tmp_path / "habit.db"))
    db.init_db(c)
    yield c
    c.close()


def _week(con, week, planned, actual, code="A", day_offset=0, schedule=None, tag=None):
    pid = db.get_or_create_project(con, code, f"project {code}", "safe")
    day = (dt.date.fromisoformat(week) + dt.timedelta(days=day_offset)).isoformat()
    con.execute("INSERT INTO plan_block(day, start_time, end_time, project_id, category_id)"
                " VALUES (?, '05:00', ?, ?, 1)",
                (day, f"{5 + planned // 60:02d}:{planned % 60:02d}", pid))
    if actual:
        manual.add_session(con, day=day, project_code=code, minutes=actual,
                           category="generative")
    if schedule:
        con.execute("INSERT OR REPLACE INTO plan_week(week_start, schedule_code)"
                    " VALUES (?, ?)", (week, schedule))
    if tag:
        con.execute("INSERT INTO week_context(week_start, tag) VALUES (?, ?)", (week, tag))
    con.commit()


# -- the prompts ------------------------------------------------------------------
def test_the_prompts_file_covers_every_task_and_forbids_ghostwriting():
    prompts = coach.load_prompts()
    assert set(prompts["tasks"]) == {"objectives", "grasscatcher", "debrief",
                                     "weeks", "size", "partner", "coverage", "energy", "capture"}
    assert "never write" in prompts["rules"]
    for name, task in prompts["tasks"].items():
        assert task["system"] and task["instruction"], name
        assert {"rule"} <= set(task)


# -- the client ---------------------------------------------------------------------
def test_ollama_requests_go_to_api_chat_with_the_schema():
    sent = []
    client = Client("tiny", opener=fake_model({"objectives": ["a"], "if_then": "b"},
                                              sent=sent))
    reply = client.ask("objectives", "Task: x")
    assert reply == {"objectives": ["a"], "if_then": "b"}
    url, body = sent[0]
    assert url == "http://localhost:11434/api/chat"
    assert body["format"]["required"] == ["objectives", "if_then"]
    assert body["messages"][1]["content"].endswith("Task: x")


def test_openai_style_requests_use_chat_completions():
    sent = []
    client = Client("tiny", url="http://127.0.0.1:1234", api="openai",
                    opener=fake_model("Fine.", api="openai", sent=sent))
    assert client.ask("size", "Suggested minutes: 300") == "Fine."
    assert sent[0][0] == "http://127.0.0.1:1234/v1/chat/completions"
    assert "response_format" not in sent[0][1]


def test_a_remote_address_is_refused_before_anything_is_sent():
    sent = []
    client = Client("tiny", url="https://api.example.com", opener=fake_model("x", sent=sent))
    with pytest.raises(CoachError, match="not on this computer"):
        client.ask("size", "facts")
    assert sent == []
    allowed = Client("tiny", url="https://api.example.com", allow_remote=True,
                     opener=fake_model("ok"))
    assert allowed.ask("size", "facts") == "ok"


def test_a_reply_that_is_not_json_is_a_coach_error():
    with pytest.raises(CoachError, match="expected form"):
        Client("tiny", opener=fake_model("not json")).ask("objectives", "Task: x")


# -- guardrails ---------------------------------------------------------------------
class _Block:
    def __init__(self, offset, start, end, letter="A"):
        self.offset, self.start, self.end, self.letter = offset, start, end, letter


def test_block_now_finds_the_block_on_the_clock():
    monday = dt.date(2026, 10, 12)
    blocks = [_Block(1, "05:00", "07:00")]
    inside = dt.datetime(2026, 10, 13, 6, 15)
    assert coach.block_now(blocks, monday, inside) is blocks[0]
    assert coach.block_now(blocks, monday, dt.datetime(2026, 10, 13, 7, 0)) is None
    assert coach.block_now(blocks, None, inside) is None


def test_the_coach_is_quiet_in_a_block_and_in_an_ai_off_week():
    today = dt.date(2026, 10, 14)
    with pytest.raises(CoachError, match="silent during deep work"):
        coach.check_allowed(today, in_block=_Block(2, "05:00", "06:00"))
    coach.check_allowed(today, in_block=_Block(2, "05:00", "06:00"), insist=True)
    with pytest.raises(CoachError, match="AI-off week"):
        coach.check_allowed(today, off_week="2026-10-12")
    coach.check_allowed(today, off_week="2026-10-05")


# -- Rule 4 ----------------------------------------------------------------------------
def test_objective_facts_hold_only_the_listed_fields():
    facts = coach.objective_facts("work on the R01", "1002RNAediting", 120,
                                  deadline="2027-02-05", waiting=["find citations"],
                                  last_step="start at aim 2")
    assert facts.splitlines()[0] == "Task: work on the R01"
    assert "Block length: 120 minutes" in facts
    assert "  - find citations" in facts


def test_suggest_objectives_trims_to_three_and_logs(con):
    reply = {"objectives": [" Draft aim 2 ", "Find 3 citations", "Revise fig 1",
                            "Extra"], "if_then": "If email calls, then I will park it."}
    answer = coach.suggest_objectives(Client("tiny", opener=fake_model(reply)),
                                      "Task: R01", con=con, week_start="2026-10-12")
    assert answer.data["objectives"] == ["Draft aim 2", "Find 3 citations", "Revise fig 1"]
    assert answer.source == "local model tiny"
    row = con.execute("SELECT task, source, facts, week_start FROM ai_log").fetchone()
    assert tuple(row) == ("objectives", "local model tiny", "Task: R01", "2026-10-12")


def test_suggest_objectives_without_a_model_gives_advice_only(con):
    answer = coach.suggest_objectives(Client("tiny", opener=down), "Task: R01", con=con)
    assert answer.data["objectives"] == []
    assert "did not answer" in answer.source
    answer = coach.suggest_objectives(None, "Task: R01")
    assert answer.source == "plain summary written without a model"


def test_rank_grasscatcher_keeps_every_task_once():
    tasks = [("A", "tidy bib"), ("B", "find citations"), (None, "clean desk")]
    deadlines = {"A": "2026-12-01", "B": "2026-11-01"}
    planned = {"A": 120, "B": 60}
    plain = coach.rank_grasscatcher(None, tasks, deadlines, planned)
    assert [i["index"] for i in plain.data] == [1, 0, 2]
    reply = {"order": [{"index": 2, "reason": "quick"}, {"index": 2, "reason": "dup"},
                       {"index": 7, "reason": "bad"}, {"index": 0, "reason": "soon"}]}
    ranked = coach.rank_grasscatcher(Client("tiny", opener=fake_model(reply)),
                                     tasks, deadlines, planned)
    assert [i["index"] for i in ranked.data] == [2, 0, 1]
    assert ranked.data[2]["reason"] == "left where it was"


# -- Rule 7 ----------------------------------------------------------------------------
def _history(con):
    # Mondays kept fully, Wednesdays kept a quarter, over five weeks.
    for week in ("2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05"):
        _week(con, week, 60, 60, day_offset=0)
        _week(con, week, 60, 15, code="B", day_offset=2)


def test_strongest_patterns_need_enough_weeks():
    rows = [{"kind": "weekday", "group": "Monday", "adherence": 1.0, "weeks": 5},
            {"kind": "event", "group": "travel", "adherence": 0.1, "weeks": 1},
            {"kind": "weekday", "group": "Wednesday", "adherence": 0.25, "weeks": 5}]
    top = coach.strongest_patterns(rows, 0.7)
    assert [r["group"] for r in top] == ["Wednesday", "Monday"]


def test_read_weeks_plain_states_the_numbers(con):
    _history(con)
    answer = coach.read_weeks(None, con, end_week="2026-10-05")
    groups = [r["group"] for r in answer.data["rows"]]
    assert set(groups) == {"Monday", "Wednesday"}
    text = answer.text
    assert "Your Wednesday blocks kept 25%" in text
    assert "over 5 weeks" in text and "small sample" in text
    assert "Plan fewer minutes for your Wednesday blocks" in answer.data["change"]


def test_read_weeks_replaces_a_sentence_with_an_invented_number(con):
    _history(con)
    reply = {"patterns": ["Wednesdays slip, kept 25% over 5 weeks.",
                          "Mondays are perfect, 100% for 40 weeks."],
             "change": "Move Wednesday writing to Monday mornings."}
    answer = coach.read_weeks(Client("tiny", opener=fake_model(reply)), con,
                              end_week="2026-10-05")
    patterns = answer.data["patterns"]
    assert any(p.startswith("Wednesdays slip") for p in patterns)
    assert not any("40 weeks" in p for p in patterns)
    assert answer.data["change"] == "Move Wednesday writing to Monday mornings."
    assert con.execute("SELECT COUNT(*) FROM ai_log WHERE task = 'weeks'").fetchone()[0] == 1


def test_read_weeks_with_too_few_weeks_says_so(con):
    _week(con, "2026-10-05", 60, 30)
    answer = coach.read_weeks(None, con)
    assert "no pattern to report" in answer.text
    assert answer.data["patterns"] == []


def test_size_next_week_uses_the_median_of_what_was_written(con):
    for week, actual in (("2026-09-14", 200), ("2026-09-21", 300), ("2026-09-28", 260)):
        _week(con, week, 360, actual, schedule="gAeB")
    _week(con, "2026-10-05", 480, 0)
    size = coach.size_next_week(con, "2026-10-05")
    assert size["minutes"] == 255           # median 260, rounded to 15
    assert size["weeks"] == 3
    assert size["current"] == 480
    same = coach.size_next_week(con, "2026-10-05", schedule_code="gAeB")
    assert "gAeB plan" in same["basis"]
    text = coach.explain_size(None, size).data["text"]
    assert "4 h 15 min" in text and "trimming" in text


def test_size_follows_an_event_tag_with_two_weeks(con):
    _week(con, "2026-09-07", 360, 300)
    _week(con, "2026-09-14", 360, 90, tag="teaching")
    _week(con, "2026-09-21", 360, 120, tag="teaching")
    size = coach.size_next_week(con, "2026-10-05", tags=["teaching"])
    assert size["minutes"] == 105 and "teaching" in size["basis"]


def test_explain_size_keeps_the_number_when_the_model_drops_it(con):
    for week in ("2026-09-14", "2026-09-21"):
        _week(con, week, 360, 300)
    size = coach.size_next_week(con, "2026-10-05")
    answer = coach.explain_size(Client("tiny", opener=fake_model("Plan less.")), size)
    assert "5 h 00 min" in answer.data["text"]


def test_ai_week_comparison_needs_two_weeks_on_each_side(con):
    for week, actual in (("2026-09-07", 30), ("2026-09-14", 30),
                         ("2026-09-21", 60), ("2026-09-28", 60)):
        _week(con, week, 60, actual)
    coach.log_call(con, "size", "plain", "f", "r", "2026-09-21")
    assert coach.ai_week_comparison(con) is None
    coach.log_call(con, "size", "plain", "f", "r", "2026-09-28")
    result = coach.ai_week_comparison(con)
    assert result == {"with_ai": 2, "with_ai_kept": 1.0,
                      "without_ai": 2, "without_ai_kept": 0.5}


def test_mark_accepted_and_the_ai_origin(con):
    log_id = coach.log_call(con, "objectives", "m", "f", "r")
    coach.mark_accepted(con, log_id, True)
    assert con.execute("SELECT accepted FROM ai_log").fetchone()[0] == 1
    review.add_objective(con, review.BlockKey("2026-10-12", "05:00", "A"),
                         "Draft aim 2", origin="ai")


def test_ensure_widens_an_old_objective_table(tmp_path):
    path = tmp_path / "old.db"
    con = db.connect(str(path))
    old = coach.PROMPTS_PATH.with_name("schema.sql").read_text().replace(
        "('typed','grasscatcher','ai')", "('typed','grasscatcher')")
    con.executescript(old)
    key = review.BlockKey("2026-10-12", "05:00", "A")
    review.add_objective(con, key, "kept through the upgrade")
    review.ensure(con)
    review.add_objective(con, key, "from the coach", origin="ai")
    assert [o.text for o in review.objectives(con, key)] == [
        "kept through the upgrade", "from the coach"]
    con.close()


def test_a_missing_model_names_the_pull_command():
    import urllib.error

    def opener(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", {},
            io.BytesIO(b'{"error": "model \\"qwen2.5:7b\\" not found, try pulling it first"}'))

    with pytest.raises(CoachError, match="run ollama pull qwen2.5:7b"):
        Client("qwen2.5:7b", opener=opener).ask("size", "x")


def test_ranking_pins_the_reply_to_the_task_count():
    sent = []
    reply = {"order": [{"index": 1, "reason": "a"}, {"index": 0, "reason": "b"}]}
    coach.rank_grasscatcher(Client("tiny", opener=fake_model(reply, sent=sent)),
                            [("A", "x"), ("B", "y")], {}, {})
    body = sent[0][1]
    order = body["format"]["properties"]["order"]
    assert order["minItems"] == order["maxItems"] == 2
    assert order["items"]["properties"]["index"]["enum"] == [0, 1]
    assert "There are 2 tasks, numbered 0 to 1" in body["messages"][1]["content"]


def test_read_weeks_replaces_a_bare_label(con):
    """llama3.2 once answered with the bare words Wednesday and gAeB."""
    _history(con)
    reply = {"patterns": ["Wednesday", "Monday"], "change": "Add a buffer day."}
    answer = coach.read_weeks(Client("tiny", opener=fake_model(reply)), con,
                              end_week="2026-10-05")
    assert all("% of their planned minutes" in p for p in answer.data["patterns"])


def test_list_models_reads_both_interfaces():
    def ollama(request, timeout):
        assert request.full_url == "http://localhost:11434/api/tags"
        return _Reply(json.dumps({"models": [{"name": "qwen2.5:7b"},
                                             {"name": "llama3.2:latest"}]}).encode())

    assert coach.list_models(opener=ollama) == ["llama3.2:latest", "qwen2.5:7b"]

    def openai(request, timeout):
        assert request.full_url == "http://127.0.0.1:1234/v1/models"
        return _Reply(json.dumps({"data": [{"id": "gemma"}]}).encode())

    assert coach.list_models("http://127.0.0.1:1234", "openai", opener=openai) == ["gemma"]
    with pytest.raises(CoachError, match="not on this computer"):
        coach.list_models("https://example.com", opener=ollama)
    with pytest.raises(CoachError, match="no model server answered"):
        coach.list_models(opener=down)


# -- Rule 8: the Friday summary for a partner ------------------------------------------
def _partner_week(con):
    """A week of three planned blocks: one kept, one missed, one still ahead."""
    week = "2026-10-12"
    _week(con, week, 120, 120, code="A", day_offset=0)
    _week(con, week, 60, 0, code="B", day_offset=1)
    _week(con, week, 60, 0, code="A", day_offset=4)
    review.ensure(con)
    key = review.BlockKey("2026-10-12", "05:00", "A")
    for text, done in (("Draft the second aim paragraph", True),
                       ("Find three citations", True),
                       ("Revise figure 2", False)):
        oid = review.add_objective(con, key, text)
        review.mark(con, oid, done)
    return week


def test_partner_plain_summary_states_the_week(con):
    week = _partner_week(con)
    answer = coach.partner_summary(None, con, week, today="2026-10-14")
    text = answer.data["text"]
    assert answer.source.startswith("plain summary")
    assert "week of October 12" in text
    assert "I planned 4 h 00 min of writing and wrote 2 h 00 min, which is 50% of the plan." in text
    assert "I kept 1 of the 2 planned blocks that have passed." in text
    assert "1 more block is still ahead this week." in text
    assert "I met 2 of the 3 objectives I committed to." in text
    assert 'Objectives I met include "Draft the second aim paragraph" and "Find three citations".' in text
    assert text.count("\n\n") == 1                     # time, then work
    assert "personal best" not in text                  # a first week sets every mark
    assert "Revise figure 2" not in text
    assert answer.data["blocks"] == {"kept": 1, "partial": 0, "missed": 1, "ahead": 1}
    assert con.execute("SELECT task FROM ai_log").fetchall()[0][0] == "partner"


def test_partner_facts_hold_only_the_summary(con):
    week = _partner_week(con)
    facts = coach.partner_facts(coach.partner_week(con, week, today="2026-10-14"))
    assert "Share of the plan kept: 50%" in facts
    assert "Objective met: Draft the second aim paragraph" in facts
    assert "Revise figure 2" not in facts          # unmet objectives stay private
    assert "session" not in facts.lower()


def test_partner_keeps_a_model_draft_that_uses_the_facts(con):
    week = _partner_week(con)
    reply = ("This week I drafted the second aim paragraph and found three "
             "citations. I kept 50% of my plan and met 2 of 3 objectives.")
    answer = coach.partner_summary(Client("tiny", opener=fake_model(reply)), con, week,
                                   today="2026-10-14")
    assert answer.source == "local model tiny"
    assert answer.data["text"] == reply


def test_partner_rejects_a_draft_with_an_invented_number(con):
    week = _partner_week(con)
    reply = "I kept 50% of my plan and wrote 1,200 words."
    answer = coach.partner_summary(Client("tiny", opener=fake_model(reply)), con, week,
                                   today="2026-10-14")
    assert "not in your record" in answer.source
    assert answer.data["text"].startswith("Here is my writing week")


def test_partner_rejects_a_draft_without_the_share_kept(con):
    week = _partner_week(con)
    answer = coach.partner_summary(Client("tiny", opener=fake_model("A fine week.")),
                                   con, week, today="2026-10-14")
    assert "share of the plan kept" in answer.source


def test_partner_notes_a_restart_a_best_and_next_week(con):
    _week(con, "2026-10-05", 60, 0)                 # a planned week with no writing
    _week(con, "2026-10-12", 60, 60)
    _week(con, "2026-10-19", 90, 0)                 # next week's plan
    answer = coach.partner_summary(None, con, "2026-10-12", today="2026-10-18")
    text = answer.data["text"]
    assert "back on the plan after a week without writing" in text
    assert ("personal bests for most of the plan kept at 100% and most minutes "
            "written at 1 h 00 min.") in text
    assert "Next week I have planned 1 h 30 min." in text


def test_partner_without_a_plan_says_so(con):
    answer = coach.partner_summary(None, con, "2026-10-12")
    assert answer.data is None
    assert "nothing to summarize" in answer.text
    assert con.execute("SELECT COUNT(*) FROM ai_log").fetchone()[0] == 0


def test_partner_unlogged_leaves_the_week_without_ai(con):
    week = _partner_week(con)
    coach.partner_summary(None, con, week, today="2026-10-14", log=False)
    assert con.execute("SELECT COUNT(*) FROM ai_log").fetchone()[0] == 0
