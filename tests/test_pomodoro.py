"""The Pomodoro timer: the cycle from the block, the clock, sounds, settings, hotkeys."""

import datetime as dt
import json
import os
import wave
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5", reason="the graphical extra is not installed")

from writing_habit.gui import pomodoro as pm                             # noqa: E402
from writing_habit.gui.pomodoro import (LONG, SHORT, WORK, PomodoroClock,  # noqa: E402
                                        PomodoroSettings, build_cycle, fit_in_block)


def _block(start, end):
    return SimpleNamespace(start=start, end=end, letter="A")


# -- the cycle --------------------------------------------------------------------
@pytest.mark.parametrize("minutes,count", [(120, 4), (115, 4), (114, 3), (90, 3),
                                           (60, 2), (55, 2), (45, 1), (30, 1), (15, 1)])
def test_the_block_sets_the_pomodoros_per_cycle(minutes, count):
    assert fit_in_block(minutes, 25, 5) == count


def test_no_block_gives_the_default_and_other_timings_count():
    assert fit_in_block(None, 25, 5) == 4
    assert fit_in_block(120, 50, 10) == 2
    assert pm.block_minutes(_block("23:00", "01:00")) == 120


def test_a_fixed_number_overrides_the_block():
    options = PomodoroSettings(auto_cycle=False, per_cycle=6)
    assert pm.cycle_length(options, _block("05:00", "07:00")) == 6
    assert pm.cycle_length(PomodoroSettings(), _block("05:00", "06:30")) == 3


def test_a_cycle_alternates_and_ends_with_the_long_break():
    phases = build_cycle(PomodoroSettings(), 3)
    assert [(p.kind, p.minutes) for p in phases] == [
        (WORK, 25), (SHORT, 5), (WORK, 25), (SHORT, 5), (WORK, 25), (LONG, 15)]


# -- the clock --------------------------------------------------------------------
def test_the_clock_runs_a_cycle_by_itself():
    clock = PomodoroClock(PomodoroSettings())
    clock.start(0, _block("05:00", "06:00"))             # two Pomodoros
    assert clock.count == 2 and clock.text(0) == "Pomodoro 1/2  25:00"
    assert clock.text(61.5) == "Pomodoro 1/2  23:59"
    assert clock.poll(1499) is None
    assert clock.poll(1500).kind == WORK
    assert clock.text(1500) == "Short break  05:00"
    # A late read does not stretch the cycle: the break began at 1500.
    assert clock.poll(1830).kind == SHORT and clock.text(1830) == "Pomodoro 2/2  24:30"
    assert clock.poll(1800 + 1500).kind == WORK
    assert clock.phase.kind == LONG
    assert clock.poll(3300 + 900).kind == LONG
    assert clock.state == "done" and clock.completed == 2
    assert clock.text(4200) == "Cycle done, 2 Pomodoros"


def test_pause_resume_and_stop():
    clock = PomodoroClock(PomodoroSettings())
    clock.start(0)
    clock.pause(600)
    assert clock.state == "paused" and clock.text(5000) == "Pomodoro 1/4  15:00 paused"
    assert clock.poll(5000) is None
    clock.start(5000)
    assert clock.remaining(5100) == 800
    clock.stop()
    assert clock.state == "idle" and clock.text(0) == "Pomodoro"


def test_without_automatic_starts_the_next_phase_waits():
    clock = PomodoroClock(PomodoroSettings(auto_next=False))
    clock.start(0)
    clock.poll(1500)
    assert clock.state == "waiting" and clock.text(9999) == "Short break ready. Press Start"
    clock.start(2000)
    assert clock.text(2000) == "Short break  05:00"


# -- settings ---------------------------------------------------------------------
@pytest.fixture()
def store(monkeypatch, tmp_path):
    # Point the daily record at a folder that does not exist, so no test can
    # write to the real mytime.db. The tests that record set their own folder.
    values = {"pomodoro": json.dumps({"db_dir": str(tmp_path / "no-database-here")})}
    monkeypatch.setattr("writing_habit.gui.settings.get", lambda key: values.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: values.__setitem__(key, value))
    return values


def test_settings_round_trip_and_ignore_bad_values(store):
    store.clear()
    assert PomodoroSettings.load() == PomodoroSettings()
    PomodoroSettings(pomodoro=50, tick=False, start_key="Ctrl+Alt+P").save()
    loaded = PomodoroSettings.load()
    assert (loaded.pomodoro, loaded.tick, loaded.start_key) == (50, False, "Ctrl+Alt+P")
    store["pomodoro"] = json.dumps({"pomodoro": "lots", "unknown": 1, "long_break": 20})
    assert PomodoroSettings.load() == PomodoroSettings(long_break=20)
    store["pomodoro"] = "not json"
    assert PomodoroSettings.load() == PomodoroSettings()


# -- sounds -----------------------------------------------------------------------
def test_the_sounds_are_written_once(tmp_path):
    paths = pm.sound_files(tmp_path)
    for name in ("tick", "buzzer"):
        with wave.open(str(paths[name])) as w:
            seconds = w.getnframes() / w.getframerate()
        assert (seconds < 0.1) if name == "tick" else (1.0 < seconds < 2.0)
    stamp = paths["tick"].stat().st_mtime_ns
    pm.sound_files(tmp_path)
    assert paths["tick"].stat().st_mtime_ns == stamp


# -- the widget -------------------------------------------------------------------
@pytest.fixture()
def timer(qtbot, store):
    block = {"value": _block("05:00", "07:00")}
    widget = pm.PomodoroTimer(lambda: block["value"])
    qtbot.addWidget(widget)
    widget.clock_now = 0.0
    widget.now = lambda: widget.clock_now
    widget.sounds = []
    widget.play = lambda name, volume: widget.sounds.append((name, volume))
    widget.lines = []
    widget.logged.connect(widget.lines.append)
    widget.block_ref = block
    return widget


def test_the_widget_ticks_and_buzzes(timer):
    timer.start()
    assert timer.display.text() == "Pomodoro 1/4  25:00"
    assert timer.lines == ["Pomodoro cycle of 4 started"]
    timer.sounds.clear()
    timer.clock_now = 1.0
    timer.update_state()
    assert timer.sounds == [("tick", 30)]
    timer.clock_now = 1500.0
    timer.update_state()
    assert timer.sounds[-1] == ("buzzer", 80)
    assert timer.lines[-1] == "Pomodoro 1/4 ended. Short break started"
    timer.sounds.clear()
    timer.clock_now = 1501.0
    timer.update_state()
    assert timer.sounds == []                       # no ticking in a break
    assert "Short break" in timer.display.text()


def test_the_sounds_can_be_turned_off(timer):
    timer.apply_settings(PomodoroSettings(tick=False, buzzer=False))
    timer.start()
    timer.clock_now = 1500.0
    timer.update_state()
    assert timer.sounds == []


def test_the_button_pauses_and_resumes_and_stop_resets(timer):
    timer.display.click()
    timer.clock_now = 60.0
    timer.display.click()
    assert timer.clock.state == "paused" and timer.display.text().endswith("paused")
    timer.clock_now = 600.0
    timer.start_button.click()
    assert timer.display.text() == "Pomodoro 1/4  24:00"
    timer.stop_button.click()
    assert timer.display.text() == "Pomodoro" and not timer.stop_button.isEnabled()
    assert timer.lines[-1] == "Pomodoro stopped after 0 Pomodoros"


def test_a_new_cycle_starts_when_the_long_break_ends_in_a_block(timer):
    timer.block_ref["value"] = _block("05:00", "06:00")
    timer.start()
    for now in (1500, 1800, 3300, 4200):
        timer.clock_now = float(now)
        timer.update_state()
    assert timer.lines[-1] == "Pomodoro cycle done: 2 Pomodoros. Next cycle of 2 started"
    assert timer.clock.state == "running"
    timer.block_ref["value"] = None
    for now in (5700, 6000, 7500, 8400):
        timer.clock_now = float(now)
        timer.update_state()
    assert timer.clock.state == "done" and timer.display.text() == "Cycle done, 2 Pomodoros"


def test_the_hotkeys_start_and_stop(timer, qtbot):
    host = pm.QtWidgets.QWidget()
    qtbot.addWidget(host)
    timer.install_hotkeys(host)
    keys = [s.key().toString() for s in timer._shortcuts]
    assert keys == [pm.QtGui.QKeySequence("Meta+Ctrl+P").toString(),
                    pm.QtGui.QKeySequence("Meta+Ctrl+S").toString()]
    assert all(s.context() == pm.Qt.ApplicationShortcut for s in timer._shortcuts)
    timer._shortcuts[0].activated.emit()
    assert timer.clock.state == "running"
    timer._shortcuts[1].activated.emit()
    assert timer.clock.state == "idle"
    timer.apply_settings(PomodoroSettings(start_key="Ctrl+Alt+P", stop_key=""))
    assert [s.key().toString() for s in timer._shortcuts] == [
        pm.QtGui.QKeySequence("Ctrl+Alt+P").toString()]


def test_the_settings_dialog_matches_the_tabs_and_reads_back(timer):
    dialog = timer.open_settings(run=False)
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        "General", "Timing", "Notifications", "Hotkeys", "Database"]
    assert dialog.auto_cycle_box.text() == "From the time block (4 for 120 min)"
    assert not dialog.per_cycle_spin.isEnabled() and dialog.per_cycle_spin.value() == 4
    dialog.pomodoro_spin.setValue(50)
    dialog.short_spin.setValue(10)
    assert dialog.auto_cycle_box.text() == "From the time block (2 for 120 min)"
    assert dialog.per_cycle_spin.value() == 2
    assert dialog.result_settings().per_cycle == 4         # the fixed number is kept
    dialog.auto_cycle_box.setChecked(False)
    assert dialog.per_cycle_spin.value() == 4 and dialog.per_cycle_spin.isEnabled()
    dialog.per_cycle_spin.setValue(5)
    dialog.auto_next_box.setChecked(False)
    result = dialog.result_settings()
    assert (result.pomodoro, result.short_break, result.per_cycle, result.auto_cycle,
            result.auto_next, result.start_key) == (50, 10, 5, False, False,
                                                     PomodoroSettings().start_key)
    tests = []
    dialog.test_requested.connect(lambda name, volume: tests.append(name))
    dialog.show_settings(PomodoroSettings())
    assert dialog.result_settings() == PomodoroSettings()


# -- in the schedule editor ------------------------------------------------------------
WEEK = (
    "|        Time | M  | Tu |\n"
    "|-------------+----+----|\n"
    "| 05:00-06:30 | gA |    |\n"
    "| 07:00-08:00 | eB |    |\n"
    "|-------------+----+----|\n"
    "| A: one 2026-11-01 :safe: |  |  |\n"
    "| B: two 2026-12-01 :safe: |  |  |\n"
)


def test_the_editor_uses_the_live_block_then_the_selected_one(qtbot, tmp_path, store):
    pytest.importorskip("writing_schedule", reason="the weekly table needs writing-schedule")
    from writing_habit.gui.schedule_editor import ScheduleEditor
    editor = ScheduleEditor()
    qtbot.addWidget(editor)
    path = tmp_path / "Oct12.org"
    path.write_text(WEEK, encoding="utf-8")
    editor.open(str(path))
    editor.set_hour_view(True)
    assert editor.pomodoro.parent() is editor
    editor.block_timer.now = lambda: dt.datetime(2026, 10, 12, 5, 30)
    assert editor.pomodoro_block().letter == "A"
    editor.pomodoro.play = lambda *a: None
    editor.pomodoro.start()
    assert editor.pomodoro.clock.count == 3                    # 90 minutes
    editor.pomodoro.stop()
    editor.block_timer.now = lambda: dt.datetime(2026, 10, 12, 12, 0)
    editor.hour_view.setCurrentIndex(editor.hour_model.index(7, 1))
    assert editor.pomodoro_block().letter == "B"
    editor.pomodoro.start()
    assert editor.pomodoro.clock.count == 2                    # 60 minutes


# -- today's count ----------------------------------------------------------------
def test_finished_pomodoros_count_for_the_day(timer, store):
    day = {"value": dt.date(2026, 10, 21)}
    timer.today = lambda: day["value"]
    timer.update_state()
    assert timer.today_label.text() == " Today: 0"
    timer.start()
    timer.clock_now = 1500.0                 # the first Pomodoro ends
    timer.update_state()
    timer.clock_now = 1800.0                 # the short break ends, which does not count
    timer.update_state()
    assert timer.today_label.text() == " Today: 1"
    timer.stop()                             # a Pomodoro cut short does not count
    timer.start()
    timer.clock_now = 3300.0
    timer.update_state()
    assert timer.today_label.text() == " Today: 2"
    assert json.loads(store["pomodoro_today"]) == {"date": "2026-10-21", "count": 2}


def test_the_count_survives_a_restart_and_starts_over_the_next_day(qtbot, store):
    store["pomodoro_today"] = json.dumps({"date": "2026-10-21", "count": 5})
    assert pm.today_count(dt.date(2026, 10, 21)) == 5
    widget = pm.PomodoroTimer()
    qtbot.addWidget(widget)
    widget.today = lambda: dt.date(2026, 10, 21)
    widget.update_state()
    assert widget.today_label.text() == " Today: 5"
    widget.today = lambda: dt.date(2026, 10, 22)
    widget.update_state()
    assert widget.today_label.text() == " Today: 0"
    assert pm.add_to_today(dt.date(2026, 10, 22)) == 1
    store["pomodoro_today"] = "garbage"
    assert pm.today_count(dt.date(2026, 10, 22)) == 0


# -- the daily record in a database ---------------------------------------------------
def test_record_adds_one_row_per_day_and_updates_it(tmp_path):
    from writing_habit import pom_count
    path = tmp_path / "mytime.db"
    assert pom_count.record(path, "zzPomCount", dt.date(2026, 10, 21), 6,
                            dt.datetime(2026, 10, 21, 23, 59)) == "added"
    assert pom_count.record(path, "zzPomCount", dt.date(2026, 10, 21), 7) == "updated"
    pom_count.record(path, "zzPomCount", dt.date(2026, 10, 22), 0)
    assert pom_count.rows(path, "zzPomCount") == [("2026-10-21", 7), ("2026-10-22", 0)]


def test_record_refuses_a_bad_table_or_folder(tmp_path):
    from writing_habit import pom_count
    with pytest.raises(ValueError):
        pom_count.record(tmp_path / "m.db", "zz; DROP TABLE x", dt.date(2026, 10, 21), 1)
    with pytest.raises(FileNotFoundError):
        pom_count.record(tmp_path / "nowhere" / "m.db", "zzPomCount", dt.date(2026, 10, 21), 1)
    assert pom_count.database_path("~/x", "") == pm.Path("~/x/mytime.db").expanduser()


ZTIMESPENT = """CREATE TABLE "zTimeSpent" (
  "id" INTEGER NOT NULL,
  "DateDashed" Date,
  "Start" TIME,
  "End" TIME,
  "TimeClock" TIME GENERATED ALWAYS AS (strftime('%H:%M', CAST((julianday("End") - julianday("Start")) AS REAL), '12:00')) VIRTUAL,
  "TimeHr" TIME GENERATED ALWAYS AS (ROUND((julianday("End") - julianday("Start")) * 24, 2)) VIRTUAL,
  "ProjectID" INT,
  "ProjectDirectory" TEXT,
  "Description" TEXT,
  "Activity" TEXT DEFAULT none,
  PRIMARY KEY("id")
)"""


def _time_db(path):
    import sqlite3
    con = sqlite3.connect(str(path))
    con.execute(ZTIMESPENT)
    con.execute('INSERT INTO zTimeSpent (id, DateDashed, Start, "End", ProjectID) '
                "VALUES (1, '2026-10-21', '05:30', '07:00', 142)")
    con.commit()
    return con


def test_the_time_tracker_table_is_never_touched(tmp_path):
    from writing_habit import pom_count
    path = tmp_path / "mytime.db"
    con = _time_db(path)
    before = con.execute("SELECT sql FROM sqlite_master WHERE name = 'zTimeSpent'"
                         ).fetchone()[0]
    con.close()
    pom_count.record(path, "zzPomCount", dt.date(2026, 10, 21), 6)
    for name in ("zTimeSpent", "ztimespent", "ZTIMESPENT"):
        with pytest.raises(ValueError, match="time tracker's own table"):
            pom_count.record(path, name, dt.date(2026, 10, 21), 6)
    import sqlite3
    con = sqlite3.connect(str(path))
    after = con.execute("SELECT sql FROM sqlite_master WHERE name = 'zTimeSpent'"
                        ).fetchone()[0]
    clock, hours = con.execute("SELECT TimeClock, TimeHr FROM zTimeSpent").fetchone()
    con.close()
    assert after == before
    assert (clock, hours) == ("01:30", 1.5)


def test_a_table_of_another_shape_is_refused_and_left_alone(tmp_path):
    import sqlite3
    from writing_habit import pom_count
    path = tmp_path / "mytime.db"
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE zProjects (id INTEGER PRIMARY KEY, name TEXT)")
    con.commit()
    con.close()
    with pytest.raises(ValueError, match="not a Pomodoro count table"):
        pom_count.record(path, "zProjects", dt.date(2026, 10, 21), 3)
    con = sqlite3.connect(str(path))
    assert [r[1] for r in con.execute("PRAGMA table_info(zProjects)")] == ["id", "name"]
    con.close()


def test_the_next_record_time_is_tonight_or_tomorrow_night():
    assert pm.next_record_time(dt.datetime(2026, 10, 21, 19, 0)) == dt.datetime(2026, 10, 21, 23, 59)
    assert pm.next_record_time(dt.datetime(2026, 10, 21, 23, 59, 30)) == \
        dt.datetime(2026, 10, 22, 23, 59)


@pytest.fixture()
def recording(timer, tmp_path):
    from writing_habit import pom_count
    timer.apply_settings(PomodoroSettings(db_dir=str(tmp_path)))
    day = {"value": dt.date(2026, 10, 21)}
    timer.today = lambda: day["value"]
    timer.wall = lambda: dt.datetime.combine(day["value"], dt.time(23, 59))
    timer.day = day
    timer.rows = lambda: pom_count.rows(tmp_path / "mytime.db", "zzPomCount")
    return timer


def _finish_one(timer):
    timer.start()
    timer.clock_now += 1500.0
    timer.update_state()
    timer.stop()


def test_eleven_fifty_nine_writes_the_day(recording):
    _finish_one(recording)
    _finish_one(recording)
    recording.schedule_record()
    assert recording._record_target == dt.date(2026, 10, 22)   # 23:59 itself is past
    recording._record_target = dt.date(2026, 10, 21)
    recording._record_tonight()
    assert recording.rows() == [("2026-10-21", 2)]
    assert recording.lines[-1].startswith("Recorded 2 Pomodoros for 2026-10-21 in zzPomCount")
    assert recording.catch_up() is None                        # nothing left to write


def test_a_missed_night_is_written_the_next_day(recording):
    _finish_one(recording)
    recording.day["value"] = dt.date(2026, 10, 22)             # the app was closed at 23:59
    assert recording.catch_up() == "added"
    assert recording.rows() == [("2026-10-21", 1)]


def test_a_late_pomodoro_updates_the_row_before_the_new_day_starts(recording):
    _finish_one(recording)
    recording._record_target = dt.date(2026, 10, 21)
    recording._record_tonight()
    _finish_one(recording)                                     # ends at 23:59:40
    recording.day["value"] = dt.date(2026, 10, 22)
    _finish_one(recording)                                     # the first of the new day
    assert recording.rows() == [("2026-10-21", 2)]
    assert pm.today_count(dt.date(2026, 10, 22)) == 1


def test_a_late_timer_after_sleep_does_not_overwrite(recording):
    _finish_one(recording)
    recording._record_target = dt.date(2026, 10, 21)
    recording.day["value"] = dt.date(2026, 10, 22)            # woke the next morning
    recording._record_tonight()
    assert recording.rows() == [("2026-10-21", 1)]


def test_recording_can_be_turned_off_and_reports_errors(timer, tmp_path):
    timer.apply_settings(PomodoroSettings(record_db=False, db_dir=str(tmp_path)))
    assert timer.record_day(dt.date(2026, 10, 21), 3) is None
    assert not (tmp_path / "mytime.db").exists()
    timer.apply_settings(PomodoroSettings(db_dir=str(tmp_path / "missing")))
    assert timer.record_day(dt.date(2026, 10, 21), 3) is None
    assert timer.lines[-1].startswith("Could not record the Pomodoro count for 2026-10-21")


def test_the_database_tab_edits_the_path_and_records_now(timer, tmp_path):
    from writing_habit import pom_count
    dialog = timer.open_settings(run=False)
    assert dialog.tabs.tabText(4) == "Database"
    assert dialog.db_table_edit.text() == "zzPomCount"
    assert dialog.db_file_edit.text() == "mytime.db"
    assert PomodoroSettings().db_dir == "~/6003TimeTracking/cb"
    dialog.db_dir_edit.setText(str(tmp_path))
    dialog.db_table_edit.setText("zzPoms")
    assert dialog.db_path_label.text() == f"zzPoms in {tmp_path / 'mytime.db'}"
    timer.today = lambda: dt.date(2026, 10, 21)
    dialog.record_requested.emit()
    assert dialog.db_status.text() == "Added today's row in zzPoms"
    assert pom_count.rows(tmp_path / "mytime.db", "zzPoms") == [("2026-10-21", 0)]
    result = dialog.result_settings()
    assert (result.db_dir, result.db_table) == (str(tmp_path), "zzPoms")
    assert timer.options.db_table == "zzPomCount"           # nothing saved before OK
    dialog.db_table_edit.setText("bad name")
    assert dialog.db_path_label.text().endswith("letters, digits, and _)")


# -- custom sound files ---------------------------------------------------------------
def test_a_custom_file_is_chosen_and_a_missing_one_falls_back(tmp_path):
    built_in = pm.sound_files(tmp_path / "built-in")
    mine = tmp_path / "bell.wav"
    mine.write_bytes(built_in["buzzer"].read_bytes())
    assert pm.choose_sound("buzzer", str(mine), built_in) == (mine, "")
    assert pm.choose_sound("tick", "", built_in) == (built_in["tick"], "")
    path, note = pm.choose_sound("tick", str(tmp_path / "gone.wav"), built_in)
    assert path == built_in["tick"] and note.endswith("not found, so the built-in tick plays")


def test_the_player_uses_the_files_and_explains_what_it_cannot_play(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "sound_effect_class", lambda: None)
    mine = tmp_path / "bell.wav"
    pm._write_wave(mine, pm.buzzer_samples())
    song = tmp_path / "gong.mp3"
    song.write_bytes(b"ID3")
    player = pm.SoundPlayer(None, {"buzzer": str(mine)})
    assert player.paths["buzzer"] == mine and player.paths["tick"] == player.built_in["tick"]
    player.afplay = None
    player.files = {}
    player.set_files({"buzzer": str(song)})
    assert player.paths["buzzer"] == player.built_in["buzzer"]
    assert "not a WAV file" in player.notes["buzzer"]
    player.afplay = "/usr/bin/afplay"
    player.files = {}
    player.set_files({"buzzer": str(song)})
    assert player.paths["buzzer"] == song and player.means("buzzer") == "afplay"
    calls = []
    monkeypatch.setattr(pm.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
    player.play("buzzer", 50)
    assert calls == [["/usr/bin/afplay", "-v", "0.50", str(song)]]


def test_the_settings_keep_the_files_and_the_dialog_edits_them(timer, tmp_path):
    mine = tmp_path / "tick.wav"
    pm._write_wave(mine, pm.tick_samples())
    timer.apply_settings(PomodoroSettings(tick_file=str(mine)))
    assert PomodoroSettings.load().tick_file == str(mine)
    dialog = timer.open_settings(run=False)
    assert dialog.tick_file_edit.text() == str(mine)
    assert dialog.buzzer_file_edit.text() == ""
    assert dialog.buzzer_file_edit.placeholderText() == "the built-in buzzer"
    dialog.buzzer_file_edit.setText(f"  {tmp_path / 'alarm.aiff'}  ")
    assert dialog.result_settings().buzzer_file == str(tmp_path / "alarm.aiff")
    dialog.show_settings(PomodoroSettings())
    assert dialog.tick_file_edit.text() == "" and dialog.result_settings() == PomodoroSettings()


def test_the_widget_logs_a_missing_file_once(qtbot, store, tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "sound_effect_class", lambda: None)
    monkeypatch.setattr(pm.QtWidgets.QApplication, "beep", lambda: None)
    widget = pm.PomodoroTimer()
    qtbot.addWidget(widget)
    lines = []
    widget.logged.connect(lines.append)
    widget.apply_settings(PomodoroSettings(buzzer_file=str(tmp_path / "gone.mp3")))
    widget._player = None
    monkeypatch.setattr(pm.shutil, "which", lambda name: None)
    widget._play("buzzer", 80)
    widget._play("buzzer", 80)
    assert [line for line in lines if "not found" in line] == [
        f"{tmp_path / 'gone.mp3'} not found, so the built-in buzzer plays"]
