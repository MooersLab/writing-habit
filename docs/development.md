# Development

The package is small and dependency-light, so a working session needs only a
checkout and an editable install. This page covers the test suite, the
cross-port parity fixture, and building these docs.

## Testing

```
pip install -e '.[plan,ics,plot,dev]'
pytest
```

The suite has a few layers. `tests/test_schema.py` applies `schema.sql` to a
fresh database and checks the tables, the generated columns, and the four views.
`tests/test_name.py` covers the schedule-code decoder and the legend check.
`tests/test_mvp_loop.py` runs the whole loop end to end, namely `initdb`, plan
import, CSV track import, and compare, then asserts the adherence, the barbell
split, and the streak on a frozen example week. The plan-import test skips
itself when the `writing-schedule` package is absent, so the rest of the suite
still runs on a bare install.

## The cross-port parity fixture

`tests/test_dashboard.py` is the tuning fork between the two ports. It renders
the dashboard from `tests/fixtures/cross-port.db` for the week of 2026-01-19 and
asserts that the result is byte-identical to `tests/fixtures/dashboard.html`.
The same two fixture files ship with the Emacs Lisp twin, and its ERT suite
asserts against them too, so the Python package and the Emacs Lisp package stay
aligned to one fixed rendering rather than to each other. When you change the
dashboard markup, regenerate the fixture in both repositories in the same
commit, because a one-byte drift fails both suites.

## Building these docs

The documentation is a Sphinx project under `docs/`. Build it locally with the
documentation requirements installed:

```
pip install -r docs/requirements.txt
sphinx-build -b html docs docs/_build/html
```

Open `docs/_build/html/index.html` in a browser. Read the Docs builds the same
project from `.readthedocs.yaml`, which installs the package so autodoc can
import it, installs `docs/requirements.txt`, and fails the build on any warning.
Build with the warning flag before you push, so a warning surfaces on your
machine rather than on the Read the Docs build:

```
sphinx-build -W -b html docs docs/_build/html
```

## Regenerating the diagrams

The four Graphviz diagrams under `docs/imgs/` are built from the DOT sources in
`docs/_diagrams/`. Regenerate them with Graphviz installed:

```
for d in architecture schema-er workflow-loop schedule-code; do
  dot -Tpng -Gdpi=140 docs/_diagrams/$d.dot -o docs/imgs/$d.png
done
```

The two dashboard screenshots are renders of a dashboard HTML file, one in each
theme. The bar chart is the output of `compare --plot`.
