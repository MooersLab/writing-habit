"""The balloon a weekly-table cell shows when the pointer rests on it.

The balloon names the project in full, gives its due date when the key carries
one, and gives its risk class. The due-date reading is Qt-free and runs
everywhere; the balloon text itself needs the model.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")

from writing_habit.gui.weekly_table import WeeklyTable, split_due_date  # noqa: E402

TABLE = (
    "| Time <l>    | M  | Tu | W  | Th |\n"
    "|-------------+----+----+----+----|\n"
    "| Generative: |    |    |    |    |\n"
    "| 04:00-05:30 | A  | C  | F  | Z  |\n"
    "| 05:30-07:00 | G  | W  | E  |    |\n"
    "|-------------+----+----+----+----|\n"
    "| A: 1003molGraphicsR01, Sept 25 :safe: |  |  |  |  |\n"
    "| C: 1452PHFSboXt, September 22 :safe:  |  |  |  |  |\n"
    "| E: email                              |  |  |  |  |\n"
    "| F: 0382CCinJN, 4072UsersMeeting2026 :safe: |  |  |  |  |\n"
    "| G: 0485GUIsc, :safe:                  |  |  |  |  |\n"
    "| W: new idea, 2026-10-01 :risky:       |  |  |  |  |\n"
)


@pytest.mark.parametrize("description, expected", [
    ("1003molGraphicsR01, Sept 25", ("1003molGraphicsR01", "Sept 25")),
    ("1452PHFSboXt, September 22", ("1452PHFSboXt", "September 22")),
    ("1006AIrxOpt, Feb 5", ("1006AIrxOpt", "Feb 5")),
    ("paper, Oct. 3, 2026", ("paper", "Oct. 3, 2026")),
    ("paper, due Nov 1st", ("paper", "Nov 1st")),
    ("paper, 2026-10-01", ("paper", "2026-10-01")),
    ("paper, 10/1", ("paper", "10/1")),
    ("0382CCinJN, 4072UsersMeeting2026", ("0382CCinJN, 4072UsersMeeting2026", None)),
    ("0485GUIsc,", ("0485GUIsc", None)),
    ("0201dusp1 September 18", ("0201dusp1", "September 18")),
    ("0393ReprMGNB before September 30", ("0393ReprMGNB", "September 30")),
    ("0470doeBarat, Ocotober 31", ("0470doeBarat", "Ocotober 31")),
    ("4072UsersMeeting2026 Sep 16, 0382CCinJN, December 31",
     ("4072UsersMeeting2026 Sep 16, 0382CCinJN", "December 31")),
    ("DNPH1 docking", ("DNPH1 docking", None)),
    ("2026words", ("2026words", None)),
    ("Mayfield grant", ("Mayfield grant", None)),
])
def test_split_due_date(description, expected):
    assert split_due_date(description) == expected


def test_project_info_reads_the_key():
    table = WeeklyTable(TABLE)
    assert table.project_info("a") == {
        "code": "A", "name": "1003molGraphicsR01", "due": "Sept 25", "risk": "safe"}
    assert table.project_info("W")["risk"] == "risky"
    assert table.project_info("E")["risk"] is None
    assert table.project_info("Z") is None


@pytest.fixture()
def model():
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    from writing_habit.gui.qt import QtWidgets
    from writing_habit.gui.table_model import WeeklyTableModel
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return WeeklyTableModel(WeeklyTable(TABLE))


def _tip(model, day_column, row=1):
    from writing_habit.gui.qt import Qt
    return model.data(model.index(row, day_column), Qt.ToolTipRole)


def test_balloon_gives_name_due_date_and_risk(model):
    assert _tip(model, 1) == "A: 1003molGraphicsR01\nDue: Sept 25\nRisk: safe"
    assert _tip(model, 2) == "C: 1452PHFSboXt\nDue: September 22\nRisk: safe"


def test_balloon_omits_a_missing_due_date(model):
    assert _tip(model, 3) == "F: 0382CCinJN, 4072UsersMeeting2026\nRisk: safe"
    assert _tip(model, 3, row=2) == "E: email\nRisk: not tagged"


def test_balloon_shows_risky(model):
    assert _tip(model, 2, row=2) == "W: new idea\nDue: 2026-10-01\nRisk: risky"


def test_balloon_flags_a_code_missing_from_the_key(model):
    assert _tip(model, 4) == "Z: not in the key"


def test_blank_cell_and_time_column_have_no_balloon(model):
    assert _tip(model, 4, row=2) is None
    assert _tip(model, 0) is None
