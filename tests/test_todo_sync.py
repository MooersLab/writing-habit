"""Syncing the grasscatcher list with the Project TODOS of a project's log."""

from pathlib import Path

import pytest

from writing_habit import todo_sync as ts
from writing_habit.project_lists import GRASSCATCHER, Entry, ProjectLists

LOG = """\
#+TITLE: Writing log for 0142 Covalent inhibitor modeling of RET Kinase
* Daily log
** 2026 October 19
** TODO this heading is not under Project TODOS

* Project TODOS

** TODO [#A1] Read the key review articles on covlent docking.
Some notes under the first to-do.
** DONE [#B] Measure the cysteine distances in 7JU6
** NEXT Draft the docking protocol section :writing:
** WAITING [#2] Ask the core for GPU time
*** TODO [#C3] A nested to-do counts too
** Not a to-do heading

* Notes
Text after the section.
"""


@pytest.fixture()
def project(tmp_path):
    folder = tmp_path / "0142RETKinaseCovalentInhibitors"
    folder.mkdir()
    log = folder / "log0142.org"
    log.write_text(LOG, encoding="utf-8")
    return tmp_path, log


# -- cookies ----------------------------------------------------------------------
@pytest.mark.parametrize("text,priority,title", [
    ("[#A1] Read it", "A1", "Read it"),
    ("[#a] lower case", "A", "lower case"),
    ("[#12] number only", "12", "number only"),
    ("no cookie here", None, "no cookie here"),
    ("  [#B2]   spaced ", "B2", "spaced"),
])
def test_split_priority(text, priority, title):
    assert ts.split_priority(text) == (priority, title)
    if priority:
        assert ts.join_priority(priority, title) == f"[#{priority}] {title}"


def test_priority_order():
    cookies = [None, "B", "A2", "3", "A", "A10", "1", "C1"]
    ordered = sorted(cookies, key=ts.priority_key)
    assert ordered == ["A", "A2", "A10", "B", "C1", "1", "3", None]


def test_task_key_ignores_cookie_case_and_full_stop():
    assert ts.task_key("[#A1] Read the key review articles.") == \
        ts.task_key("read the  KEY review articles")


# -- reading -----------------------------------------------------------------------
def test_only_the_project_todos_section_is_read():
    todos = ts.read_todos(LOG)
    assert [(t.keyword, t.priority, t.title) for t in todos] == [
        ("TODO", "A1", "Read the key review articles on covlent docking."),
        ("DONE", "B", "Measure the cysteine distances in 7JU6"),
        ("NEXT", None, "Draft the docking protocol section"),
        ("WAITING", "2", "Ask the core for GPU time"),
        ("TODO", "C3", "A nested to-do counts too"),
    ]
    assert todos[1].done and not todos[0].done


def test_a_log_without_the_section_has_no_todos():
    assert ts.read_todos("* Daily log\n** TODO later\n") == []


# -- finding the log ------------------------------------------------------------------
def test_the_folder_named_like_the_project_wins(project):
    root, log = project
    (root / "0142RETKinaseDocking").mkdir()
    (root / "0142RETKinaseDocking" / "log0142.org").write_text("* Project TODOS\n")
    found, _candidates = ts.find_log("0142RETKinaseCovalentInhibitors", root)
    assert found == log


def test_a_single_numbered_folder_is_found(project):
    root, log = project
    assert ts.find_log("0142covalent", root)[0] == log


def test_several_numbered_folders_are_reported(project):
    root, _log = project
    (root / "0142RETKinaseDocking").mkdir()
    (root / "0142RETKinaseDocking" / "log0142.org").write_text("* Project TODOS\n")
    found, candidates = ts.find_log("0142other", root)
    assert found is None and len(candidates) == 2


def test_a_project_without_a_number_has_no_log(project):
    root, _log = project
    assert ts.find_log("email", root) == (None, [])


# -- planning ---------------------------------------------------------------------------
def test_the_plan_compares_both_sides(project):
    _root, log = project
    rows = [(0, "1", "[#A3] Read the key review articles on covlent docking"),  # cookie differs
            (1, "1", "Measure the cysteine distances in 7JU6."),               # done in log
            (2, "1", "[#B1] Run GNINA with the covalent option"),               # new
            (3, "2", "[#A] A task of another project")]
    plan = ts.plan_project("1", "0142RETKinaseCovalentInhibitors", log, rows)
    assert plan.problem is None
    assert plan.reprioritize == [(0, "[#A1] Read the key review articles on covlent docking")]
    assert plan.done == [1]
    assert plan.to_log == ["[#B1] Run GNINA with the covalent option"]
    assert plan.to_grasscatcher == ["Draft the docking protocol section",
                                    "[#2] Ask the core for GPU time",
                                    "[#C3] A nested to-do counts too"]
    assert plan.changes == 6


def test_a_missing_log_is_a_problem_not_a_change():
    plan = ts.plan_project("Q", "0999nothing", None, [])
    assert plan.problem == "no log file found" and plan.changes == 0


def test_an_emacs_lock_is_noticed(project):
    _root, log = project
    (log.parent / "#log0142.org#").write_text("autosave")
    assert ts.plan_project("1", "p", log, []).lock is not None


# -- writing the log ---------------------------------------------------------------------
def test_new_todos_go_at_the_end_of_the_section_only():
    out = ts.add_to_log(LOG, ["[#B1] Run GNINA", "Plain task"])
    before, after = LOG.splitlines(), out.splitlines()
    added = [line for line in after if line not in before]
    assert added == ["** TODO [#B1] Run GNINA", "** TODO Plain task"]
    assert after.index("** TODO Plain task") < after.index("* Notes")
    assert after.index("** TODO [#B1] Run GNINA") > after.index("** Not a to-do heading")
    # Every old line is still there, in order.
    assert [line for line in after if line in before] == before


def test_a_log_without_the_section_gets_one():
    out = ts.add_to_log("* Daily log\nentry\n", ["[#A] First"])
    assert out.endswith("* Project TODOS\n\n** TODO [#A] First\n")


def test_write_log_keeps_a_copy(project):
    _root, log = project
    assert ts.write_log(log, ["[#A] new task"]) == 1
    assert (log.parent / "log0142.org~").read_text() == LOG
    assert "** TODO [#A] new task" in log.read_text()
    assert ts.write_log(log, []) == 0


# -- the grasscatcher side ------------------------------------------------------------------
def test_apply_changes_the_grasscatcher(project):
    _root, log = project
    lists = ProjectLists([])
    for code, text in [("1", "[#A3] Read the key review articles on covlent docking"),
                       ("1", "Measure the cysteine distances in 7JU6"),
                       ("2", "keep me")]:
        lists.insert(GRASSCATCHER, None, Entry(code, text))
    plan = ts.plan_project("1", "p", log, ts.grasscatcher_rows(lists))
    assert ts.apply_to_lists(lists, [plan]) == 5
    texts = [(e.code, e.description) for e in lists.entries(GRASSCATCHER)]
    assert texts == [
        ("1", "[#A1] Read the key review articles on covlent docking"),
        ("2", "keep me"),
        ("1", "Draft the docking protocol section"),
        ("1", "[#2] Ask the core for GPU time"),
        ("1", "[#C3] A nested to-do counts too")]
    # A second sync finds nothing more to do.
    again = ts.plan_project("1", "p", log, ts.grasscatcher_rows(lists))
    assert again.changes == 0


def test_sort_by_priority():
    lists = ProjectLists([])
    for text in ["no cookie", "[#B] bee", "[#A2] a two", "[#A] a"]:
        lists.insert(GRASSCATCHER, None, Entry("1", text))
    assert ts.sort_by_priority(lists)
    assert [e.description for e in lists.entries(GRASSCATCHER)] == [
        "[#A] a", "[#A2] a two", "[#B] bee", "no cookie"]
    assert not ts.sort_by_priority(lists)


def test_a_cookie_survives_the_list_round_trip():
    lists = ProjectLists([])
    lists.insert(GRASSCATCHER, None, Entry("1", "[#A1] Read it. 2026-11-01"))
    entry = lists.entries(GRASSCATCHER)[0]
    assert ts.split_priority(entry.description)[0] == "A1"
    assert lists.lines[-1] == "| 1: [#A1] Read it. 2026-11-01 |"
