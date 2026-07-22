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
| W: 2026words :speculative:   |  |  |  |  |  |
```

Inside a table cell `:safe:` is literal text, because org reads `:tag:` syntax
only on headlines, so the tag does not affect the table or its export. Plan
import strips the tag before it stores the description, so the project name
stays clean.
