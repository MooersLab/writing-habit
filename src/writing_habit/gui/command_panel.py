"""A form for one subcommand, with the shell command it will run.

The panel is generated from a :class:`~writing_habit.gui.argspec.CommandSpec`,
so it carries a widget for every option the parser declares. Three parts sit
below the form. The preview shows the command that will run, which teaches the
command line rather than hiding it. The run button is disabled while a required
value is missing, and the reason is named beside it. The output pane shows what
the command printed.
"""

from __future__ import annotations

from typing import Dict, Optional

from pathlib import Path

from . import argspec, forms, settings
from .qt import Qt, QtWidgets, fixed_font, pyqtSignal


class CommandPanel(QtWidgets.QWidget):
    """One generated form.  Emits every line it would write to the log."""

    logged = pyqtSignal(str)
    finished = pyqtSignal(str, int)      # output, exit code
    produced = pyqtSignal(list)          # the files the run wrote

    def __init__(self, spec: argspec.CommandSpec, prog: str = "writing-habit",
                 parent=None):
        super().__init__(parent)
        self.spec = spec
        self.prog = prog
        self.fields: Dict[str, forms.Field] = {}
        self.worker: Optional[object] = None
        #: Set by the window. Called with the argv before a run, and a false
        #: answer stops it. The panel does not know what the window wants to
        #: check, only that a run can be refused.
        self.guard = None

        outer = QtWidgets.QVBoxLayout(self)
        if spec.help:
            blurb = QtWidgets.QLabel(spec.help)
            blurb.setWordWrap(True)
            outer.addWidget(blurb)

        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        for option in spec.options:
            field = forms.build(option)
            field.on_change(self.refresh)
            self.fields[option.dest] = field
            label = option.label + (" *" if option.required or option.positional else "")
            form.addRow(label, field.widget)
        outer.addLayout(form)

        self.preview = QtWidgets.QLineEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(fixed_font())
        outer.addWidget(QtWidgets.QLabel("Command"))
        outer.addWidget(self.preview)

        row = QtWidgets.QHBoxLayout()
        self.run_button = QtWidgets.QPushButton("Run")
        self.run_button.clicked.connect(self.run)
        row.addWidget(self.run_button)
        self.note = QtWidgets.QLabel("")
        row.addWidget(self.note)
        row.addStretch(1)
        outer.addLayout(row)

        self.output = QtWidgets.QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Output appears here.")
        self.output.setFont(fixed_font())
        outer.addWidget(self.output, 1)

        self.seed_from_settings()
        self.refresh()

    # -- values ------------------------------------------------------------
    def values(self) -> Dict[str, object]:
        return {dest: field.value() for dest, field in self.fields.items()}

    def argv(self):
        return argspec.to_argv(self.spec, self.values())

    def command(self) -> str:
        return argspec.command_string(self.prog, self.argv())

    def seed_from_settings(self) -> None:
        """Fill the widgets a weekly loop reuses, so a run needs less typing."""
        remembered = {
            "db": settings.get("db"),
            "week": settings.get("week") or forms.today_iso(),
            "dir": settings.get("out_dir"),
        }
        table = argspec.table_dest(self.spec)
        if table is not None:
            remembered[table] = settings.get("table")
        for dest, value in remembered.items():
            field = self.fields.get(dest)
            if field is not None and value:
                field.set_value(value)

    def set_table(self, path: str) -> bool:
        """Point this form's table argument at ``path``.  Say whether it has one.

        The grid owns which table is current, and a form reads that choice
        rather than writing it back, so there is one answer to the question of
        which week is being worked on.
        """
        dest = argspec.table_dest(self.spec)
        field = self.fields.get(dest) if dest else None
        if field is None:
            return False
        field.set_value(path)
        self.refresh()
        return True

    def remember(self) -> None:
        """Store the paths this run used, so the next form starts there."""
        values = self.values()
        if values.get("db"):
            settings.put("db", str(values["db"]))
        if values.get("week"):
            settings.put("week", str(values["week"]))
        if values.get("dir"):
            settings.put("out_dir", str(values["dir"]))

    # -- state -------------------------------------------------------------
    def refresh(self) -> None:
        self.preview.setText(self.command())
        self.preview.setCursorPosition(0)      # show the command from its start
        missing = argspec.missing_required(self.spec, self.values())
        busy = self.worker is not None
        self.run_button.setEnabled(not missing and not busy)
        if busy:
            self.note.setText("Running.")
        elif missing:
            self.note.setText("Needs " + ", ".join(missing))
        else:
            self.note.setText("")

    # -- running -----------------------------------------------------------
    def run(self) -> None:
        from .runner import CommandWorker

        command = self.command()
        self.logged.emit("$ " + command)
        self.output.setPlainText("")
        guard = getattr(self, "guard", None)
        if guard is not None and not guard(self.argv()):
            return
        worker = CommandWorker(self.argv(), self.prog, self)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_thread_end)
        self.worker = worker
        self.refresh()
        worker.start()

    def _on_done(self, output: str, code: int) -> None:
        text = output or "(no output)"
        if code:
            text += f"\nexit code {code}"
        self.output.setPlainText(text)
        for line in output.splitlines():
            self.logged.emit(line)
        if code == 0:
            self.remember()
            written = self.written_files(output)
            if written:
                self.produced.emit(written)
        self.finished.emit(output, code)

    def _on_failed(self, tb: str) -> None:
        self.output.setPlainText(tb)
        self.logged.emit("The command raised an exception. See the output pane.")
        self.finished.emit(tb, 1)

    #: Options whose value names a file the command writes.
    OUTPUT_DESTS = ("out", "plot")

    @staticmethod
    def paths_in_output(output: str):
        """Return the paths named by the ``Wrote ...`` lines of ``output``.

        Some commands take the directory rather than the file and derive the
        name, so the form alone cannot say what appeared. Every such command
        announces each file on its own line beginning with ``Wrote``, with the
        path last, which covers ``Wrote /tmp/out/sheet.pdf``, ``Wrote
        iCalendar: /tmp/out/week.ics``, and ``Wrote plot to trend.png`` alike.
        A token that is not a file on disk is dropped, so a sentence that
        merely starts with the word is harmless.
        """
        found = []
        for line in (output or "").splitlines():
            stripped = line.strip()
            if not stripped.startswith("Wrote"):
                continue
            token = stripped.split()[-1]
            if token and Path(token).is_file():
                found.append(token)
        return found

    def written_files(self, output: str = ""):
        """Return the files this run wrote, from the form and from the output.

        The form knows the paths given as ``--out`` and ``--plot`` exactly, so
        those need no parsing. A path that is missing after a successful run is
        left out rather than reported, because the command line already said
        what it wrote.
        """
        values = self.values()
        found = []
        for dest in self.OUTPUT_DESTS:
            value = values.get(dest)
            if value and Path(str(value)).exists():
                found.append(str(value))
        for path in self.paths_in_output(output):
            if path not in found:
                found.append(path)
        return found

    def _on_thread_end(self) -> None:
        self.worker = None
        self.refresh()
