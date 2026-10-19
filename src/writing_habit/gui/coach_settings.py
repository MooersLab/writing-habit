"""The Coach settings dialog: the local model, its server, and the model picker.

The coach's settings were stored values with no place in the window to change
them. This dialog shows them together. The model picker asks the server which
models it has installed, through Ollama's ``/api/tags`` or the ``/v1/models``
list of an OpenAI-style server, so the writer picks a model that is really
there rather than typing a name that leads to a 404. A name can still be typed,
for a model the writer is about to pull.
"""

from __future__ import annotations

from typing import List, Optional

from .. import coach
from . import settings
from .qt import QtWidgets

#: The interfaces offered, as (label, setting value).
API_CHOICES = [
    ("Ollama", "ollama"),
    ("OpenAI-style (LM Studio, llama.cpp)", "openai"),
]

#: The address each interface usually listens on.
DEFAULT_URLS = {"ollama": "http://localhost:11434", "openai": "http://localhost:1234"}


def same_model(a: str, b: str) -> bool:
    """Say whether two Ollama names name one model, as llama3.2 and llama3.2:latest do."""
    def plain(name):
        return name[:-len(":latest")] if name.endswith(":latest") else name
    return plain(a or "") == plain(b or "")


class CoachSettingsDialog(QtWidgets.QDialog):
    """Edit the coach's settings, and pick a model from the server's list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Coach settings")
        #: Lists the server's models.  A test replaces it.
        self.lister = coach.list_models
        layout = QtWidgets.QVBoxLayout(self)

        self.use_box = QtWidgets.QCheckBox("Use the local model")
        self.use_box.setToolTip(
            "Off, every coach task gives a plain answer written without a model, "
            "and nothing is sent anywhere")
        self.use_box.setChecked(settings.get("ai_debrief") == "true")
        layout.addWidget(self.use_box)

        form = QtWidgets.QFormLayout()
        self.api_box = QtWidgets.QComboBox()
        for label, value in API_CHOICES:
            self.api_box.addItem(label, value)
        values = [value for _label, value in API_CHOICES]
        current_api = settings.get("ai_api") or "ollama"
        self.api_box.setCurrentIndex(values.index(current_api)
                                     if current_api in values else 0)
        form.addRow("Server", self.api_box)
        self.url_edit = QtWidgets.QLineEdit(settings.get("ai_url") or DEFAULT_URLS["ollama"])
        form.addRow("Address", self.url_edit)
        model_row = QtWidgets.QHBoxLayout()
        self.model_box = QtWidgets.QComboBox()
        self.model_box.setEditable(True)
        self.model_box.setMinimumWidth(240)
        self.model_box.setEditText(settings.get("ai_model"))
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.setAutoDefault(False)
        self.refresh_button.setToolTip("Ask the server which models it has installed")
        self.refresh_button.clicked.connect(lambda: self.refresh())
        model_row.addWidget(self.model_box, 1)
        model_row.addWidget(self.refresh_button)
        form.addRow("Model", model_row)
        layout.addLayout(form)

        self.remote_box = QtWidgets.QCheckBox("Allow a server that is not on this computer")
        self.remote_box.setToolTip(
            "Leave this off to keep your records on this computer, as Rule 10 asks")
        self.remote_box.setChecked(settings.get("ai_allow_remote") == "true")
        layout.addWidget(self.remote_box)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #52514e;")
        layout.addWidget(self.status)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.api_box.currentIndexChanged.connect(lambda _i: self._api_changed())

    # -- reading the fields --------------------------------------------------
    def api(self) -> str:
        return self.api_box.currentData()

    def model(self) -> str:
        return self.model_box.currentText().strip()

    def _api_changed(self) -> None:
        """Move the address to the new interface's usual port when it was the old default."""
        if self.url_edit.text().strip() in DEFAULT_URLS.values():
            self.url_edit.setText(DEFAULT_URLS[self.api()])
        self.refresh()

    # -- the model list --------------------------------------------------------
    def refresh(self) -> Optional[List[str]]:
        """Fill the picker with the server's models.  Return them, or ``None``."""
        typed = self.model()
        try:
            names = self.lister(self.url_edit.text().strip(), self.api(),
                                allow_remote=self.remote_box.isChecked())
        except coach.CoachError as exc:
            self.status.setText(f"Could not list the models: {exc}. Is the server "
                                "running? You can still type a model name.")
            return None
        self.model_box.clear()
        self.model_box.addItems(names)
        match = next((i for i, n in enumerate(names) if same_model(n, typed)), None)
        if match is not None:
            self.model_box.setCurrentIndex(match)
        elif typed:
            self.model_box.setEditText(typed)
        if names:
            self.status.setText(f"{len(names)} model{'s' if len(names) != 1 else ''} "
                                "installed on the server.")
        else:
            hint = "Run ollama pull llama3.2" if self.api() == "ollama" else \
                "Load a model in the server"
            self.status.setText(f"The server has no models yet. {hint}, then press "
                                "Refresh.")
        if typed and match is None and names:
            self.status.setText(self.status.text() + f" {typed} is not among them.")
        return names

    # -- saving ------------------------------------------------------------------
    def save(self) -> None:
        settings.put("ai_debrief", "true" if self.use_box.isChecked() else "false")
        settings.put("ai_api", self.api())
        settings.put("ai_url", self.url_edit.text().strip() or DEFAULT_URLS[self.api()])
        if self.model():
            settings.put("ai_model", self.model())
        settings.put("ai_allow_remote", "true" if self.remote_box.isChecked() else "false")

    def accept(self) -> None:
        self.save()
        super().accept()
