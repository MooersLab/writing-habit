-- writing-habit schema.sql
-- Shared SQLite schema for the three modules: schedule (plan), track (actual), compare.
-- Design goals: individual N-of-1 use, plain-text friendly, open interchange through ICS, CSV, and SQLite.
--
-- Conventions:
--   Dates are ISO 8601 text, YYYY-MM-DD.
--   Times are 24-hour HH:MM, zero padded.
--   Durations are integer minutes.
--   week_start is the ISO Monday of the week, computed for you as a generated column.
--
-- Requires SQLite 3.31 or newer for generated columns. Enable foreign keys per connection.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Reference tables
-- ---------------------------------------------------------------------------

-- The three writing activities from Rule 2.
CREATE TABLE IF NOT EXISTS category (
    category_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
                 CHECK (name IN ('generative','editing','support')),
    sort_order  INTEGER NOT NULL DEFAULT 0
);

-- The writing portfolio. code matches the schedule legend, for example A, B, EM, W2.
-- risk_class is the barbell class and is one of safe or speculative. Support is an
-- activity category, not a risk class, so a support project carries no risk_class.
CREATE TABLE IF NOT EXISTS project (
    project_id  INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    description TEXT,
    risk_class  TEXT CHECK (risk_class IN ('safe','speculative')),
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Fact tables
-- ---------------------------------------------------------------------------

-- Planned blocks written by the schedule module, one row per block per day.
CREATE TABLE IF NOT EXISTS plan_block (
    block_id    INTEGER PRIMARY KEY,
    day         TEXT    NOT NULL,                 -- ISO date
    start_time  TEXT    NOT NULL,                 -- HH:MM
    end_time    TEXT    NOT NULL,                 -- HH:MM
    project_id  INTEGER NOT NULL REFERENCES project(project_id),
    category_id INTEGER NOT NULL REFERENCES category(category_id),
    source      TEXT    NOT NULL DEFAULT 'schedule',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    planned_min INTEGER GENERATED ALWAYS AS (
        (CAST(substr(end_time,1,2)   AS INTEGER)*60 + CAST(substr(end_time,4,2)   AS INTEGER))
      - (CAST(substr(start_time,1,2) AS INTEGER)*60 + CAST(substr(start_time,4,2) AS INTEGER))
    ) VIRTUAL,
    week_start  TEXT GENERATED ALWAYS AS (
        date(day, '-' || ((CAST(strftime('%w', day) AS INTEGER) + 6) % 7) || ' days')
    ) VIRTUAL,
    UNIQUE (day, start_time, project_id)
);

-- Actual sessions written by the track module.
-- start_time and end_time may be null in spreadsheet mode, where only a duration is entered.
CREATE TABLE IF NOT EXISTS session (
    session_id  INTEGER PRIMARY KEY,
    day         TEXT    NOT NULL,                 -- ISO date
    start_time  TEXT,                             -- HH:MM or null
    end_time    TEXT,                             -- HH:MM or null
    actual_min  INTEGER NOT NULL CHECK (actual_min >= 0),
    project_id  INTEGER NOT NULL REFERENCES project(project_id),
    category_id INTEGER REFERENCES category(category_id),
    source      TEXT    NOT NULL CHECK (source IN ('ics','csv','manual','sqlite')),
    source_ref  TEXT,                             -- ICS UID, filename:row, etc.
    note        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    week_start  TEXT GENERATED ALWAYS AS (
        date(day, '-' || ((CAST(strftime('%w', day) AS INTEGER) + 6) % 7) || ' days')
    ) VIRTUAL
);

-- Provenance of every import, for reproducibility.
CREATE TABLE IF NOT EXISTS import_log (
    import_id     INTEGER PRIMARY KEY,
    imported_at   TEXT NOT NULL DEFAULT (datetime('now')),
    source_type   TEXT NOT NULL CHECK (source_type IN ('ics','csv','xlsx','sheets','sqlite','org')),
    source_name   TEXT,
    rows_read     INTEGER,
    rows_inserted INTEGER,
    tool_version  TEXT,
    note          TEXT
);

CREATE INDEX IF NOT EXISTS ix_plan_week    ON plan_block(week_start);
CREATE INDEX IF NOT EXISTS ix_plan_project ON plan_block(project_id);
CREATE INDEX IF NOT EXISTS ix_sess_week    ON session(week_start);
CREATE INDEX IF NOT EXISTS ix_sess_project ON session(project_id);

-- Seed the three activities.
INSERT OR IGNORE INTO category (category_id, name, sort_order) VALUES
    (1,'generative',1),
    (2,'editing',2),
    (3,'support',3);

-- ---------------------------------------------------------------------------
-- Comparison views (the compare module reads these).
-- FULL OUTER JOIN is avoided so the views run on older SQLite builds.
-- ---------------------------------------------------------------------------

-- Planned versus actual minutes per week and project, with adherence ratio. Feeds Rule 10.
CREATE VIEW IF NOT EXISTS v_week_project AS
WITH keys AS (
        SELECT week_start, project_id FROM plan_block
        UNION
        SELECT week_start, project_id FROM session
),
p AS (SELECT week_start, project_id, SUM(planned_min) AS planned_min
        FROM plan_block GROUP BY week_start, project_id),
a AS (SELECT week_start, project_id, SUM(actual_min)  AS actual_min
        FROM session   GROUP BY week_start, project_id)
SELECT  k.week_start,
        pr.code,
        pr.description,
        pr.risk_class,
        COALESCE(p.planned_min,0) AS planned_min,
        COALESCE(a.actual_min,0)  AS actual_min,
        COALESCE(a.actual_min,0) - COALESCE(p.planned_min,0) AS diff_min,
        CASE WHEN COALESCE(p.planned_min,0)=0 THEN NULL
             ELSE ROUND(1.0*COALESCE(a.actual_min,0)/p.planned_min, 2) END AS adherence
FROM keys k
LEFT JOIN p  ON p.week_start=k.week_start AND p.project_id=k.project_id
LEFT JOIN a  ON a.week_start=k.week_start AND a.project_id=k.project_id
JOIN project pr ON pr.project_id=k.project_id
ORDER BY k.week_start, pr.code;

-- Planned versus actual minutes per week and activity. Feeds the Rule 2 balance.
CREATE VIEW IF NOT EXISTS v_week_category AS
WITH keys AS (
        SELECT week_start, category_id FROM plan_block
        UNION
        SELECT week_start, category_id FROM session WHERE category_id IS NOT NULL
),
p AS (SELECT week_start, category_id, SUM(planned_min) AS planned_min
        FROM plan_block GROUP BY week_start, category_id),
a AS (SELECT week_start, category_id, SUM(actual_min)  AS actual_min
        FROM session WHERE category_id IS NOT NULL GROUP BY week_start, category_id)
SELECT  k.week_start,
        c.name AS category,
        COALESCE(p.planned_min,0) AS planned_min,
        COALESCE(a.actual_min,0)  AS actual_min
FROM keys k
LEFT JOIN p ON p.week_start=k.week_start AND p.category_id=k.category_id
LEFT JOIN a ON a.week_start=k.week_start AND a.category_id=k.category_id
JOIN category c ON c.category_id=k.category_id
ORDER BY k.week_start, c.sort_order;

-- Planned versus actual minutes per week and barbell class. Detects the Rule 6 drift.
-- Only the two risk classes, safe and speculative, take part in the barbell. Support
-- is an activity category, not a risk class, so support and untagged projects are
-- excluded here.
CREATE VIEW IF NOT EXISTS v_week_barbell AS
WITH pb AS (
        SELECT b.week_start, pr.risk_class, SUM(b.planned_min) AS planned_min
        FROM plan_block b JOIN project pr ON pr.project_id=b.project_id
        WHERE pr.risk_class IN ('safe','speculative')
        GROUP BY b.week_start, pr.risk_class),
sb AS (
        SELECT s.week_start, pr.risk_class, SUM(s.actual_min) AS actual_min
        FROM session s JOIN project pr ON pr.project_id=s.project_id
        WHERE pr.risk_class IN ('safe','speculative')
        GROUP BY s.week_start, pr.risk_class),
keys AS (
        SELECT week_start, risk_class FROM pb
        UNION
        SELECT week_start, risk_class FROM sb)
SELECT  k.week_start,
        k.risk_class,
        COALESCE(pb.planned_min,0) AS planned_min,
        COALESCE(sb.actual_min,0)  AS actual_min
FROM keys k
LEFT JOIN pb ON pb.week_start=k.week_start AND pb.risk_class IS k.risk_class
LEFT JOIN sb ON sb.week_start=k.week_start AND sb.risk_class IS k.risk_class
ORDER BY k.week_start, k.risk_class;

-- Actual minutes per day, with a worked flag. The compare module counts streaks from this. Feeds Rule 10.
CREATE VIEW IF NOT EXISTS v_day_actual AS
SELECT  day,
        week_start,
        SUM(actual_min) AS actual_min,
        CASE WHEN SUM(actual_min) > 0 THEN 1 ELSE 0 END AS worked
FROM session
GROUP BY day, week_start
ORDER BY day;

-- ---------------------------------------------------------------------------
-- Cross-week views for the adherence tracker (build step 1).
-- These carry every week in the database, so the history reader and the weekly
-- plots select a range from them rather than one week.
-- ---------------------------------------------------------------------------

-- Overall adherence per week: the ratio of the summed actual minutes to the
-- summed planned minutes across all projects. This weights a project by its
-- size, so a large project dominates the number. First headline series.
CREATE VIEW IF NOT EXISTS v_week_overall AS
WITH p AS (SELECT week_start, SUM(planned_min) AS planned_min
             FROM plan_block GROUP BY week_start),
     a AS (SELECT week_start, SUM(actual_min)  AS actual_min
             FROM session    GROUP BY week_start),
     keys AS (SELECT week_start FROM p UNION SELECT week_start FROM a)
SELECT  k.week_start,
        COALESCE(p.planned_min,0) AS planned_min,
        COALESCE(a.actual_min,0)  AS actual_min,
        CASE WHEN COALESCE(p.planned_min,0)=0 THEN NULL
             ELSE ROUND(1.0*COALESCE(a.actual_min,0)/p.planned_min, 2) END AS adherence
FROM keys k
LEFT JOIN p ON p.week_start=k.week_start
LEFT JOIN a ON a.week_start=k.week_start
ORDER BY k.week_start;

-- Mean of the per-project adherence ratios per week. This weights every project
-- equally rather than by size, so a small starved project counts as much as a
-- large one. AVG ignores a project with no planned minutes. Second headline series.
CREATE VIEW IF NOT EXISTS v_week_project_mean AS
SELECT  week_start,
        ROUND(AVG(adherence), 2) AS mean_adherence,
        COUNT(adherence)         AS n_projects
FROM v_week_project
WHERE adherence IS NOT NULL
GROUP BY week_start
ORDER BY week_start;

-- Planned versus actual minutes per week, project, and activity, with the per-cell
-- adherence ratio. This is the base for the per-category series.
CREATE VIEW IF NOT EXISTS v_week_project_category AS
WITH keys AS (
        SELECT week_start, project_id, category_id FROM plan_block
        UNION
        SELECT week_start, project_id, category_id FROM session WHERE category_id IS NOT NULL
),
p AS (SELECT week_start, project_id, category_id, SUM(planned_min) AS planned_min
        FROM plan_block GROUP BY week_start, project_id, category_id),
a AS (SELECT week_start, project_id, category_id, SUM(actual_min)  AS actual_min
        FROM session WHERE category_id IS NOT NULL
        GROUP BY week_start, project_id, category_id)
SELECT  k.week_start,
        pr.code,
        c.name AS category,
        COALESCE(p.planned_min,0) AS planned_min,
        COALESCE(a.actual_min,0)  AS actual_min,
        CASE WHEN COALESCE(p.planned_min,0)=0 THEN NULL
             ELSE ROUND(1.0*COALESCE(a.actual_min,0)/p.planned_min, 2) END AS adherence
FROM keys k
LEFT JOIN p ON p.week_start=k.week_start AND p.project_id=k.project_id AND p.category_id=k.category_id
LEFT JOIN a ON a.week_start=k.week_start AND a.project_id=k.project_id AND a.category_id=k.category_id
JOIN project  pr ON pr.project_id=k.project_id
JOIN category c  ON c.category_id=k.category_id
ORDER BY k.week_start, pr.code, c.sort_order;

-- Mean per-project adherence within each activity, per week. One row per week and
-- category. The generative, editing, and support rows each feed their own plot.
CREATE VIEW IF NOT EXISTS v_week_category_mean AS
SELECT  week_start,
        category,
        ROUND(AVG(adherence), 2) AS mean_adherence,
        COUNT(adherence)         AS n_projects
FROM v_week_project_category
WHERE adherence IS NOT NULL
GROUP BY week_start, category
ORDER BY week_start, category;

-- ---------------------------------------------------------------------------
-- Cross-week grouping (build step 3, the second dashboard). Two small metadata
-- tables and three rollups that group the weekly overall series by month, by
-- event context, and by the schedule file-name code.
-- ---------------------------------------------------------------------------

-- One row per planned week, capturing the schedule file that produced it. The
-- schedule_code is the file-name code from the naming convention, used to group
-- weeks that share a plan shape.
CREATE TABLE IF NOT EXISTS plan_week (
    week_start    TEXT PRIMARY KEY,
    schedule_code TEXT,
    table_path    TEXT,
    imported_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Free tags that mark the context of a week, for example a national meeting, a
-- teaching block, or a data-collection push. A week may carry several tags.
CREATE TABLE IF NOT EXISTS week_context (
    week_start TEXT NOT NULL,
    tag        TEXT NOT NULL,
    note       TEXT,
    PRIMARY KEY (week_start, tag)
);

CREATE INDEX IF NOT EXISTS ix_context_tag ON week_context(tag);

-- Overall adherence per calendar month, rolled up from the weekly series.
CREATE VIEW IF NOT EXISTS v_month_overall AS
SELECT  substr(week_start, 1, 7) AS month,
        SUM(planned_min) AS planned_min,
        SUM(actual_min)  AS actual_min,
        COUNT(*)         AS weeks,
        CASE WHEN SUM(planned_min)=0 THEN NULL
             ELSE ROUND(1.0*SUM(actual_min)/SUM(planned_min), 2) END AS adherence
FROM v_week_overall
GROUP BY month
ORDER BY month;

-- Overall adherence per context tag, summed over the weeks that carry the tag.
-- A week counts once per tag it carries.
CREATE VIEW IF NOT EXISTS v_context_overall AS
SELECT  c.tag,
        SUM(o.planned_min) AS planned_min,
        SUM(o.actual_min)  AS actual_min,
        COUNT(*)           AS weeks,
        CASE WHEN SUM(o.planned_min)=0 THEN NULL
             ELSE ROUND(1.0*SUM(o.actual_min)/SUM(o.planned_min), 2) END AS adherence
FROM week_context c
JOIN v_week_overall o ON o.week_start = c.week_start
GROUP BY c.tag
ORDER BY c.tag;

-- Overall adherence per schedule code, summed over the weeks that used it.
CREATE VIEW IF NOT EXISTS v_schedule_overall AS
SELECT  w.schedule_code,
        SUM(o.planned_min) AS planned_min,
        SUM(o.actual_min)  AS actual_min,
        COUNT(*)           AS weeks,
        CASE WHEN SUM(o.planned_min)=0 THEN NULL
             ELSE ROUND(1.0*SUM(o.actual_min)/SUM(o.planned_min), 2) END AS adherence
FROM plan_week w
JOIN v_week_overall o ON o.week_start = w.week_start
WHERE w.schedule_code IS NOT NULL
GROUP BY w.schedule_code
ORDER BY w.schedule_code;
