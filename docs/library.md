# Using the library

Every command is a thin wrapper over a function you can call from your own
Python. The full signatures are in the [API reference](api.md); this page shows
the everyday paths. Each function takes an open connection, so you open the
database once and pass it around.

## Open and seed a database

```python
from writing_habit import db

con = db.connect("habit.db")   # row access by name, foreign keys on
db.init_db(con)                # create the schema and seed the activities
```

`connect` returns a `sqlite3.Connection` with `row_factory` set to
`sqlite3.Row`, so every query row is accessible by column name. `init_db` is
safe to run twice.

## Import a plan

```python
from writing_habit.plan_import import import_org

n = import_org(con, "examples/my-week.org", "2026-01-19")
print(n, "planned blocks")
```

`import_org` calls the real `writing-schedule` parser, so it needs the `plan`
extra. It fills the `project`, `category`, and `plan_block` tables and returns
the number of planned blocks for the week.

## Import or add sessions

```python
from writing_habit.track import csv_actuals, manual

csv_actuals.import_csv(con, "examples/actuals.csv")

manual.add_session(
    con, day="2026-01-19", project_code="A",
    minutes=75, category="generative", note="morning block",
)
```

The ICS reader is in `writing_habit.track.ics_actuals` and needs the `ics`
extra. Each importer records its provenance in `import_log`.

## Read the comparison views

```python
from writing_habit.compare import queries

for r in queries.week_project(con, "2026-01-19"):
    print(r["code"], r["planned_min"], r["actual_min"], r["adherence"])

print("streak:", queries.current_streak(con))
```

The four wrappers, namely `week_project`, `week_category`, `week_barbell`, and
`day_actual`, read the four views defined in the schema, so the library never
writes its own aggregation SQL. `current_streak` counts the run of consecutive
worked days ending at the latest one.

## Render the report and the dashboard

```python
from writing_habit.compare import report
from writing_habit.dashboard import write_dashboard

print(report.render_week(con, "2026-01-19"))     # the text report
report.write_plot(con, "2026-01-19", "week.png") # needs the plot extra

write_dashboard(con, "2026-01-19", "week.html")  # the HTML dashboard
```

`render_week` returns the plain-text report as a string. `write_plot` writes the
bar chart and needs the `plot` extra. `write_dashboard` writes the
self-contained HTML page and needs nothing beyond the standard library. For the
dashboard markup as a string without writing a file, call
`writing_habit.dashboard.dashboard_html(con, week)`.

## Decode a schedule code

```python
from writing_habit import name

decoded = name.decode("4gAAeAsA-gWW")
print(name.format_week(decoded))
total, by_activity, by_project = name.summary(decoded)
```

The `name` module uses the standard library alone. `decode` returns one entry
per day, `format_week` renders the week as text, and `summary` returns the block
counts.
