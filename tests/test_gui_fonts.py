"""The interface must never ask Qt for a font family by a generic name.

Qt has no family called ``Monospace`` on macOS or Windows.  Asking for one,
either by that name or through the CSS generic, makes Qt walk the whole font
database looking for an alias, which costs about 80 ms at startup and prints

    qt.qpa.fonts: Populating font family aliases took 82 ms.

These tests keep the generic out and confirm that the helper names a family
that exists.
"""
from __future__ import annotations

import ast
from pathlib import Path

GUI = Path(__file__).resolve().parents[1] / "src" / "writing_habit" / "gui"

GENERIC = ("monospace", "sans-serif", "serif", "cursive", "fantasy")


def test_no_generic_family_in_a_stylesheet():
    """No module asks for a generic family in a style sheet."""
    offenders = []
    for path in sorted(GUI.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            text = node.value.lower()
            if "font-family" in text and any(g in text for g in GENERIC):
                offenders.append(f"{path.name}:{node.lineno}: {node.value!r}")
    assert not offenders, "generic font family requested in:\n" + "\n".join(offenders)


def test_no_hard_coded_family_name():
    """No module names one platform's font, which would be wrong elsewhere.

    The check reads the calls rather than the text, because the helper's own
    docstring names Menlo and Consolas while explaining what it avoids.
    """
    named = {"menlo", "consolas", "courier", "courier new", "monaco",
             "dejavu sans mono", "liberation mono"}
    offenders = []
    for path in sorted(GUI.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name not in ("QFont", "setFamily", "setFamilies"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if arg.value.strip().lower() in named:
                        offenders.append(
                            f"{path.name}:{node.lineno}: {name}({arg.value!r})")
    assert not offenders, "font family hard coded in:\n" + "\n".join(offenders)


def test_fixed_font_names_a_real_family(qapp):
    """The helper returns a fixed-width family that the font database knows."""
    from writing_habit.gui.qt import QtGui, fixed_font

    font = fixed_font()
    family = font.family()
    assert family
    assert family.lower() not in GENERIC
    assert QtGui.QFontDatabase().families(), "no font families at all"
    # The hint makes Qt substitute a fixed-width face when the family the
    # database named is proportional, as happens on a stripped-down system.
    assert font.fixedPitch()
    assert font.styleHint() == QtGui.QFont.Monospace


def test_panels_use_the_fixed_font(qapp):
    """The command preview, its output pane, and the log all use the helper."""
    from writing_habit import cli
    from writing_habit.gui import argspec
    from writing_habit.gui.command_panel import CommandPanel
    from writing_habit.gui.mainwindow import MainWindow
    from writing_habit.gui.qt import fixed_font

    wanted = fixed_font().family()
    specs = argspec.commands(cli.build_parser())
    panel = CommandPanel(specs["compare"])
    assert panel.preview.font().family() == wanted
    assert panel.output.font().family() == wanted

    window = MainWindow()
    assert window.log.font().family() == wanted
