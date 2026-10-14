"""The legend description as a project name and a YYYY-MM-DD deadline."""

from datetime import date

import pytest

from writing_habit import name

OCT5 = date(2026, 10, 5)


@pytest.mark.parametrize("text, expected", [
    ("1008ToolsForQCrOfRNA 2026-10-05", ("1008ToolsForQCrOfRNA", "2026-10-05")),
    ("0201dusp1, 2026-11-01", ("0201dusp1", "2026-11-01")),
    ("0374qflip", ("0374qflip", None)),
    ("0201dusp1 November 1", ("0201dusp1 November 1", None)),
    ("", ("", None)),
])
def test_split_deadline(text, expected):
    assert name.split_deadline(text) == expected


def test_join_is_the_inverse_of_split():
    for project, deadline in [("0374qflip", None), ("0201dusp1", "2026-11-01")]:
        assert name.split_deadline(name.join_deadline(project, deadline)) == (project, deadline)


@pytest.mark.parametrize("text, ok", [
    ("", True), ("2026-11-15", True), ("2026-02-30", False), ("Nov 15", False),
    ("2026-1-5", False),
])
def test_valid_deadline(text, ok):
    assert name.valid_deadline(text) is ok


@pytest.mark.parametrize("text, expected", [
    ("1006AIrxOpt, NSF Dec 15", ("1006AIrxOpt", "2026-12-15", "NSF")),
    ("1452PHFSboXt, March 1", ("1452PHFSboXt", "2027-03-01", "")),
    ("0211dnph1 Submitted October 1", ("0211dnph1", None, "Submitted October 1")),
    ("4072UsersMeeting2026 Sep 16, 0382CCinJN, December 31",
     ("4072UsersMeeting2026, 0382CCinJN", "2026-12-31", "Sep 16")),
    ("0393ReprMGNB before October 8", ("0393ReprMGNB", "2026-10-08", "")),
    ("0470doeBarat, Ocotober 31", ("0470doeBarat", "2026-10-31", "")),
    ("0437mpDOE, part of grant 1008, hold back",
     ("0437mpDOE", None, "part of grant 1008, hold back")),
    ("2026words", ("2026words", None, "")),
    ("email, Sept 25", ("email", "2026-09-25", "")),
    ("0201dusp1 2026-11-01", ("0201dusp1", "2026-11-01", "")),
])
def test_tidy_description(text, expected):
    assert name.tidy_description(text, OCT5) == expected


def test_tidy_keeps_the_sync_reading_project_numbers():
    project, _deadline, _dropped = name.tidy_description(
        "4072UsersMeeting2026 Sep 16, 0382CCinJN, December 31", OCT5)
    assert "4072" in project and "0382" in project
