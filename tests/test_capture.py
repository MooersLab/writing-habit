"""Quick capture: plain words become a coded grasscatcher task."""

from writing_habit import capture, coach
from writing_habit.capture import Project

from test_coach import fake_model

LEGEND = {"A": "1001grantR01 2026-11-15", "B": "2002reviewArticle 2026-12-01",
          "C": "3003methodsNote", "E": "9001email"}
LISTS = [("F", "5005bookChapter 2026-12-20"), (None, "6006renewalR01 2027-03-05")]


def _projects():
    return capture.projects_from(LEGEND, LISTS)


def test_projects_come_from_the_legend_and_coded_list_entries():
    assert [(p.code, p.name) for p in _projects()] == [
        ("A", "1001grantR01"), ("B", "2002reviewArticle"), ("C", "3003methodsNote"),
        ("E", "9001email"), ("F", "5005bookChapter")]


def test_a_part_of_the_name_finds_the_project():
    got = capture.plain("remember to email the reviewer about figure 3 for the R01, "
                        "priority A", _projects())
    assert (got.code, got.task, got.cookie) == ("A", "Email the reviewer about figure 3 "
                                                     "for the R01", "A")
    assert got.how == "R01 in its name"
    assert got.entry_text().startswith("[#A] Email the reviewer")


def test_the_number_the_code_and_the_whole_name_find_the_project():
    assert capture.plain("check the stats in 3003", _projects()).code == "C"
    assert capture.plain("C: tidy the methods", _projects()).task == "Tidy the methods"
    assert capture.plain("C: tidy the methods", _projects()).how == "its code C"
    assert capture.plain("outline for bookChapter", _projects()).code == "F"
    assert capture.plain("ask Sam about project B", _projects()).code == "B"


def test_no_project_or_a_tie_leaves_the_code_empty():
    assert capture.plain("buy printer toner", _projects()).code is None
    tie = [Project("A", "1001grantR01"), Project("G", "6006renewalR01")]
    got = capture.plain("cite the R01 budget rules", tie)
    assert got.code is None and "both A and G" in got.how


def test_a_cookie_is_read_and_kept_out_of_the_task():
    got = capture.plain("[#B2] reread the comments on the grant R01", _projects())
    assert (got.cookie, got.task) == ("B2", "Reread the comments on the grant R01")
    assert capture.priority("nothing urgent here") is None


def test_a_model_project_named_in_the_words_is_kept():
    reply = {"code": "A", "task": "Email the reviewer about figure 3"}
    plain = capture.plain("email the reviewer about figure 3 for the R01", _projects())
    got = capture.confirm(reply, "email the reviewer about figure 3 for the R01",
                          _projects(), plain)
    assert (got.code, got.task) == ("A", "Email the reviewer about figure 3")


def test_a_model_project_the_words_do_not_name_is_overruled():
    text = "email the reviewer about figure 3 for the R01"
    plain = capture.plain(text, _projects())
    got = capture.confirm({"code": "B", "task": "Email the reviewer"}, text,
                          _projects(), plain)
    assert got.code == "A"
    assert got.how.startswith("the model's project is not named in your words")


def test_a_model_task_with_new_words_or_numbers_is_overruled():
    text = "email the reviewer about figure 3 for the R01"
    plain = capture.plain(text, _projects())
    invented = capture.confirm({"code": "A", "task": "Submit the budget by Friday"},
                               text, _projects(), plain)
    assert invented.task == plain.task
    numbered = capture.confirm({"code": "A", "task": "Email the reviewer about figure 4"},
                               text, _projects(), plain)
    assert numbered.task == plain.task


def test_the_coach_capture_with_and_without_a_model(tmp_path):
    from writing_habit import db
    con = db.connect(str(tmp_path / "habit.db"))
    db.init_db(con)
    text = "remember to email the reviewer about figure 3 for the R01"
    plain = coach.capture_task(None, text, _projects())
    assert plain.data.code == "A" and plain.source.startswith("plain")
    model = coach.Client("tiny", opener=fake_model(
        {"code": "A", "task": "Email the reviewer about figure 3"}))
    answer = coach.capture_task(model, text, _projects(), con=con)
    assert answer.text == "Email the reviewer about figure 3"
    assert answer.source == "local model tiny"
    assert "Captured words: remember to email" in answer.facts
    assert con.execute("SELECT task FROM ai_log").fetchone()[0] == "capture"
    con.close()
