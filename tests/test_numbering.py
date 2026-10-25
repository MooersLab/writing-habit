"""Project numbering help: free numbers near related projects, and projects forming."""

from writing_habit import coach, numbering

from test_coach import fake_model

NAMES = ("0131RETKinase2018BrP 0132RETKinase2019JBC 0139RETprotac "
         "0140RETactivationLoopDeletions 0141RETkinaseMutants "
         "0142RETKinaseCovalentInhibitors 0149RETKinaseDocking 0200DUSP1review "
         "0201DUSP1radiation 0378QCrPluginPyMOL 0379pymolSceneManager "
         "0385PyMOLWhisper 0403PyMOLRStudio 0404PYMOLColab 1001grantR01").split()
KNOWN = numbering.known_projects(NAMES)


def test_names_split_into_words():
    assert numbering.words("0142RETKinaseCovalentInhibitors") == [
        "ret", "kinase", "covalent", "inhibitors"]
    assert numbering.words("0378QCrPluginPyMOL") == ["qcr", "plugin", "pymol"]
    assert numbering.camel("RET kinase PROTAC degraders") == "RETKinasePROTACDegraders"


def test_a_rare_shared_word_finds_the_closest_project():
    s = numbering.suggest("RET kinase PROTAC degraders", KNOWN)
    assert [n for n, _o, _w in s.related] == ["0139"]
    assert s.numbers == ["0143", "0144", "0145"]
    assert s.reason == "1 project shares ret, protac with the new name"


def test_free_numbers_inside_the_range_come_first():
    s = numbering.suggest("RET kinase review 2026", KNOWN)
    assert {n for n, _o, _w in s.related} >= {"0131", "0141", "0149"}
    assert s.numbers[0] in {"0143", "0144", "0145", "0146", "0147", "0148"}
    assert all(n not in KNOWN for n in s.numbers)


def test_spelling_of_pymol_does_not_matter():
    s = numbering.suggest("PyMOL in Positron", KNOWN)
    assert {n for n, _o, _w in s.related} == {"0378", "0379", "0385", "0403", "0404"}


def test_no_related_project_follows_the_active_projects():
    s = numbering.suggest("Seeded direct methods", KNOWN, active=["0142", "1001"])
    assert s.related == [] and s.numbers == ["1002", "1003", "1004"]
    assert "follows the highest number of this week's projects" in s.reason


def test_project_folders_are_read_and_nothing_else(tmp_path):
    for name in ("0142RETKinase", "0200DUSP1review", "notes", "2026words"):
        (tmp_path / name).mkdir()
    (tmp_path / "0300file.txt").write_text("x")
    assert numbering.folder_projects(tmp_path) == {
        "0142": "0142RETKinase", "0200": "0200DUSP1review", "2026": "2026words"}
    assert numbering.folder_projects(tmp_path / "missing") == {}


def test_a_project_forming_inside_another():
    tasks = {"A": ["Outline the PROTAC linker study", "Order PROTAC compounds",
                   "Email Sam about PROTAC assays", "Fix figure 2"],
             "B": ["Draft aim 2", "Draft aim 3"]}
    found = numbering.forming(tasks, {"A": "0142RETKinaseCovalentInhibitors",
                                      "B": "1001grantR01"})
    assert [(f.code, f.word, len(f.tasks)) for f in found] == [("A", "protac", 3)]
    assert found[0].sentence().startswith(
        "3 tasks of A 0142RETKinaseCovalentInhibitors mention “protac”")
    # A word the project's own name holds is not a new project.
    assert numbering.forming({"A": ["Read the RET paper", "Check the RET table",
                                    "Edit the RET methods"]},
                             {"A": "0142RETKinase"}) == []


def test_the_plain_note_and_the_coach_wording():
    s = numbering.suggest("RET kinase PROTAC degraders", KNOWN)
    assert numbering.plain(s, []).startswith(
        "0143 is free and sits with the related projects 0139RETprotac")
    reply = "Use 0143, beside 0139RETprotac, so the PROTAC work stays together."
    answer = coach.number_project(coach.Client("tiny", opener=fake_model(reply)), s)
    assert answer.data["note"] == reply
    bad = coach.number_project(coach.Client("tiny", opener=fake_model("Use 0500.")), s)
    assert bad.data["note"] == numbering.plain(s, [])


def test_line_names_the_number_and_the_neighbors():
    s = numbering.suggest("RET kinase PROTAC degraders", KNOWN)
    assert s.line("0143") == "Use 0143RETKinasePROTACDegraders, near 0139"
