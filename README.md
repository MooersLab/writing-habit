# writing-habit

[![Python versions](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://pypi.org/project/writing-schedule/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)


Track and compare planned versus actual academic writing effort. A companion to
[writing-schedule](https://github.com/MooersLab/writing-schedule-py).

The toolkit has three modules that share one SQLite database:

- **schedule** turns a weekly plain-text table into a plan (this lives in `writing-schedule`).
- **track** records the effort you actually spent, from a CSV, an ICS calendar, or by hand.
- **compare** reports the gap between plan and performance.

The database schema in `schema.sql` is the single contract between the modules,
so you can substitute other software at any stage. The core needs only the
Python standard library. ICS import, plotting, and Google Sheets are optional
extras.

## Install

```
pip install -e .            # core, standard library only
pip install -e '.[ics]'     # add ICS import
pip install -e '.[plot]'    # add the comparison plot
```

Plan import calls the real writing-schedule parser, so the plan and the
schedule never diverge. Until writing-schedule is on PyPI, install it from its
checkout:

```
pip install -e <path>/writing-schedule-py/writing_schedule
```

The other commands (initdb, track, compare) run without it.

## Quick start

```
writing-habit initdb --db habit.db
writing-habit plan import examples/my-week.org --week 2026-01-19 --db habit.db
writing-habit track import examples/actuals.csv --format csv --db habit.db
writing-habit compare --week 2026-01-19 --db habit.db
```

Add a session by hand at the end of the day:

```
writing-habit track add --day 2026-01-19 --project A --minutes 75 --category generative --db habit.db
```

## Tracking formats

The CSV template (`tracking-template.csv`) has columns
`date, start, end, minutes, project_code, category, note`. Enter either a start
and end time or a minutes value. Excel and Google Sheets both export CSV, so no
extra dependency is needed.

For calendar tracking, keep actuals in their own ICS calendar. Put the legend
code in the event summary in brackets, for example `[A] DNPH1 docking`, and put
the activity in the categories field.

## Marking safe and speculative projects

To drive the barbell view, add a risk tag to the end of a legend description in
the weekly table, in either the org-tag form `:safe:` or the parenthesis form
`(safe)`. Recognized tags are `safe`, `speculative`, and `support`.

```
| A: DNPH1 docking :safe:      |  |  |  |  |  |
| W: 2026words :speculative:   |  |  |  |  |  |
```

Inside a table cell `:safe:` is literal text, because org only reads `:tag:`
syntax on headlines, so it does not affect the table or its export. The plan
importer strips the tag before storing the description.

## What compare reports

- adherence per project, planned against actual
- the split across the three activities (generative, editing, support)
- the barbell split across safe and speculative work, which is the Rule 6 drift
- the current streak of consecutive writing days

## Scope

This is a tool for one person studying and improving their own writing habit,
an N-of-1 instrument. It records self-reported effort, not verified focus.

## License

MIT

## Status

Still under rapid development. Not in PyPI yet. I suggest coming back later.

## Funding


