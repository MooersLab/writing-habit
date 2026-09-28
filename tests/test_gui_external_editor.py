"""Opening the weekly table in the editor named by WHGEDITOR.

The lookup needs no Qt. The widget tests replace the launcher, so no editor is
ever started by the suite.
"""

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from writing_habit.gui import external_editor as ee                   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "my-week.org"


def _bashrc(tmp_path, text):
    path = tmp_path / ".bashrc"
    path.write_text(text)
    return path


# -- reading ~/.bashrc ---------------------------------------------------------
@pytest.mark.parametrize("line,expected", [
    ('export WHGEDITOR="emacsclient -n"', "emacsclient -n"),
    ("export WHGEDITOR='code --wait'", "code --wait"),
    ("WHGEDITOR=vim", "vim"),
    ("  export WHGEDITOR=/usr/bin/gedit   # the GNOME one", "/usr/bin/gedit"),
])
def test_the_value_is_read_from_bashrc(tmp_path, line, expected):
    assert ee.read_bashrc_value(_bashrc(tmp_path, f"# start\n{line}\n")) == expected


def test_the_last_assignment_wins(tmp_path):
    path = _bashrc(tmp_path, "export WHGEDITOR=first\nexport WHGEDITOR=second\n")
    assert ee.read_bashrc_value(path) == "second"


def test_a_commented_out_line_is_ignored(tmp_path):
    path = _bashrc(tmp_path, "# export WHGEDITOR=emacs\nexport EDITOR=vi\n")
    assert ee.read_bashrc_value(path) is None


def test_a_similar_name_is_not_taken(tmp_path):
    path = _bashrc(tmp_path, "export MYWHGEDITOR=nano\nexport WHGEDITOR_X=vi\n")
    assert ee.read_bashrc_value(path) is None


def test_home_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = _bashrc(tmp_path, 'export WHGEDITOR="$HOME/bin/ed -x"\n')
    assert ee.read_bashrc_value(path) == f"{tmp_path}/bin/ed -x"


def test_a_missing_bashrc_gives_none(tmp_path):
    assert ee.read_bashrc_value(tmp_path / "absent") is None


def test_an_empty_value_counts_as_none(tmp_path):
    assert ee.read_bashrc_value(_bashrc(tmp_path, "export WHGEDITOR=\n")) is None


# -- choosing the command ------------------------------------------------------
def test_the_environment_comes_first(tmp_path):
    bashrc = _bashrc(tmp_path, "export WHGEDITOR=from-bashrc\n")
    argv, source = ee.editor_command("/t.org", {"WHGEDITOR": "from-env"}, bashrc)
    assert argv[-1] == "/t.org" and argv[0].endswith("from-env")
    assert source == "the environment"


def test_bashrc_is_used_when_the_environment_is_silent(tmp_path):
    bashrc = _bashrc(tmp_path, 'export WHGEDITOR="myeditor --flag"\n')
    argv, source = ee.editor_command("/t.org", {}, bashrc)
    assert argv[0].endswith("myeditor")
    assert argv[1:] == ["--flag", "/t.org"]
    assert source == str(bashrc)


@pytest.mark.parametrize("platform,expected", [
    ("darwin", ["open", "-t", "/t.org"]),
    ("linux", ["xdg-open", "/t.org"]),
    ("win32", []),
])
def test_the_system_default_when_nothing_is_named(tmp_path, platform, expected):
    argv, source = ee.editor_command("/t.org", {}, tmp_path / "none", platform)
    assert argv == expected
    assert source == "the system default"


def test_a_program_on_path_is_resolved(tmp_path, monkeypatch):
    program = tmp_path / "fake-editor"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    argv, _source = ee.editor_command("/t.org", {"WHGEDITOR": "fake-editor"},
                                      tmp_path / "none")
    assert argv[0] == str(program)


def test_open_in_editor_starts_the_command(tmp_path, monkeypatch):
    started = []

    class FakePopen:
        def __init__(self, argv, **kwargs):
            started.append((argv, kwargs))

    monkeypatch.setattr(ee.subprocess, "Popen", FakePopen)
    argv, _source = ee.open_in_editor("/t.org", {"WHGEDITOR": "ed"},
                                      tmp_path / "none")
    assert started[0][0] == argv
    assert started[0][1]["start_new_session"] is True


# -- the button ----------------------------------------------------------------
@pytest.fixture()
def editor(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    pytest.importorskip("writing_schedule", reason="the weekly table needs it")
    store = {}
    monkeypatch.setattr("writing_habit.gui.settings.get",
                        lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    from writing_habit.gui.schedule_editor import ScheduleEditor
    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    widget.launched = []

    def launch(path):
        widget.launched.append((path, Path(path).read_text()))
        return ["fake-editor", path], "the test"

    widget.launch_editor = launch
    return widget


def _open_copy(editor, tmp_path):
    copy = tmp_path / "my-week.org"
    shutil.copy(EXAMPLE, copy)
    editor.open(str(copy))
    return copy


def test_the_button_waits_for_a_file(editor, tmp_path):
    assert not editor.external_button.isEnabled()
    _open_copy(editor, tmp_path)
    assert editor.external_button.isEnabled()


def test_a_scaffolded_table_has_no_file_to_open(editor):
    editor.scaffold(projects=2)
    assert not editor.external_button.isEnabled()
    assert editor.open_externally() is None
    assert editor.launched == []


def test_a_clean_table_opens_at_once(editor, tmp_path):
    copy = _open_copy(editor, tmp_path)
    argv = editor.open_externally()
    assert argv == ["fake-editor", str(copy)]
    assert editor.launched[0][0] == str(copy)


def test_save_and_open_writes_the_edits_first(editor, tmp_path, monkeypatch):
    copy = _open_copy(editor, tmp_path)
    editor.table.set_cell(editor.table.block_rows[0], 6, "B")
    monkeypatch.setattr(editor, "_ask_save_before_editing", lambda: "save")
    editor.open_externally()
    assert editor.table.dirty is False
    assert editor.launched[0][1] == copy.read_text()
    assert "| B  |" in editor.launched[0][1].splitlines()[5]


def test_open_the_saved_version_keeps_the_edits_in_the_grid(editor, tmp_path,
                                                            monkeypatch):
    copy = _open_copy(editor, tmp_path)
    on_disk = copy.read_text()
    editor.table.set_cell(editor.table.block_rows[0], 6, "B")
    monkeypatch.setattr(editor, "_ask_save_before_editing", lambda: "saved")
    editor.open_externally()
    assert editor.table.dirty is True
    assert editor.launched[0][1] == on_disk


def test_cancel_opens_nothing(editor, tmp_path, monkeypatch):
    _open_copy(editor, tmp_path)
    editor.table.set_cell(editor.table.block_rows[0], 6, "B")
    monkeypatch.setattr(editor, "_ask_save_before_editing", lambda: "cancel")
    assert editor.open_externally() is None
    assert editor.launched == []


def test_a_missing_program_is_reported(editor, tmp_path, monkeypatch):
    _open_copy(editor, tmp_path)
    warned = []
    monkeypatch.setattr("writing_habit.gui.qt.QtWidgets.QMessageBox.warning",
                        lambda *args: warned.append(args[-1]))

    def boom(path):
        raise FileNotFoundError("no such program: emacsclient")

    editor.launch_editor = boom
    assert editor.open_externally() is None
    assert warned and "WHGEDITOR" in warned[0]


def test_reload_picks_up_an_external_change(editor, tmp_path):
    copy = _open_copy(editor, tmp_path)
    editor.open_externally()
    copy.write_text(copy.read_text().replace("| 04:00-05:30 ", "| 04:15-05:30 "))
    editor.reload()
    first = editor.table.block_rows[0]
    assert editor.table.rows[first].parsed == ("04:15", "05:30")
