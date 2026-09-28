# Installation

`writing-habit` runs on Python 3.9 and later. The core has no third-party
dependency, because the database, the CSV reader, and the report all use the
standard library alone. Three features are optional extras that you add only
when you need them.

## The core

Install the package from PyPI:

```
pip install writing-habit
```

This gives you `initdb`, `track` (CSV and by hand), `compare`, `dashboard`, and
`name`. None of these needs anything beyond the standard library. For
development, install from a checkout in editable mode instead:

```
pip install -e .
```

## The optional extras

Each extra pulls in one third-party package and unlocks one capability. Install
only the extras you use, because keeping the core dependency-free protects the
one-command install.

| Extra | Command | What it adds |
|-------|---------|--------------|
| `plan` | `pip install 'writing-habit[plan]'` | Plan import, through the real `writing-schedule` parser, so the plan and the schedule never diverge. |
| `ics` | `pip install 'writing-habit[ics]'` | Actuals import from an ICS calendar, through `icalendar`. |
| `plot` | `pip install 'writing-habit[plot]'` | The planned-versus-actual bar chart from `compare --plot`, through `matplotlib`. |
| `sheets` | `pip install 'writing-habit[sheets]'` | A live Google Sheets reader, through `gspread`, kept as an extra so it is never a core dependency. |
| `gui` | `pip install 'writing-habit[gui]'` | The point-and-click interface, through PyQt5, which also brings `writing-schedule`. See [the graphical interface](gui.md). |
| `preview` | `pip install 'writing-habit[preview]'` | A faithful in-window preview of the two HTML dashboards, through `PyQtWebEngine`. Optional even with `gui`. |

You may combine extras, for example `pip install 'writing-habit[plan,ics,plot]'`.

## The plan extra and writing-schedule

Plan import calls the real `writing-schedule` parser rather than a copy of it.
The `plan` extra installs
[writing-schedule](https://pypi.org/project/writing-schedule/) from PyPI, so
`pip install 'writing-habit[plan]'` resolves it for you. The other commands,
namely `initdb`, `track`, `compare`, `dashboard`, and `name`, run without it.

When you are working from a checkout of both projects, install `writing-schedule`
in editable mode instead so your local changes are picked up:

```
pip install -e <path>/writing-schedule-py/writing_schedule
```

## The graphical extra and its license

The `gui` extra installs PyQt5, and the optional `preview` extra installs
PyQtWebEngine. **Both are distributed under the GPL**, while the library, the
command line, and the documentation remain MIT, so installing either extra
brings GPL terms into your environment. An installation without them is
unaffected, which is why the graphical layer is an extra rather than a
dependency.

The `gui` extra also installs `writing-schedule`, because the table editor uses
its parser, its overlap check, and its scaffold.

```
pip install 'writing-habit[gui]'
writing-habit-gui
```

## Verifying the installation

```
writing-habit --help
```

The command prints the nine subcommands, namely `initdb`, `plan`, `track`,
`compare`, `history`, `dashboard`, `seasons`, `context`, and `name`. If the
console script is on your path, the installation is complete.
