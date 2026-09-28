"""Qt must not leak out of the gui package, nor past gui/qt.py inside it.

The library and the command line stay free of Qt, which is what lets the wheel
install without the graphical extra. Inside the graphical package every Qt name
enters through ``gui/qt.py``, so a later move to PyQt6 or PySide6 edits one
file. Both checks read the import statements with the ``ast`` module rather than
the raw text, because the prose of a docstring names the binding on purpose.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "writing_habit"
GUI = SRC / "gui"
BINDINGS = ("PyQt5", "PyQt6", "PySide2", "PySide6")


def _imported_modules(path: Path):
    """Return every module name imported by the file at ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _binding_imports(path: Path):
    return [m for m in _imported_modules(path)
            if any(m == b or m.startswith(b + ".") for b in BINDINGS)]


def test_no_library_module_imports_qt():
    offenders = {
        str(p.relative_to(SRC)): _binding_imports(p)
        for p in SRC.rglob("*.py")
        if GUI not in p.parents and p.parent != GUI and _binding_imports(p)
    }
    assert offenders == {}, f"Qt imported outside the gui package: {offenders}"


def test_only_the_qt_module_imports_the_binding():
    offenders = {
        p.name: _binding_imports(p)
        for p in GUI.rglob("*.py")
        if p.name != "qt.py" and _binding_imports(p)
    }
    assert offenders == {}, f"import Qt through gui/qt.py instead: {offenders}"


def test_the_entry_point_module_defers_the_qt_import():
    """`main` imports Qt inside the function, so a missing extra prints a hint."""
    text = (GUI / "app.py").read_text(encoding="utf-8")
    head = text.split("def main(", 1)[0]
    assert "from .qt import" not in head
    assert "from .mainwindow import" not in head
