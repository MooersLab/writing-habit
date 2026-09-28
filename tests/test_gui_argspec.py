"""The generated command descriptors must cover the command line exactly.

These tests need no Qt, because the walk over an argparse parser is plain
Python. They are the guard on the private argparse attributes the walk reads,
so a change in a future Python fails here with a clear message rather than in
the interface.
"""

import pytest

from writing_habit import cli
from writing_habit.gui import argspec

SPECS = argspec.commands(cli.build_parser())

EXPECTED = {
    "initdb", "plan import", "track import", "track add", "compare",
    "dashboard", "history", "context set", "context clear", "context list",
    "seasons", "name",
}


def test_every_subcommand_is_described():
    assert set(SPECS) == EXPECTED


def test_nested_commands_keep_their_word_path():
    assert SPECS["plan import"].path == ("plan", "import")
    assert SPECS["context clear"].path == ("context", "clear")


def test_options_carry_their_shape():
    week = SPECS["compare"].option("--week")
    assert week.required and not week.is_flag and week.choices is None

    fmt = SPECS["track import"].option("--format")
    assert fmt.choices == ("csv", "ics")

    minutes = SPECS["track add"].option("--minutes")
    assert minutes.is_int and not minutes.required

    path = SPECS["plan import"].option("path")
    assert path.positional and path.required


def test_two_commands_may_share_a_dest_with_different_meanings():
    """history --from and track add --start both carry the dest ``start``."""
    assert SPECS["history"].option("--from").dest == "start"
    assert SPECS["track add"].option("--start").dest == "start"


@pytest.mark.parametrize(
    "name,values",
    [
        ("initdb", {"db": "h.db"}),
        ("plan import", {"path": "my-week.org", "week": "2026-01-19", "db": "h.db"}),
        ("track import", {"path": "a.csv", "format": "ics", "db": "h.db"}),
        ("track add", {"day": "2026-01-19", "project": "A", "minutes": "75",
                       "category": "generative", "db": "h.db"}),
        ("compare", {"week": "2026-01-19", "plot": "p.png", "db": "h.db"}),
        ("dashboard", {"week": "2026-01-19", "out": "w.html", "db": "h.db"}),
        ("history", {"start": "2026-01-01", "end": "2026-06-30", "db": "h.db"}),
        ("context set", {"week": "2026-03-16", "tag": "teaching", "db": "h.db"}),
        ("seasons", {"out": "s.html", "db": "h.db"}),
        ("name", {"code": "4gAAeAsA-gWW"}),
    ],
)
def test_the_generated_argv_parses_back_to_the_same_values(name, values):
    argv = argspec.to_argv(SPECS[name], values)
    parsed = vars(cli.build_parser().parse_args(argv))
    for dest, value in values.items():
        assert str(parsed[dest]) == str(value)


def test_an_omitted_optional_value_leaves_the_flag_out():
    argv = argspec.to_argv(SPECS["history"], {"start": None, "end": None, "db": "h.db"})
    assert argv == ["history", "--db", "h.db"]


def test_an_empty_string_is_a_value_rather_than_an_omission():
    """writing-schedule --tz "" asks for floating times, so "" must survive."""
    ws_cli = pytest.importorskip(
        "writing_schedule.cli", reason="the writing-schedule package is not installed")
    specs = argspec.commands(ws_cli.build_parser())
    argv = argspec.to_argv(specs["export"], {"table": "my-week.org",
                                             "week": "2026-01-19", "tz": ""})
    assert argv == ["export", "my-week.org", "--week", "2026-01-19", "--tz", ""]
    assert ws_cli.build_parser().parse_args(argv).tz == ""


def test_missing_required_names_the_flags():
    missing = argspec.missing_required(SPECS["plan import"], {"week": "2026-01-19"})
    assert missing == ["path", "--db"]
    assert argspec.missing_required(
        SPECS["initdb"], {"db": "h.db"}) == []


def test_command_string_quotes_a_path_with_a_space():
    argv = argspec.to_argv(SPECS["initdb"], {"db": "/tmp/my writing/h.db"})
    line = argspec.command_string("writing-habit", argv)
    assert line == "writing-habit initdb --db '/tmp/my writing/h.db'"


def test_the_schedule_parser_walks_too():
    ws_cli = pytest.importorskip(
        "writing_schedule.cli", reason="the writing-schedule package is not installed")
    specs = argspec.commands(ws_cli.build_parser())
    assert {"generate", "export", "sheets", "template", "weeks", "check"} <= set(specs)
    assert specs["sheets"].option("--engine").choices == ("reportlab", "latex")
