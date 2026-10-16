"""The calendar of planning periods, list titles, and rolling the lists forward.

None of these tests needs Qt.
"""

import datetime as dt

import pytest

from writing_habit import periods as pm
from writing_habit.project_lists import (CARRIED, COMPLETED, CURRENT, HORIZONS,
                                         ProjectLists, list_titles, read_lists)
from writing_habit.track.mytime_sync import semester_numbers

D = dt.date

CALENDAR = """\
#+TITLE: Planning periods

Notes kept above the table.

#+NAME: periods
| Kind     | Name        | Start      | End        | Horizon |
|----------+-------------+------------+------------+---------|
| semester | Fall 2026   | 2026-08-04 | 2026-12-18 | yes     |
| semester | Spring 2027 | 2026-12-19 | 2027-05-14 | yes     |
| semester | Summer 2027 | 2027-05-15 | 2027-08-02 | yes     |
| semester | Fall 2027   | 2027-08-03 | 2027-12-17 | yes     |
| semester | Spring 2028 | 2027-12-18 | 2028-05-13 | yes     |
| semester | Summer 2028 | 2028-05-14 | 2028-08-01 | yes     |
| fiscal   | FY 2027     | 2026-07-01 | 2027-06-30 | yes     |

Notes kept below the table.
"""


@pytest.fixture()
def calendar():
    return pm.Calendar.parse(CALENDAR)


# -- reading and writing ---------------------------------------------------------
def test_the_table_is_read(calendar):
    assert len(calendar.periods) == 7
    assert calendar.kinds() == ["semester", "fiscal"]
    fall = calendar.periods[0]
    assert (fall.kind, fall.name, fall.start, fall.end, fall.horizon) == (
        "semester", "Fall 2026", D(2026, 8, 4), D(2026, 12, 18), True)
    assert calendar.check() == []


def test_an_unchanged_calendar_round_trips(calendar):
    assert pm.Calendar.parse(calendar.to_text()).periods == calendar.periods
    text = calendar.to_text()
    assert "Notes kept above the table." in text
    assert text.rstrip().endswith("Notes kept below the table.")


def test_a_new_calendar_writes_an_org_table(tmp_path):
    cal = pm.Calendar(pm.fill_year("semesters", 2027))
    path = cal.save(str(tmp_path / "periods.org"))
    text = open(path).read()
    assert "#+NAME: periods" in text
    assert "| Kind     | Name        | Start      | End        | Horizon |" in text
    assert pm.Calendar.from_file(path).periods == cal.periods


def test_a_bad_row_is_reported_not_dropped_silently():
    cal = pm.Calendar.parse(CALENDAR.replace("2027-05-14 | yes", "May 14   | yes"))
    assert len(cal.periods) == 6
    assert any("Spring 2027" in p for p in cal.check())


# -- the current period and the horizons ---------------------------------------
@pytest.mark.parametrize("day,name", [
    (D(2026, 10, 15), "Fall 2026"),
    (D(2026, 12, 18), "Fall 2026"),
    (D(2026, 12, 19), "Spring 2027"),      # the intersession joins spring
    (D(2027, 5, 15), "Summer 2027"),
    (D(2027, 8, 3), "Fall 2027"),
])
def test_the_current_period(calendar, day, name):
    assert calendar.current("semester", day).name == name


def test_before_the_first_period_there_is_none(calendar):
    assert calendar.current("semester", D(2026, 1, 1)) is None
    assert calendar.ahead("semester", D(2026, 1, 1), 5) == [None] * 5


def test_in_a_gap_the_last_period_stays_current():
    cal = pm.Calendar([pm.Period("quarter", "Q1", D(2027, 1, 1), D(2027, 3, 1)),
                       pm.Period("quarter", "Q2", D(2027, 4, 1), D(2027, 6, 30))])
    assert cal.current("quarter", D(2027, 3, 15)).name == "Q1"


def test_the_horizons_ahead(calendar):
    names = [p.name if p else None
             for p in calendar.ahead("semester", D(2026, 10, 15), 5)]
    assert names == ["Fall 2026", "Spring 2027", "Summer 2027", "Fall 2027",
                     "Spring 2028"]
    late = [p.name if p else None
            for p in calendar.ahead("semester", D(2027, 9, 1), 5)]
    assert late == ["Fall 2027", "Spring 2028", "Summer 2028", None, None]


def test_a_period_that_is_not_a_horizon_is_skipped():
    text = CALENDAR.replace("| Summer 2027 | 2027-05-15 | 2027-08-02 | yes",
                            "| Summer 2027 | 2027-05-15 | 2027-08-02 | no ")
    cal = pm.Calendar.parse(text)
    names = [p.name for p in cal.ahead("semester", D(2026, 10, 15), 3)]
    assert names == ["Fall 2026", "Spring 2027", "Fall 2027"]


def test_steps_between(calendar):
    assert calendar.steps_between("semester", "Fall 2026", "Fall 2026") == 0
    assert calendar.steps_between("semester", "Fall 2026", "Spring 2027") == 1
    assert calendar.steps_between("semester", "Fall 2026", "Fall 2027") == 3
    assert calendar.steps_between("semester", "Fall 2026", "Winter 1999") is None


# -- checks ---------------------------------------------------------------------
def test_the_checks_name_each_problem():
    cal = pm.Calendar([
        pm.Period("semester", "A", D(2027, 1, 1), D(2027, 5, 1)),
        pm.Period("semester", "B", D(2027, 4, 1), D(2027, 8, 1)),       # overlaps A
        pm.Period("semester", "C", D(2027, 12, 1), D(2027, 11, 1)),     # backwards
        pm.Period("semester", "A", D(2029, 1, 1), D(2029, 2, 1)),       # twice
    ])
    problems = " | ".join(cal.check())
    assert "A and B overlap" in problems
    assert "C ends before it starts" in problems
    assert "A appears twice" in problems
    assert "days pass between" in problems


# -- templates --------------------------------------------------------------------
@pytest.mark.parametrize("style", [key for key, _label in pm.TEMPLATES])
def test_every_template_is_contiguous_and_clean(style):
    periods = pm.fill_year(style, 2027, first_month=7)
    assert periods
    assert pm.Calendar(periods).check() == []
    for a, b in zip(periods, periods[1:]):
        assert b.start == a.end + dt.timedelta(days=1)


def test_the_semester_template_matches_the_ou_pattern():
    names = [(p.name, p.start, p.end) for p in pm.fill_year("semesters", 2027)]
    assert names == [("Spring 2027", D(2026, 12, 19), D(2027, 5, 14)),
                     ("Summer 2027", D(2027, 5, 15), D(2027, 8, 2)),
                     ("Fall 2027", D(2027, 8, 3), D(2027, 12, 18))]


def test_the_fiscal_year_starts_in_the_chosen_month():
    (fy,) = pm.fill_year("fiscal-year", 2027, first_month=7)
    assert (fy.name, fy.start, fy.end) == ("FY 2027", D(2026, 7, 1), D(2027, 6, 30))
    (cy,) = pm.fill_year("fiscal-year", 2027, first_month=1)
    assert (cy.start, cy.end) == (D(2027, 1, 1), D(2027, 12, 31))


# -- file names and paths ----------------------------------------------------------
@pytest.mark.parametrize("stem,day", [
    ("Oct12", D(2026, 10, 12)), ("sept14", D(2026, 9, 14)),
    ("August31", D(2026, 8, 31)), ("Jan4", D(2027, 1, 4)),
])
def test_a_dated_file_name_gives_the_nearest_date(stem, day):
    assert pm.week_date(stem, D(2026, 10, 15)) == day


def test_a_canonical_name_gives_no_date():
    assert pm.week_date("sEeBgA-sEeAgB", D(2026, 10, 15)) is None
    assert pm.week_date("blank", D(2026, 10, 15)) is None


def test_the_calendar_sits_beside_the_tables(tmp_path):
    table = tmp_path / "Oct12.org"
    assert pm.calendar_path(str(table)) == tmp_path / "periods.org"
    assert pm.calendar_path(str(table), "~/cal.org").name == "cal.org"
    assert pm.archive_path(tmp_path / "periods.org") == tmp_path / "completed.org"


# -- titles ----------------------------------------------------------------------------
def test_titles_name_the_periods(calendar):
    titles = list_titles(calendar.ahead("semester", D(2026, 10, 15), 5))
    assert titles[CURRENT] == "Fall 2026 projects"
    assert titles[COMPLETED] == "Completed in Fall 2026"
    assert titles["next-next-next-semester-projects"] == "Fall 2027 projects"
    assert titles["next-next-next-next-semester-projects"] == "Spring 2028 projects"


def test_titles_fall_back_past_the_calendar(calendar):
    titles = list_titles(calendar.ahead("semester", D(2027, 9, 1), 5))
    assert titles["next-next-next-semester-projects"] == "3*Next semester projects"


# -- the archive -----------------------------------------------------------------------
def test_completed_projects_are_archived_once(tmp_path):
    path = tmp_path / "completed.org"
    assert pm.archive_completed(path, "Fall 2026", ["B: 1006AIrxOpt :safe:",
                                                    "- 0055early"]) == 2
    assert pm.archive_completed(path, "Fall 2026", ["B: 1006AIrxOpt :safe:"]) == 0
    assert pm.archive_completed(path, "Spring 2027", ["X: 0374qflip"]) == 1
    text = path.read_text()
    assert "* Fall 2026\n#+NAME: completed-fall-2026\n| B: 1006AIrxOpt :safe: |" in text
    assert "#+NAME: completed-spring-2027\n| X: 0374qflip |" in text
    assert text.count("1006AIrxOpt") == 1


# -- the lists: period line and roll forward ---------------------------------------------
LISTS_TEXT = """\

#+NAME: current-semester-projects
| A: 1094RNAstrucDetResearchProgram :safe: |
| B: 1006AIrxOpt 2026-12-15 :safe:         |

#+NAME: completed-this-semester
| X: 0374qflip 2026-11-21 :risky: |

#+NAME: next-semester-projects
| - 1452PHFSboXt 2027-03-01 :safe: |

#+NAME: next-next-semester-projects
| Z: 1008ToolsForQCrOfRNA @editing :safe: |

#+NAME: next-next-next-next-semester-projects
| - 2000farIdea |
"""


@pytest.fixture()
def lists():
    return ProjectLists(LISTS_TEXT.splitlines())


def _projects(lists, name):
    return [e.project for e in lists.entries(name)]


def test_the_period_line_is_written_before_the_lists(lists):
    assert lists.period() is None
    assert lists.set_period("Fall 2026")
    assert lists.period() == "Fall 2026"
    assert lists.lines.index("#+PROJECT_PERIOD: Fall 2026") < lists.lines.index(
        "#+NAME: current-semester-projects")
    assert not lists.set_period("Fall 2026")
    assert lists.set_period("Spring 2027")
    assert sum(line.startswith("#+PROJECT_PERIOD") for line in lists.lines) == 1


def test_a_roll_moves_every_list_one_step(lists):
    lists.set_period("Fall 2026")
    result = lists.roll_forward("Spring 2027")
    assert [e.project for e in result.completed] == ["0374qflip"]
    assert [e.project for e in result.carried] == [
        "1094RNAstrucDetResearchProgram", "1006AIrxOpt"]
    assert _projects(lists, COMPLETED) == []
    assert _projects(lists, CARRIED) == ["1094RNAstrucDetResearchProgram", "1006AIrxOpt"]
    assert _projects(lists, CURRENT) == ["1452PHFSboXt"]
    assert _projects(lists, HORIZONS[1]) == ["1008ToolsForQCrOfRNA"]
    assert _projects(lists, HORIZONS[2]) == []
    assert _projects(lists, HORIZONS[3]) == ["2000farIdea"]
    assert _projects(lists, HORIZONS[4]) == []
    assert lists.period() == "Spring 2027"
    # Codes, activities, and risk tags travel with the rows.
    moved = lists.entries(HORIZONS[1])[0]
    assert (moved.code, moved.activity, moved.risk) == ("Z", "editing", "safe")


def test_two_rolls_keep_carried_projects_once(lists):
    lists.roll_forward("Spring 2027")
    lists.roll_forward("Summer 2027")
    assert _projects(lists, CARRIED) == [
        "1094RNAstrucDetResearchProgram", "1006AIrxOpt", "1452PHFSboXt"]
    assert _projects(lists, CURRENT) == ["1008ToolsForQCrOfRNA"]
    assert _projects(lists, HORIZONS[2]) == ["2000farIdea"]


def test_a_rolled_file_still_parses_for_the_scheduler(tmp_path):
    parse_text = pytest.importorskip("writing_schedule").parse_text
    week = ("| Time | M |\n|------+---|\n| 05:00-06:00 | gB |\n|------+---|\n"
            "| B: 1006AIrxOpt |  |\n")
    lines = LISTS_TEXT.splitlines()
    lists = ProjectLists(lines)
    lists.roll_forward("Spring 2027")
    text = week + "\n".join(lines) + "\n"
    assert len(parse_text(text).events) == 1
    path = tmp_path / "week.org"
    path.write_text(text)
    assert _projects(read_lists(str(path)), CARRIED) == [
        "1094RNAstrucDetResearchProgram", "1006AIrxOpt"]


def test_track_sync_counts_carried_projects(tmp_path):
    lines = LISTS_TEXT.splitlines()
    ProjectLists(lines).roll_forward("Spring 2027")
    path = tmp_path / "week.org"
    path.write_text("| Time | M |\n|------+---|\n| 05:00-06:00 | B |\n"
                    + "\n".join(lines) + "\n")
    assert {"1094", "1006", "1452"} <= semester_numbers(str(path))
