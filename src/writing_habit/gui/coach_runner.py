"""The coach in the window: settings, guardrails, a background thread, and dialogs.

:mod:`writing_habit.coach` holds the logic with no Qt. This module connects it
to the window. :func:`client` builds the model client from the settings, or
returns ``None`` when the writer has not turned the local model on.
:class:`Guard` applies Rule 10 before any request: no coach during a planned
block unless the writer insists, and none in an AI-off week. :class:`Runner`
sends the request on a worker thread, so the window stays responsive while a
model thinks. :class:`SuggestionDialog` shows a reply as choices the writer
accepts or discards, and the choice is written to the ``ai_log`` table.
"""

from __future__ import annotations

import datetime as _dt
from typing import Callable, List, Optional, Sequence

from .. import coach
from . import settings
from .qt import Qt, QtCore, QtWidgets, pyqtSignal


def source_line(source: str) -> str:
    """Say who wrote a reply, in a sentence for the window."""
    if source.startswith("local model"):
        return f"Written by the {source}."
    rest = source.split("written without a model", 1)
    if len(rest) == 2 and rest[1].strip(", "):
        return f"A plain summary written without a model{rest[1].rstrip('.')}."
    return "A plain summary written without a model."


def client() -> Optional[coach.Client]:
    """Return the model client the settings describe, or ``None`` when it is off."""
    if settings.get("ai_debrief") != "true":
        return None
    return coach.Client(
        model=settings.get("ai_model"), url=settings.get("ai_url"),
        api=settings.get("ai_api") or "ollama",
        allow_remote=settings.get("ai_allow_remote") == "true")


class Guard:
    """Rule 10 before every request.

    ``blocks`` returns the planned blocks of the open week, ``monday`` its
    Monday. ``now`` and ``confirm`` are replaced in tests.
    """

    def __init__(self, blocks: Callable[[], Sequence], monday: Callable[[], object],
                 parent=None):
        self.blocks = blocks
        self.monday = monday
        self.parent = parent
        self.now = _dt.datetime.now
        self.confirm = self._ask

    def _ask(self, text: str) -> bool:
        answer = QtWidgets.QMessageBox.question(
            self.parent, "The coach stays quiet during a block",
            text + "\n\nAsk anyway?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        return answer == QtWidgets.QMessageBox.Yes

    def allows(self) -> Optional[str]:
        """Return ``None`` when the coach may speak, or the reason it may not."""
        now = self.now()
        try:
            coach.check_allowed(now.date(), off_week=settings.get("ai_off_week"))
        except coach.CoachError as exc:
            return str(exc)
        block = coach.block_now(self.blocks(), self.monday(), now)
        if block is None:
            return None
        try:
            coach.check_allowed(now.date(), in_block=block)
        except coach.CoachError as exc:
            if self.confirm(str(exc)[0].upper() + str(exc)[1:] + "."):
                return None
            return str(exc)
        return None


class _Signals(QtCore.QObject):
    finished = pyqtSignal(object, object)       # result, error


class _Task(QtCore.QRunnable):
    def __init__(self, work):
        super().__init__()
        self.work = work
        self.signals = _Signals()

    def run(self) -> None:                       # pragma: no cover - threaded
        try:
            result, error = self.work(), None
        except Exception as exc:                 # noqa: BLE001
            result, error = None, exc
        self.signals.finished.emit(result, error)


class Runner(QtCore.QObject):
    """Run coach work off the window's thread.

    ``background`` is set false in tests, which then get the result at once.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.background = True
        self._live: List[_Task] = []

    def run(self, work: Callable[[], object], done: Callable[[object], None],
            failed: Optional[Callable[[Exception], None]] = None) -> None:
        if not self.background:
            try:
                result = work()
            except Exception as exc:              # noqa: BLE001
                if failed is not None:
                    failed(exc)
                    return
                raise
            done(result)
            return
        task = _Task(work)                         # pragma: no cover - threaded
        self._live.append(task)

        def finish(result, error):                 # pragma: no cover - threaded
            self._live.remove(task)
            QtWidgets.QApplication.restoreOverrideCursor()
            if error is not None:
                if failed is not None:
                    failed(error)
                return
            done(result)
        task.signals.finished.connect(finish)
        QtWidgets.QApplication.setOverrideCursor(Qt.BusyCursor)
        QtCore.QThreadPool.globalInstance().start(task)


def connect(db_path: str):
    """Open the habit database with the coach tables in place."""
    from .. import db, review
    con = db.connect(db_path)
    review.ensure(con)
    return con


class SuggestionDialog(QtWidgets.QDialog):
    """A coach reply as a list of choices, with the facts that were sent.

    ``items`` are the lines the writer may accept, each with a checkbox, or none
    for a reply that is only read. Accepting or discarding marks the reply in
    the ``ai_log`` table.
    """

    def __init__(self, title: str, answer: coach.Answer, items: Sequence[str] = (),
                 intro: str = "", accept_text: str = "Accept", parent=None,
                 checked: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.answer = answer
        layout = QtWidgets.QVBoxLayout(self)
        if intro and ("\n\n" in intro or len(intro) > 320):
            # A long note of several paragraphs goes in a box that scrolls,
            # because a wrapped label is cut off when the dialog sizes itself.
            note = QtWidgets.QPlainTextEdit(intro)
            note.setReadOnly(True)
            note.setMinimumSize(560, 150)
            layout.addWidget(note)
        elif intro:
            label = QtWidgets.QLabel(intro)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.boxes: List[QtWidgets.QCheckBox] = []
        for item in items:
            box = QtWidgets.QCheckBox(item)
            box.setChecked(checked)
            self.boxes.append(box)
            layout.addWidget(box)
        if not items:
            text = QtWidgets.QPlainTextEdit(answer.text)
            text.setReadOnly(True)
            text.setMinimumHeight(120)
            layout.addWidget(text)
        source = QtWidgets.QLabel(source_line(answer.source))
        source.setWordWrap(True)
        source.setStyleSheet("color: #898781;")
        layout.addWidget(source)
        facts = QtWidgets.QPushButton("Show what was sent")
        facts.setAutoDefault(False)
        facts.setCheckable(True)
        self.facts_view = QtWidgets.QPlainTextEdit(answer.facts or "Nothing was sent.")
        self.facts_view.setReadOnly(True)
        self.facts_view.setVisible(False)
        facts.toggled.connect(self.facts_view.setVisible)
        layout.addWidget(facts)
        layout.addWidget(self.facts_view)
        buttons = QtWidgets.QDialogButtonBox()
        self.accept_button = buttons.addButton(accept_text,
                                               QtWidgets.QDialogButtonBox.AcceptRole)
        buttons.addButton("Discard", QtWidgets.QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen(self) -> List[int]:
        """Return the positions of the checked items."""
        return [i for i, box in enumerate(self.boxes) if box.isChecked()]


class PartnerDialog(QtWidgets.QDialog):
    """The Friday summary as an editable draft that the writer copies and sends.

    Nothing is sent from here. **Copy to clipboard** puts the edited text on the
    clipboard for the writer to paste into an email or a chat, and marks the
    draft accepted in the ``ai_log`` table.
    """

    INTRO = ("A short summary of the week for your accountability partner. "
             "Edit it as you like, then copy it into a message. It holds totals "
             "and objectives met, not your full log.")

    def __init__(self, answer: coach.Answer, parent=None,
                 title: str = "Summary for your writing partner",
                 intro: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.answer = answer
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(intro or self.INTRO)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.editor = QtWidgets.QPlainTextEdit(answer.data["text"])
        self.editor.setMinimumHeight(160)
        layout.addWidget(self.editor)
        source = QtWidgets.QLabel(source_line(answer.source))
        source.setWordWrap(True)
        source.setStyleSheet("color: #898781;")
        layout.addWidget(source)
        facts = QtWidgets.QPushButton("Show what was sent")
        facts.setAutoDefault(False)
        facts.setCheckable(True)
        self.facts_view = QtWidgets.QPlainTextEdit(answer.facts or "Nothing was sent.")
        self.facts_view.setReadOnly(True)
        self.facts_view.setVisible(False)
        facts.toggled.connect(self.facts_view.setVisible)
        layout.addWidget(facts)
        layout.addWidget(self.facts_view)
        buttons = QtWidgets.QDialogButtonBox()
        self.accept_button = buttons.addButton("Copy to clipboard",
                                               QtWidgets.QDialogButtonBox.AcceptRole)
        buttons.addButton("Close", QtWidgets.QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(640, 470)

    def text(self) -> str:
        """Return the draft as the writer left it."""
        return self.editor.toPlainText().strip()


class MissesDialog(QtWidgets.QDialog):
    """One question per missed block, each with a box for the writer's reason.

    The coach only asks. **Save the answers** keeps each reason in the
    ``block_miss`` table, and an emptied box removes a saved reason.
    """

    def __init__(self, answer: coach.Answer, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Why were these blocks missed?")
        self.answer = answer
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(answer.data.get("intro", ""))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.boxes: List[QtWidgets.QLineEdit] = []
        for question, miss in zip(answer.data["questions"], answer.data["misses"]):
            label = QtWidgets.QLabel(question)
            label.setWordWrap(True)
            layout.addWidget(label)
            box = QtWidgets.QLineEdit(miss.reason)
            box.setPlaceholderText("What took that slot, in a sentence")
            layout.addWidget(box)
            self.boxes.append(box)
        source = QtWidgets.QLabel(source_line(answer.source))
        source.setWordWrap(True)
        source.setStyleSheet("color: #898781;")
        layout.addWidget(source)
        facts = QtWidgets.QPushButton("Show what was sent")
        facts.setAutoDefault(False)
        facts.setCheckable(True)
        self.facts_view = QtWidgets.QPlainTextEdit(answer.facts or "Nothing was sent.")
        self.facts_view.setReadOnly(True)
        self.facts_view.setVisible(False)
        facts.toggled.connect(self.facts_view.setVisible)
        layout.addWidget(facts)
        layout.addWidget(self.facts_view)
        buttons = QtWidgets.QDialogButtonBox()
        self.accept_button = buttons.addButton("Save the answers",
                                               QtWidgets.QDialogButtonBox.AcceptRole)
        buttons.addButton("Close", QtWidgets.QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(640, 120 + 70 * len(self.boxes))

    def answers(self) -> List[str]:
        """Return the reasons as the writer left them, one per question."""
        return [box.text().strip() for box in self.boxes]
