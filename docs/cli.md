# Command-line reference

The console command is `writing-habit`. It has six subcommands, and every
subcommand prints its own help with `writing-habit SUBCOMMAND --help`. Every
subcommand except `name` takes a `--db` path, so you can keep more than one
database.

```
writing-habit initdb    --db DB
writing-habit plan import TABLE --week DATE --db DB
writing-habit track import FILE --format csv|ics --db DB
writing-habit track add   --day DATE --project CODE [--minutes N] [--category C] [--start HH:MM] [--end HH:MM] [--note TEXT] --db DB
writing-habit compare   --week DATE [--plot FILE] --db DB
writing-habit dashboard --week DATE --out FILE --db DB
writing-habit name      CODE [--table TABLE]
```

Every `--week` and `--day` value is written as `YYYY-MM-DD`. A `--week` value
may be any date inside the target week, because the week snaps to the Monday on
or before that date.

## initdb

Create the schema and seed the three activities. Safe to run twice, because the
schema uses `IF NOT EXISTS` throughout.

```
writing-habit initdb --db habit.db
```

## plan import

Parse a weekly `writing-schedule` table and fill the `project`, `category`, and
`plan_block` tables for the week that contains `--week`. This subcommand needs
the `plan` extra, because it calls the real `writing-schedule` parser.

```
writing-habit plan import examples/my-week.org --week 2026-01-19 --db habit.db
```

## track import

Load actual sessions from a file. The `--format` option selects the reader.

| Option | Meaning |
|--------|---------|
| `--format csv` | Read the tracking CSV template. Standard library only. The default. |
| `--format ics` | Read an actuals ICS calendar. Needs the `ics` extra. |

```
writing-habit track import examples/actuals.csv --format csv --db habit.db
writing-habit track import examples/actuals.ics --format ics --db habit.db
```

## track add

Add one session by hand.

| Option | Meaning |
|--------|---------|
| `--day DATE` | The day of the session. Required. |
| `--project CODE` | The legend code the session worked on. Required. |
| `--minutes N` | The duration in minutes. Give this, or both `--start` and `--end`. |
| `--start HH:MM`, `--end HH:MM` | The clock times, from which the minutes are computed when `--minutes` is absent. |
| `--category C` | The activity, one of generative, editing, or support. Optional. |
| `--note TEXT` | A free-text note. Optional. |

```
writing-habit track add --day 2026-01-19 --project A --minutes 75 --category generative --db habit.db
```

## compare

Print the planned-versus-actual report for the week, by project, by activity,
and by barbell class, and print the current streak. With `--plot`, also write a
bar chart of planned against actual per project, which needs the `plot` extra.

```
writing-habit compare --week 2026-01-19 --db habit.db
writing-habit compare --week 2026-01-19 --db habit.db --plot week.png
```

## dashboard

Render a self-contained HTML dashboard for the week and write it to `--out`.
The file embeds its own style and script, so it opens in any browser with no
server. It carries a light theme and a dark theme. This is the same dashboard
the Emacs Lisp twin renders, byte for byte, from the same database.

```
writing-habit dashboard --week 2026-01-19 --out week.html --db habit.db
```

## name

Decode a schedule file-name code, and check its project letters against a table
legend. This subcommand needs no database. With no `--table`, the command looks
for `<code>.org` in the current directory.

```
writing-habit name 4gAAeAsA-gWW
writing-habit name 4gAAeAsA-gWW --table my-week.org
```
