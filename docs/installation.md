# Installation

`writing-habit` runs on Python 3.9 and later. The core has no third-party
dependency, because the database, the CSV reader, and the report all use the
standard library alone. Three features are optional extras that you add only
when you need them.

## The core

Install the package in editable mode from a checkout, which is the usual choice
while the toolkit is young:

```
pip install -e .
```

This gives you `initdb`, `track` (CSV and by hand), `compare`, `dashboard`, and
`name`. None of these needs anything beyond the standard library.

## The optional extras

Each extra pulls in one third-party package and unlocks one capability. Install
only the extras you use, because keeping the core dependency-free protects the
one-command install.

| Extra | Command | What it adds |
|-------|---------|--------------|
| `plan` | `pip install -e '.[plan]'` | Plan import, through the real `writing-schedule` parser, so the plan and the schedule never diverge. |
| `ics` | `pip install -e '.[ics]'` | Actuals import from an ICS calendar, through `icalendar`. |
| `plot` | `pip install -e '.[plot]'` | The planned-versus-actual bar chart from `compare --plot`, through `matplotlib`. |
| `sheets` | `pip install -e '.[sheets]'` | A live Google Sheets reader, through `gspread`, kept as an extra so it is never a core dependency. |

You may combine extras, for example `pip install -e '.[plan,ics,plot]'`.

## Installing writing-schedule for plan import

Plan import calls the real `writing-schedule` parser rather than a copy of it.
Until `writing-schedule` is published to PyPI, install it from its checkout so
the `plan` extra resolves:

```
pip install -e <path>/writing-schedule-py/writing_schedule
```

The other commands, namely `initdb`, `track`, `compare`, `dashboard`, and
`name`, run without it.

## Verifying the installation

```
writing-habit --help
```

The command prints the six subcommands, namely `initdb`, `plan`, `track`,
`compare`, `dashboard`, and `name`. If the console script is on your path, the
installation is complete.
