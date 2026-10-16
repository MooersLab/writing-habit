"""The post-block debrief: the prompt, the local summary, and the model call."""

import io
import json
import urllib.error

import pytest

from writing_habit import debrief
from writing_habit.debrief import BlockFacts

FACTS = BlockFacts(project="1006AIrxOpt", minutes=120,
                   objectives=[("Draft aim 2", True), ("Find three citations", False)],
                   focus=4, interruptions=2, next_step="", note="phone rang")


class _Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_prompt_carries_only_the_review():
    text = debrief.prompt(FACTS)
    assert "Project: 1006AIrxOpt" in text
    assert "[met] Draft aim 2" in text
    assert "[not met] Find three citations" in text
    assert "Self-rated focus: 4 of 5" in text
    assert "Writer's note: phone rang" in text


def test_the_local_summary_leads_with_the_win_and_suggests_a_next_step():
    text = debrief.local_debrief(FACTS)
    assert text.startswith("You finished Draft aim 2.")
    assert "2 interruptions" in text
    assert "Find three citations" in text
    assert "—" not in text and ":" not in text.replace("note:", "")


def test_a_block_with_no_objectives_still_gets_credit_for_showing_up():
    text = debrief.local_debrief(BlockFacts(project="B", minutes=60))
    assert "showed up for 60 minutes" in text


def test_ask_model_posts_to_the_local_server():
    sent = {}

    def opener(request, timeout):
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data.decode())
        return _Reply(json.dumps({"response": " Well done. "}).encode())

    text = debrief.ask_model(FACTS, "llama3.2", "http://localhost:11434", opener=opener)
    assert text == "Well done."
    assert sent["url"] == "http://localhost:11434/api/generate"
    assert sent["body"]["model"] == "llama3.2"
    assert sent["body"]["stream"] is False
    assert "never write" in sent["body"]["system"]


def test_a_remote_server_is_refused_unless_allowed():
    with pytest.raises(RuntimeError, match="not on this computer"):
        debrief.ask_model(FACTS, "m", "https://api.example.com",
                          opener=lambda *a, **k: None)


def test_an_unreachable_model_falls_back_to_the_summary():
    def opener(request, timeout):
        raise urllib.error.URLError("connection refused")

    text, source = debrief.debrief(FACTS, True, "llama3.2", opener=opener)
    assert text == debrief.local_debrief(FACTS)
    assert "did not answer" in source


def test_model_off_never_calls_out():
    def opener(*_a, **_k):
        raise AssertionError("must not be called")

    text, source = debrief.debrief(FACTS, False, "llama3.2", opener=opener)
    assert source == "summary without a model"
