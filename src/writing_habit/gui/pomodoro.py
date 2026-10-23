"""A Pomodoro timer that sits beside the block timer.

The block timer counts down the planned writing block. The Pomodoro timer
splits that block into Pomodoros of focused work with short breaks between
them, and a long break at the end of the cycle::

    Pomodoro 1, short break, Pomodoro 2, short break, ..., Pomodoro n, long break

By default the cycle length ``n`` comes from the block. It is the largest
number of Pomodoros that fit in the block with their short breaks, so a
two-hour block holds four (4 x 25 + 3 x 5 = 115 minutes), 90 minutes holds
three, and an hour holds two. The long break then falls in the break between
two blocks. A fixed number in the settings overrides that.

The timer ticks once a second during a Pomodoro and sounds a buzzer when a
phase ends. Both sounds can be turned off. Its settings follow the familiar
Pomodoro apps: General, Timing, Notifications, and Hotkeys. The hotkeys start
and stop the timer from anywhere in the application, by default Control
Command P and Control Command S on a Mac.

The counting lives in :class:`PomodoroClock`, which takes the time as an
argument, so the tests drive it without waiting. The widget only reads the
clock once a second and plays the sounds.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .. import pom_count
from . import settings
from .qt import QtCore, QtGui, QtWidgets, Qt, pyqtSignal, sound_effect_class

#: Minutes of each phase when no block decides, and the cycle length then.
DEFAULT_PER_CYCLE = 4

#: How often the widget reads the clock, in milliseconds.
TICK_MS = 1000

WORK_STYLE = "background: #fde4e1; border: 1px solid #d0503c;"
BREAK_STYLE = "background: #e2f3e4; border: 1px solid #3c9a50;"
WAIT_STYLE = "background: #fff0d9; border: 1px solid #e0a040;"


# -- settings ----------------------------------------------------------------------
@dataclass
class PomodoroSettings:
    """What the settings dialog edits. Stored as JSON under ``pomodoro``."""

    pomodoro: int = 25            # minutes of focused work
    short_break: int = 5
    long_break: int = 15
    per_cycle: int = DEFAULT_PER_CYCLE  # Pomodoros per cycle when not automatic
    auto_cycle: bool = True       # take the cycle length from the time block
    auto_next: bool = True        # start the next timer without a press
    tick: bool = True             # tick once a second
    tick_in_breaks: bool = False  # tick during breaks too
    tick_volume: int = 30         # percent
    buzzer: bool = True           # sound a buzzer when a phase ends
    buzzer_volume: int = 80       # percent
    alert: bool = True            # bounce the Dock icon when a phase ends
    tick_file: str = ""           # a sound file for the tick; empty is the built-in tick
    buzzer_file: str = ""         # a sound file for the alarm; empty is the built-in buzzer
    start_key: str = "Meta+Ctrl+P"  # Control Command P on a Mac
    stop_key: str = "Meta+Ctrl+S"   # Control Command S on a Mac
    record_db: bool = True        # write each day's total to a database table at 11:59 PM
    db_dir: str = pom_count.DEFAULT_DIR      # the folder of the database
    db_file: str = pom_count.DEFAULT_FILE    # the database file
    db_table: str = pom_count.DEFAULT_TABLE  # the table that gets one row per day

    def db_path(self) -> Path:
        return pom_count.database_path(self.db_dir, self.db_file)

    @classmethod
    def load(cls) -> "PomodoroSettings":
        """Return the stored settings, with defaults for anything missing."""
        try:
            stored = json.loads(settings.get("pomodoro") or "{}")
        except (ValueError, KeyError):
            stored = {}
        names = {f.name: f for f in fields(cls)}
        values = {}
        for key, value in (stored or {}).items():
            if key in names and isinstance(value, type(getattr(cls(), key))):
                values[key] = value
        return cls(**values)

    def save(self) -> None:
        settings.put("pomodoro", json.dumps(asdict(self), sort_keys=True))


def fit_in_block(block_minutes: Optional[int], pomodoro: int, short_break: int) -> int:
    """Return how many Pomodoros fit in a block of ``block_minutes``.

    The Pomodoros are separated by short breaks, and the long break is not
    counted, because it falls in the break after the block. A block too short
    for one Pomodoro still gets one. ``None`` gives :data:`DEFAULT_PER_CYCLE`.
    """
    if not block_minutes or block_minutes <= 0:
        return DEFAULT_PER_CYCLE
    pomodoro, short_break = max(1, pomodoro), max(0, short_break)
    return max(1, (block_minutes + short_break) // (pomodoro + short_break))


def block_minutes(block) -> Optional[int]:
    """Return the length of a planned block in minutes, or ``None``."""
    if block is None:
        return None
    try:
        first = int(block.start[:2]) * 60 + int(block.start[3:5])
        last = int(block.end[:2]) * 60 + int(block.end[3:5])
    except (AttributeError, ValueError, TypeError):
        return None
    if last <= first:
        last += 24 * 60
    return last - first


def cycle_length(options: PomodoroSettings, block=None) -> int:
    """Return the Pomodoros per cycle the settings give for ``block``."""
    if options.auto_cycle:
        return fit_in_block(block_minutes(block), options.pomodoro, options.short_break)
    return max(1, options.per_cycle)


def today_count(day: _dt.date) -> int:
    """Return how many Pomodoros were finished on ``day``.

    The count is kept with the other preferences as ``{"date": ..., "count": ...}``,
    so it survives a restart of the application. A stored count from another
    day counts as zero, which is how the count starts over each morning.
    """
    try:
        stored = json.loads(settings.get("pomodoro_today") or "{}")
    except (ValueError, KeyError):
        return 0
    if not isinstance(stored, dict) or stored.get("date") != day.isoformat():
        return 0
    count = stored.get("count", 0)
    return count if isinstance(count, int) and count > 0 else 0


def stored_day() -> Optional[Tuple[_dt.date, int]]:
    """Return the day and count the stored tally belongs to, or ``None``."""
    try:
        stored = json.loads(settings.get("pomodoro_today") or "{}")
        day = _dt.date.fromisoformat(stored["date"])
    except (ValueError, KeyError, TypeError):
        return None
    return day, today_count(day)


def last_recorded() -> Tuple[str, int]:
    """Return the date and count last written to the database."""
    try:
        stored = json.loads(settings.get("pom_recorded") or "{}")
        return str(stored.get("date", "")), int(stored.get("count", -1))
    except (ValueError, KeyError, TypeError, AttributeError):
        return "", -1


def next_record_time(now: _dt.datetime) -> _dt.datetime:
    """Return the next 11:59 PM after ``now``."""
    target = now.replace(hour=23, minute=59, second=0, microsecond=0)
    return target if target > now else target + _dt.timedelta(days=1)


def add_to_today(day: _dt.date) -> int:
    """Count one more finished Pomodoro on ``day`` and return the new total."""
    count = today_count(day) + 1
    settings.put("pomodoro_today", json.dumps({"date": day.isoformat(), "count": count}))
    return count


# -- the clock -----------------------------------------------------------------------
WORK, SHORT, LONG = "pomodoro", "short", "long"


@dataclass
class Phase:
    kind: str          # WORK, SHORT, or LONG
    number: int        # which Pomodoro of the cycle it belongs to
    minutes: int

    def label(self, of: int) -> str:
        if self.kind == WORK:
            return f"Pomodoro {self.number}/{of}"
        return "Short break" if self.kind == SHORT else "Long break"


def build_cycle(options: PomodoroSettings, count: int) -> List[Phase]:
    """Return the phases of one cycle of ``count`` Pomodoros."""
    phases: List[Phase] = []
    for number in range(1, count + 1):
        phases.append(Phase(WORK, number, options.pomodoro))
        if number < count:
            phases.append(Phase(SHORT, number, options.short_break))
    phases.append(Phase(LONG, count, options.long_break))
    return phases


@dataclass
class PomodoroClock:
    """The timer's state. Every method takes the time in seconds."""

    options: PomodoroSettings = field(default_factory=PomodoroSettings)
    state: str = "idle"            # idle, running, paused, waiting, done
    phases: List[Phase] = field(default_factory=list)
    index: int = 0
    ends_at: float = 0.0
    paused_left: float = 0.0
    count: int = 0
    completed: int = 0             # Pomodoros finished since the last start

    @property
    def phase(self) -> Optional[Phase]:
        return self.phases[self.index] if self.phases and self.index < len(self.phases) else None

    def start(self, now: float, block=None) -> None:
        """Start a cycle, resume a pause, or begin the phase that is waiting."""
        if self.state == "paused":
            self.ends_at = now + self.paused_left
            self.state = "running"
        elif self.state == "waiting":
            self._begin(now)
        elif self.state in ("idle", "done"):
            self.count = cycle_length(self.options, block)
            self.phases = build_cycle(self.options, self.count)
            self.index = 0
            self.completed = 0
            self._begin(now)

    def pause(self, now: float) -> None:
        if self.state == "running":
            self.paused_left = max(0.0, self.ends_at - now)
            self.state = "paused"

    def stop(self) -> None:
        self.state = "idle"
        self.phases = []
        self.index = 0

    def remaining(self, now: float) -> float:
        """Seconds left in the phase under way."""
        if self.state == "running":
            return max(0.0, self.ends_at - now)
        if self.state == "paused":
            return self.paused_left
        if self.state == "waiting" and self.phase is not None:
            return self.phase.minutes * 60.0
        return 0.0

    def poll(self, now: float) -> Optional[Phase]:
        """Advance when the phase under way has ended. Return the phase that ended."""
        if self.state != "running" or now < self.ends_at:
            return None
        ended = self.phase
        if ended is not None and ended.kind == WORK:
            self.completed += 1
        self.index += 1
        if self.index >= len(self.phases):
            self.state = "done"
        elif self.options.auto_next:
            # Count the next phase from when the last one should have ended,
            # so a late read of the clock does not stretch the cycle.
            self._begin(self.ends_at)
        else:
            self.state = "waiting"
        return ended

    def _begin(self, now: float) -> None:
        self.ends_at = now + self.phase.minutes * 60.0
        self.state = "running"

    def text(self, now: float) -> str:
        """What the timer shows, such as ``Pomodoro 2/4  18:07``."""
        if self.state == "idle":
            return "Pomodoro"
        if self.state == "done":
            return f"Cycle done, {self.completed} Pomodoros"
        phase = self.phase
        left = int(math.ceil(self.remaining(now)))
        clock = f"{left // 60:02d}:{left % 60:02d}"
        if self.state == "waiting":
            return f"{phase.label(self.count)} ready. Press Start"
        if self.state == "paused":
            return f"{phase.label(self.count)}  {clock} paused"
        return f"{phase.label(self.count)}  {clock}"


# -- sounds --------------------------------------------------------------------------
RATE = 22050


def _write_wave(path: Path, samples: List[float]) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32000))
                                 for s in samples))


def tick_samples() -> List[float]:
    """A short wooden click, like a kitchen timer."""
    rng = random.Random(7)
    count = int(RATE * 0.035)
    return [math.exp(-i / (RATE * 0.004)) * (0.6 * math.sin(2 * math.pi * 2600 * i / RATE)
                                            + 0.4 * rng.uniform(-1, 1))
            for i in range(count)]


def buzzer_samples() -> List[float]:
    """Three rasping buzzes, a little under a second and a half in all."""
    out: List[float] = []
    for _ in range(3):
        for i in range(int(RATE * 0.32)):
            t = i / RATE
            square = 1.0 if math.sin(2 * math.pi * 220 * t) >= 0 else -1.0
            fifth = 1.0 if math.sin(2 * math.pi * 330 * t) >= 0 else -1.0
            fade = min(1.0, i / 200, (RATE * 0.32 - i) / 200)
            out.append(0.35 * (square + 0.6 * fifth) * fade)
        out.extend([0.0] * int(RATE * 0.12))
    return out


def sound_files(folder: Optional[Path] = None) -> dict:
    """Write the two sounds once and return ``{"tick": path, "buzzer": path}``."""
    folder = folder or Path(tempfile.gettempdir()) / "writing-habit-sounds"
    folder.mkdir(parents=True, exist_ok=True)
    paths = {"tick": folder / "tick.wav", "buzzer": folder / "buzzer.wav"}
    makers = {"tick": tick_samples, "buzzer": buzzer_samples}
    for name, path in paths.items():
        if not path.exists() or path.stat().st_size < 100:
            _write_wave(path, makers[name]())
    return paths


#: Sound files QtMultimedia plays. Other types go to ``afplay`` on macOS.
WAVE_SUFFIXES = (".wav", ".wave")

#: The types the file dialog offers. ``afplay`` plays all of them on a Mac.
SOUND_FILTER = "Sound files (*.wav *.aiff *.aif *.mp3 *.m4a *.caf);;All files (*)"


def choose_sound(name: str, custom: str, built_in: dict) -> Tuple[Path, str]:
    """Return the file to play for ``name`` and a note about the choice.

    ``custom`` is the file set in the settings, or empty for the built-in
    sound. A custom file that is missing falls back to the built-in one, and
    the note says so, so a moved file never silences the timer.
    """
    if custom:
        path = Path(custom).expanduser()
        if path.is_file():
            return path, ""
        return built_in[name], f"{path} not found, so the built-in {name} plays"
    return built_in[name], ""


class SoundPlayer:
    """Plays the tick and the buzzer by the best means this computer has.

    Each sound is the built-in one or a file chosen in the settings. A WAV
    file plays through QtMultimedia. Another type, such as MP3 or AIFF, plays
    through ``afplay`` on macOS. Without either, the buzzer becomes the system
    beep and the tick is silent, because a beep every second would be worse
    than none.
    """

    def __init__(self, parent=None, files: Optional[dict] = None):
        self.parent = parent
        self.built_in = sound_files()
        self.effect_class = sound_effect_class()
        self.afplay = shutil.which("afplay") if sys.platform == "darwin" else None
        self.files: dict = {}
        self.paths: dict = {}
        self.notes: dict = {}
        self.effects: dict = {}
        self.set_files(files or {})

    def set_files(self, files: dict) -> None:
        """Use ``{"tick": path or "", "buzzer": path or ""}`` from now on."""
        files = {name: (files.get(name) or "") for name in ("tick", "buzzer")}
        if files == self.files and self.paths:
            return
        self.files = files
        self.effects = {}
        for name in ("tick", "buzzer"):
            path, note = choose_sound(name, files[name], self.built_in)
            if path.suffix.lower() not in WAVE_SUFFIXES and not self.afplay:
                note = (f"{path.name} is not a WAV file and this computer has no "
                        f"afplay, so the built-in {name} plays")
                path = self.built_in[name]
            self.paths[name], self.notes[name] = path, note
            if self.effect_class is not None and path.suffix.lower() in WAVE_SUFFIXES:
                try:
                    effect = self.effect_class(self.parent)
                    effect.setSource(QtCore.QUrl.fromLocalFile(str(path)))
                    self.effects[name] = effect
                except Exception:                         # pragma: no cover
                    pass

    def means(self, name: str) -> str:
        """How ``name`` plays: QtMultimedia, afplay, the system beep, or silence."""
        if name in self.effects:
            return "QtMultimedia"
        if self.afplay:
            return "afplay"
        return "the system beep" if name == "buzzer" else "silence"

    def play(self, name: str, volume: int) -> None:
        volume = max(0, min(100, volume)) / 100.0
        if volume <= 0:
            return
        effect = self.effects.get(name)
        if effect is not None:
            effect.setVolume(volume)
            effect.play()
        elif self.afplay:
            subprocess.Popen([self.afplay, "-v", f"{volume:.2f}", str(self.paths[name])],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif name == "buzzer":
            QtWidgets.QApplication.beep()


# -- the widget ----------------------------------------------------------------------
class PomodoroTimer(QtWidgets.QWidget):
    """The timer's controls: a start/pause button, the display, stop, settings."""

    #: Emitted with a line for the log, such as when a phase ends.
    logged = pyqtSignal(str)
    #: Emitted with the phase that just ended.
    phase_ended = pyqtSignal(object)

    def __init__(self, block: Callable[[], object] = lambda: None, parent=None):
        super().__init__(parent)
        #: Returns the block that decides the cycle length, or ``None``.
        self.block = block
        #: The clock in seconds. A test replaces it.
        self.now = time.monotonic
        #: The calendar day, for the count of today's Pomodoros. A test replaces it.
        self.today = _dt.date.today
        #: The wall clock, for the 11:59 PM record. A test replaces it.
        self.wall = _dt.datetime.now
        self.options = PomodoroSettings.load()
        self.clock = PomodoroClock(self.options)
        #: Plays a sound by name and volume. A test replaces it.
        self.play: Callable[[str, int], None] = self._play
        self._player: Optional[SoundPlayer] = None
        self._noted: dict = {}           # the last note about each sound, logged once
        self._shortcuts: List[QtWidgets.QShortcut] = []
        self._host = None

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        style = self.style()
        self.start_button = QtWidgets.QToolButton()
        self.start_button.clicked.connect(self.toggle)
        self.display = QtWidgets.QPushButton("Pomodoro")
        self.display.setToolTip(
            "Pomodoros of focused work with short breaks, and a long break at "
            "the end of the cycle. The number of Pomodoros comes from the "
            "length of the live or selected block. Press to start or pause.")
        self.display.clicked.connect(self.toggle)
        self.stop_button = QtWidgets.QToolButton()
        self.stop_button.setIcon(style.standardIcon(QtWidgets.QStyle.SP_MediaStop))
        self.stop_button.clicked.connect(self.stop)
        self.settings_button = QtWidgets.QToolButton()
        self.settings_button.setText("...")
        self.settings_button.setToolTip("Pomodoro settings: timing, sounds, and hotkeys")
        self.settings_button.clicked.connect(lambda: self.open_settings())
        self.today_label = QtWidgets.QLabel()
        self.today_label.setToolTip(
            "Pomodoros finished today. A Pomodoro counts when its 25 minutes, "
            "or the length set in the settings, run out. The count starts over "
            "at midnight.")
        for widget in (self.start_button, self.display, self.stop_button,
                       self.settings_button, self.today_label):
            layout.addWidget(widget)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.update_state)
        # The daily record: a single shot at 11:59 PM, set again each night.
        self.record_timer = QtCore.QTimer(self)
        self.record_timer.setSingleShot(True)
        self.record_timer.timeout.connect(self._record_tonight)
        self._record_target: Optional[_dt.date] = None
        self.schedule_record()
        # A day left unrecorded, because the app was closed at 11:59 PM, is
        # written once the window is up.
        QtCore.QTimer.singleShot(0, self.catch_up)
        self.update_state()

    # -- the daily record ----------------------------------------------------------------
    def schedule_record(self) -> None:
        """Set the timer for the next 11:59 PM."""
        now = self.wall()
        target = next_record_time(now)
        self._record_target = target.date()
        self.record_timer.start(max(1000, int((target - now).total_seconds() * 1000)))

    def _record_tonight(self) -> None:
        target = self._record_target
        if target is not None and self.wall().date() == target:
            self.record_day(target, today_count(target))
        else:
            # The timer fired late, after a sleep, so the day may already have
            # changed. The stored tally still says which day it belongs to.
            self.catch_up()
        self.schedule_record()

    def catch_up(self) -> Optional[str]:
        """Write the stored tally of an earlier day when the database lacks it."""
        stored = stored_day()
        if stored is None:
            return None
        day, count = stored
        if day >= self.today() or last_recorded() == (day.isoformat(), count):
            return None
        return self.record_day(day, count)

    def record_day(self, day: _dt.date, count: int) -> Optional[str]:
        """Write ``count`` for ``day`` to the database table. Return what happened."""
        if not self.options.record_db:
            return None
        path = self.options.db_path()
        try:
            done = pom_count.record(path, self.options.db_table, day, count, self.wall())
        except (OSError, ValueError, pom_count.sqlite3.Error) as exc:
            self.logged.emit(f"Could not record the Pomodoro count for {day}: {exc}")
            return None
        settings.put("pom_recorded", json.dumps({"date": day.isoformat(), "count": count}))
        self.logged.emit(f"Recorded {count} Pomodoros for {day} in "
                         f"{self.options.db_table} of {path}")
        return done

    # -- the controls ------------------------------------------------------------------
    def start(self) -> None:
        """Start a cycle, resume a pause, or begin a phase that is waiting."""
        was = self.clock.state
        self.clock.start(self.now(), self.block())
        if was in ("idle", "done"):
            self.logged.emit(f"Pomodoro cycle of {self.clock.count} started")
        self.timer.start()
        self.update_state()

    def pause(self) -> None:
        self.clock.pause(self.now())
        self.update_state()

    def toggle(self) -> None:
        if self.clock.state == "running":
            self.pause()
        else:
            self.start()

    def stop(self) -> None:
        if self.clock.state != "idle":
            self.logged.emit(f"Pomodoro stopped after {self.clock.completed} "
                             f"Pomodoros")
        self.clock.stop()
        self.timer.stop()
        self.update_state()

    def update_state(self) -> str:
        """Read the clock: tick, buzz at a phase's end, and redraw."""
        now = self.now()
        ended = self.clock.poll(now)
        if ended is not None:
            self._phase_ended(ended)
        state = self.clock.state
        phase = self.clock.phase
        if state == "running" and phase is not None and self.options.tick and ended is None \
                and (phase.kind == WORK or self.options.tick_in_breaks):
            self.play("tick", self.options.tick_volume)
        if state not in ("running", "paused", "waiting"):
            self.timer.stop()
        text = self.clock.text(now)
        self.display.setText(text)
        self.today_label.setText(f" Today: {today_count(self.today())}")
        style = self.style()
        running = state == "running"
        self.start_button.setIcon(style.standardIcon(
            QtWidgets.QStyle.SP_MediaPause if running else QtWidgets.QStyle.SP_MediaPlay))
        self.start_button.setToolTip(
            f"{'Pause' if running else 'Start'} the Pomodoro timer "
            f"({self._key_text(self.options.start_key)})")
        self.stop_button.setToolTip(
            f"Stop the Pomodoro timer ({self._key_text(self.options.stop_key)})")
        self.stop_button.setEnabled(state != "idle")
        if state == "waiting":
            self.display.setStyleSheet(WAIT_STYLE)
        elif state in ("running", "paused") and phase is not None:
            self.display.setStyleSheet(WORK_STYLE if phase.kind == WORK else BREAK_STYLE)
        else:
            self.display.setStyleSheet("")
        return text

    def _phase_ended(self, ended: Phase) -> None:
        if ended.kind == WORK:
            self.catch_up()                 # before a new day's tally replaces the old one
            add_to_today(self.today())
        if self.options.buzzer:
            self.play("buzzer", self.options.buzzer_volume)
        if self.options.alert and self.window() is not None:
            QtWidgets.QApplication.alert(self.window())
        following = self.clock.phase
        if self.clock.state == "done":
            line = f"Pomodoro cycle done: {self.clock.completed} Pomodoros"
            # The long break ends at the next block. With automatic starts and
            # a block under way, the next cycle begins by itself.
            if self.options.auto_next and self.block() is not None:
                self.clock.start(self.now(), self.block())
                line += f". Next cycle of {self.clock.count} started"
        elif following is not None:
            line = (f"{ended.label(self.clock.count)} ended. "
                    f"{following.label(self.clock.count)} "
                    f"{'started' if self.clock.state == 'running' else 'is ready'}")
        else:                                                   # pragma: no cover
            line = f"{ended.label(self.clock.count)} ended"
        self.logged.emit(line)
        self.phase_ended.emit(ended)

    def _play(self, name: str, volume: int, options: Optional[PomodoroSettings] = None) -> None:
        options = options or self.options
        files = {"tick": options.tick_file, "buzzer": options.buzzer_file}
        if self._player is None:
            self._player = SoundPlayer(self, files)
        else:
            self._player.set_files(files)
        note = self._player.notes.get(name)
        if note and note != self._noted.get(name):
            self.logged.emit(note)
        self._noted[name] = note
        self._player.play(name, volume)

    # -- hotkeys -----------------------------------------------------------------------
    @staticmethod
    def _key_text(sequence: str) -> str:
        return QtGui.QKeySequence(sequence).toString(QtGui.QKeySequence.NativeText)

    def install_hotkeys(self, host: QtWidgets.QWidget) -> None:
        """Bind the start and stop hotkeys on ``host``, for the whole application.

        The shortcuts live on the main window rather than on this widget, so
        they work whichever tab is shown.
        """
        for shortcut in self._shortcuts:
            shortcut.setParent(None)
            shortcut.deleteLater()
        self._shortcuts = []
        self._host = host
        for sequence, action in ((self.options.start_key, self.start),
                                 (self.options.stop_key, self.stop)):
            if not sequence:
                continue
            shortcut = QtWidgets.QShortcut(QtGui.QKeySequence(sequence), host)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(action)
            self._shortcuts.append(shortcut)

    def showEvent(self, event) -> None:                       # noqa: N802
        super().showEvent(event)
        if self.window() is not self._host:
            self.install_hotkeys(self.window())

    # -- settings ----------------------------------------------------------------------
    def apply_settings(self, options: PomodoroSettings) -> None:
        """Use ``options`` from now on and store them."""
        self.options = options
        self.clock.options = options
        options.save()
        if self._host is not None:
            self.install_hotkeys(self._host)
        self.update_state()

    def play_test(self, name: str, volume: int, options: PomodoroSettings) -> None:
        """Play ``name`` as ``options`` set it, for a Test button."""
        if self.play == self._play:
            self._play(name, volume, options)
        else:
            self.play(name, volume)

    def _record_from_dialog(self, dialog) -> None:
        """Write today's count now, to the database the dialog names."""
        keep = self.options
        self.options = dialog.result_settings()
        try:
            done = self.record_day(self.today(), today_count(self.today()))
        finally:
            self.options = keep
        dialog.db_status.setText(
            f"{done.capitalize()} today's row in {dialog.result_settings().db_table}"
            if done else "Not recorded. See the log for why.")

    def open_settings(self, run=True):
        dialog = PomodoroSettingsDialog(self.options, self.block(), self)
        # A Test button plays the file the dialog shows, before OK saves it.
        dialog.test_requested.connect(
            lambda name, volume: self.play_test(name, volume, dialog.result_settings()))
        dialog.record_requested.connect(lambda: self._record_from_dialog(dialog))
        if run and dialog.exec_() == QtWidgets.QDialog.Accepted:
            self.apply_settings(dialog.result_settings())
        return dialog


class PomodoroSettingsDialog(QtWidgets.QDialog):
    """General, Timing, Notifications, and Hotkeys, as in the usual Pomodoro apps."""

    #: Emitted with a sound name and a volume when a Test button is pressed.
    test_requested = pyqtSignal(str, int)
    #: Emitted when "Record today now" is pressed.
    record_requested = pyqtSignal()

    def __init__(self, options: PomodoroSettings, block=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pomodoro settings")
        self.block = block
        self.tabs = QtWidgets.QTabWidget()

        # General: the ticking.
        general = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(general)
        self.tick_box = QtWidgets.QCheckBox("Tick during a Pomodoro")
        self.tick_box.setChecked(options.tick)
        self.tick_breaks_box = QtWidgets.QCheckBox("Tick during breaks too")
        self.tick_breaks_box.setChecked(options.tick_in_breaks)
        self.tick_volume = self._slider(options.tick_volume)
        form.addRow(self.tick_box)
        form.addRow(self.tick_breaks_box)
        form.addRow("Tick volume:", self._with_test(self.tick_volume, "tick"))
        self.tick_file_edit = self._file_row(form, "Tick sound:", options.tick_file, "tick")
        self.tabs.addTab(general, "General")

        # Timing.
        timing = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(timing)
        self.pomodoro_spin = self._minutes(options.pomodoro, 1, 120)
        self.short_spin = self._minutes(options.short_break, 1, 60)
        self.long_spin = self._minutes(options.long_break, 1, 120)
        form.addRow("Pomodoro:", self._unit(self.pomodoro_spin))
        form.addRow("Short break:", self._unit(self.short_spin))
        form.addRow("Long break:", self._unit(self.long_spin))
        self.per_cycle_spin = QtWidgets.QSpinBox()
        self.per_cycle_spin.setRange(1, 12)
        self.per_cycle_spin.setValue(options.per_cycle)
        #: The fixed number, kept while the box shows the block's number.
        self.fixed_per_cycle = options.per_cycle
        self.auto_cycle_box = QtWidgets.QCheckBox("From the time block")
        self.auto_cycle_box.setToolTip(
            "Fit as many Pomodoros in the live or selected block as its length "
            "allows, with short breaks between them")
        self.auto_cycle_box.setChecked(options.auto_cycle)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.per_cycle_spin)
        row.addWidget(self.auto_cycle_box)
        row.addStretch(1)
        form.addRow("Pomodoros per cycle:", row)
        self.auto_next_box = QtWidgets.QCheckBox("Start next timer automatically")
        self.auto_next_box.setChecked(options.auto_next)
        form.addRow(self.auto_next_box)
        for spin in (self.pomodoro_spin, self.short_spin):
            spin.valueChanged.connect(self._sync_cycle)
        self.auto_cycle_box.toggled.connect(self._sync_cycle)
        self.tabs.addTab(timing, "Timing")

        # Notifications: the buzzer.
        notes = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(notes)
        self.buzzer_box = QtWidgets.QCheckBox("Sound a buzzer when a Pomodoro or break ends")
        self.buzzer_box.setChecked(options.buzzer)
        self.buzzer_volume = self._slider(options.buzzer_volume)
        self.alert_box = QtWidgets.QCheckBox("Bounce the Dock icon when a phase ends")
        self.alert_box.setChecked(options.alert)
        form.addRow(self.buzzer_box)
        form.addRow("Buzzer volume:", self._with_test(self.buzzer_volume, "buzzer"))
        self.buzzer_file_edit = self._file_row(form, "Alarm sound:", options.buzzer_file,
                                               "buzzer")
        form.addRow(self.alert_box)
        self.tabs.addTab(notes, "Notifications")

        # Hotkeys.
        keys = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(keys)
        form.addRow("", QtWidgets.QLabel("Click to record hotkey"))
        self.start_key_edit = QtWidgets.QKeySequenceEdit(QtGui.QKeySequence(options.start_key))
        self.stop_key_edit = QtWidgets.QKeySequenceEdit(QtGui.QKeySequence(options.stop_key))
        form.addRow("Start Pomodoro:", self.start_key_edit)
        form.addRow("Stop Pomodoro:", self.stop_key_edit)
        self.tabs.addTab(keys, "Hotkeys")

        # Database: the daily record.
        data = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(data)
        self.record_box = QtWidgets.QCheckBox("Record each day's total at 11:59 PM")
        self.record_box.setChecked(options.record_db)
        self.db_dir_edit = QtWidgets.QLineEdit(options.db_dir)
        browse = QtWidgets.QPushButton("Browse")
        browse.clicked.connect(self._browse_folder)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.db_dir_edit)
        row.addWidget(browse)
        self.db_file_edit = QtWidgets.QLineEdit(options.db_file)
        self.db_table_edit = QtWidgets.QLineEdit(options.db_table)
        self.db_path_label = QtWidgets.QLabel()
        self.db_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        record_now = QtWidgets.QPushButton("Record today now")
        record_now.setToolTip("Write today's count to the table now, to test the settings")
        record_now.clicked.connect(self.record_requested.emit)
        self.db_status = QtWidgets.QLabel()
        form.addRow(self.record_box)
        form.addRow("Folder:", row)
        form.addRow("Database file:", self.db_file_edit)
        form.addRow("Table:", self.db_table_edit)
        form.addRow("Writes to:", self.db_path_label)
        form.addRow(record_now, self.db_status)
        for edit in (self.db_dir_edit, self.db_file_edit, self.db_table_edit):
            edit.textChanged.connect(self._sync_db)
        self.tabs.addTab(data, "Database")

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
            | QtWidgets.QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.RestoreDefaults).clicked.connect(
            lambda: self.show_settings(PomodoroSettings()))
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)
        self._sync_cycle()
        self._sync_db()

    @staticmethod
    def _minutes(value, low, high):
        spin = QtWidgets.QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        return spin

    @staticmethod
    def _unit(spin):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(spin)
        row.addWidget(QtWidgets.QLabel("minutes"))
        row.addStretch(1)
        return row

    @staticmethod
    def _slider(value):
        slider = QtWidgets.QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(value)
        return slider

    def _with_test(self, slider, name):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(slider)
        button = QtWidgets.QPushButton("Test")
        button.clicked.connect(lambda: self.test_requested.emit(name, slider.value()))
        row.addWidget(button)
        return row

    def _file_row(self, form, label: str, value: str, name: str) -> QtWidgets.QLineEdit:
        """Add a sound file row: the path, Browse, and Built-in."""
        edit = QtWidgets.QLineEdit(value)
        edit.setPlaceholderText(f"the built-in {name}")
        edit.setToolTip(
            "A WAV file plays through Qt. AIFF, MP3, M4A, and CAF files play "
            "through afplay on a Mac. Leave it empty for the built-in sound."
            + (" Keep a tick shorter than a second, because it plays every second."
               if name == "tick" else ""))
        browse = QtWidgets.QPushButton("Browse")
        browse.clicked.connect(lambda: self._browse_sound(edit, label))
        reset = QtWidgets.QPushButton("Built-in")
        reset.setToolTip(f"Go back to the built-in {name}")
        reset.clicked.connect(edit.clear)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(edit)
        row.addWidget(browse)
        row.addWidget(reset)
        form.addRow(label, row)
        return edit

    def _browse_sound(self, edit: QtWidgets.QLineEdit, label: str) -> None:
        start = str(Path(edit.text()).expanduser().parent) if edit.text() else str(Path.home())
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, label.rstrip(":"), start, SOUND_FILTER)
        if path:
            edit.setText(path)

    def _browse_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Folder of the database",
            str(Path(self.db_dir_edit.text() or "~").expanduser()))
        if folder:
            self.db_dir_edit.setText(folder)

    def _sync_db(self) -> None:
        options = self.result_settings()
        try:
            pom_count.check_table(options.db_table)
            note = ""
        except ValueError:
            note = "  (the table name may hold only letters, digits, and _)"
        self.db_path_label.setText(f"{options.db_table} in {options.db_path()}{note}")

    def _sync_cycle(self) -> None:
        """Show the block's cycle length while the automatic choice is on."""
        auto = self.auto_cycle_box.isChecked()
        if auto and self.per_cycle_spin.isEnabled():
            self.fixed_per_cycle = self.per_cycle_spin.value()
        elif not auto and not self.per_cycle_spin.isEnabled():
            self.per_cycle_spin.setValue(self.fixed_per_cycle)
        self.per_cycle_spin.setEnabled(not auto)
        if auto:
            minutes = block_minutes(self.block)
            count = fit_in_block(minutes, self.pomodoro_spin.value(), self.short_spin.value())
            self.auto_cycle_box.setText(
                f"From the time block ({count} for {minutes} min)" if minutes
                else f"From the time block ({DEFAULT_PER_CYCLE} with none)")
            self.per_cycle_spin.setValue(count)
        else:
            self.auto_cycle_box.setText("From the time block")

    def show_settings(self, options: PomodoroSettings) -> None:
        self.tick_box.setChecked(options.tick)
        self.tick_breaks_box.setChecked(options.tick_in_breaks)
        self.tick_volume.setValue(options.tick_volume)
        self.pomodoro_spin.setValue(options.pomodoro)
        self.short_spin.setValue(options.short_break)
        self.long_spin.setValue(options.long_break)
        self.auto_cycle_box.setChecked(False)
        self.per_cycle_spin.setValue(options.per_cycle)
        self.fixed_per_cycle = options.per_cycle
        self.auto_cycle_box.setChecked(options.auto_cycle)
        self.auto_next_box.setChecked(options.auto_next)
        self.buzzer_box.setChecked(options.buzzer)
        self.buzzer_volume.setValue(options.buzzer_volume)
        self.alert_box.setChecked(options.alert)
        self.tick_file_edit.setText(options.tick_file)
        self.buzzer_file_edit.setText(options.buzzer_file)
        self.start_key_edit.setKeySequence(QtGui.QKeySequence(options.start_key))
        self.stop_key_edit.setKeySequence(QtGui.QKeySequence(options.stop_key))
        self.record_box.setChecked(options.record_db)
        self.db_dir_edit.setText(options.db_dir)
        self.db_file_edit.setText(options.db_file)
        self.db_table_edit.setText(options.db_table)
        self._sync_cycle()

    def result_settings(self) -> PomodoroSettings:
        return PomodoroSettings(
            pomodoro=self.pomodoro_spin.value(),
            short_break=self.short_spin.value(),
            long_break=self.long_spin.value(),
            per_cycle=(self.fixed_per_cycle if self.auto_cycle_box.isChecked()
                       else self.per_cycle_spin.value()),
            auto_cycle=self.auto_cycle_box.isChecked(),
            auto_next=self.auto_next_box.isChecked(),
            tick=self.tick_box.isChecked(),
            tick_in_breaks=self.tick_breaks_box.isChecked(),
            tick_volume=self.tick_volume.value(),
            buzzer=self.buzzer_box.isChecked(),
            buzzer_volume=self.buzzer_volume.value(),
            tick_file=self.tick_file_edit.text().strip(),
            buzzer_file=self.buzzer_file_edit.text().strip(),
            alert=self.alert_box.isChecked(),
            start_key=self.start_key_edit.keySequence().toString(),
            stop_key=self.stop_key_edit.keySequence().toString(),
            record_db=self.record_box.isChecked(),
            db_dir=self.db_dir_edit.text().strip() or pom_count.DEFAULT_DIR,
            db_file=self.db_file_edit.text().strip() or pom_count.DEFAULT_FILE,
            db_table=self.db_table_edit.text().strip() or pom_count.DEFAULT_TABLE,
        )
