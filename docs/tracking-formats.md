# Tracking formats

The track module records the sessions you actually worked. It accepts three
inputs, namely a CSV, an ICS calendar, and a one-line manual entry. All three
land in the same `session` table, so you can mix them within a week. The CSV
path uses the standard library alone, the ICS path needs the `ics` extra, and
the manual path needs nothing.

## The tracking CSV

The CSV template is `tracking-template.csv`, and its columns are `date`,
`start`, `end`, `minutes`, `project_code`, `category`, and `note`. Excel and
Google Sheets both export CSV, so this path is the universal bridge and it
needs no third-party library.

```
date,start,end,minutes,project_code,category,note
2026-01-19,04:00,05:30,,A,generative,morning block on DNPH1
2026-01-19,,,45,EM,support,end-of-day inbox triage entered by hand
2026-01-20,09:15,10:45,,B,editing,rewrite of results section
```

Enter either a start and an end time, or a minutes value. When both a start and
an end are present, the importer computes the minutes and stores the times.
When only minutes are present, which is the paper-then-transcribe path, the
importer stores the duration and leaves the times empty. The `project_code`
must match a legend code, and the `category` must be generative, editing, or
support, or left blank. Import it with:

```
writing-habit track import actuals.csv --format csv --db habit.db
```

## The actuals ICS

Keep your real work blocks in their own calendar so the plan and the actuals
never collide. Put the legend code in the event summary in brackets, for
example `[A] DNPH1 docking`, and put the activity in the event categories
field, for example `generative`. The `DTSTART` and `DTEND` give the real
minutes.

```
BEGIN:VEVENT
UID:wh-2026-01-19-a1@example
SUMMARY:[A] DNPH1 docking
CATEGORIES:generative
DTSTART:20260119T040500
DTEND:20260119T053000
END:VEVENT
```

The importer reads each `VEVENT` into one session and stores the event UID in
`source_ref`. An event whose summary carries no bracketed code is skipped,
because a code is what ties a session to a project. Import it with:

```
writing-habit track import actuals.ics --format ics --db habit.db
```

This path needs the `ics` extra, which pulls in `icalendar`.

## A session by hand

At the end of a day you can add a single session with no file:

```
writing-habit track add --day 2026-01-19 --project A --minutes 75 --category generative --db habit.db
```

Give either `--minutes`, or both `--start` and `--end`, and the importer
computes the minutes from the two times. The `--category` and `--note` options
are optional. A category left off means the session still counts toward the
project and the barbell views, and it is left out of the activity view.

## Marking safe and speculative projects

The barbell view needs to know which projects are safe and which are
speculative. Set that class in the weekly table, not in the tracker, by adding a
risk tag to the end of a legend description in either the org-tag form `:safe:`
or the parenthesis form `(safe)`. The recognized tags are `safe`,
`speculative`, and `support`.

```
| A: DNPH1 docking :safe:      |  |  |  |  |  |
| W: 2026words :risky:   |  |  |  |  |  |
```

Inside a table cell `:safe:` is literal text, because org reads `:tag:` syntax
only on headlines, so the tag does not affect the table or its export. Plan
import strips the tag before it stores the description, so the project name
stays clean.

## Sync from mytime.db

`writing-habit track sync` copies timed sessions straight from the `zTimeSpent`
table of a `mytime.db` time tracker, with no CSV file in between.

```sh
writing-habit track sync ~/6003TimeTracking/cb/mytime.db --db ~/org/writing-habit.db
```

| Option | Meaning |
|---|---|
| `--since`, `--until` | Days to copy. The default start is the first planned week. |
| `--scope semester` | Default. Keep the week's legend and the table's current semester project list. A semester project not in the week's legend counts as unplanned work. A writing project on no list is kept and labeled risky prospecting. |
| `--scope legend` | Keep only projects named in the week's table legend. Nothing is labeled risky prospecting. |
| `--scope all` | Also keep other projects, under their directory name, as unplanned work. A writing project on no list is still labeled risky prospecting. |
| `--prospect-range RANGES` | The project numbers that count as writing projects for the risky-prospecting label. The default is `0000-1999,2100-5999`. Give `none` to turn the label off. |
| `--table TABLE` | The table whose legend is read for weeks with no imported plan. The Track tab fills it with the table open in the Schedule tab. |
| `--dry-run` | Report what would change and write nothing. |

How a row is read:

- The project number (`ProjectID`, or the leading digits of `ProjectDirectory`)
  is matched against the four-digit numbers in the legend of the table that
  planned that week, so `1008` becomes the letter whose description begins
  `1008ToolsForQCrOfRNA`. A week with no imported plan reads the legend of
  `--table`, or else of the nearest planned week. A week with no legend at all
  is reported as such, and its rows are left out.
- `Activity` starting with g, e or r, or s gives generative, editing, or support.
  Otherwise the session takes the activity of an overlapping planned block.
- A row without both a start and an end time is skipped until it has them.
  An end before the start wraps past midnight.
- A writing project that appears in the tracker but on neither the week's
  legend nor the semester lists (current, carried over, or completed) is kept
  under its directory name and flagged `prospecting`. This is risky work.
  Prospecting on a project that has not earned a place in the plan has a high
  risk of being abandoned for lack of time. The plan comparisons leave it out,
  and the dashboard and the text report show it in a section of its own. The
  project number decides what counts as a writing project. The 6000s and above
  (commuting, administration, committees, mentoring, meetings, personal time)
  and the yearly journals in 2000-2099 are never prospecting. A rerun clears the
  flag once the project is added to a list.
- Each session stores `mytime.db:zTimeSpent:<id>` in `source_ref`. A rerun
  updates edited rows and never inserts a row twice.

The Track tab of the desktop app has the same form. It remembers the mytime.db
path, and **File > Sync from mytime.db** (Ctrl+Shift+Y) runs it with the
remembered paths. **File > Sync mytime.db at startup** runs it each time the app
opens. For the shell, `scripts/whsync.sh` defines a `whsync` function.
