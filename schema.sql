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
-- risk_class supports the Rule 6 barbell analysis.
CREATE TABLE IF NOT EXISTS project (
    project_id  INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    description TEXT,
    risk_class  TEXT CHECK (risk_class IN ('safe','speculative','support')),
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
CREATE VIEW IF NOT EXISTS v_week_barbell AS
WITH pb AS (
        SELECT b.week_start, pr.risk_class, SUM(b.planned_min) AS planned_min
        FROM plan_block b JOIN project pr ON pr.project_id=b.project_id
        GROUP BY b.week_start, pr.risk_class),
sb AS (
        SELECT s.week_start, pr.risk_class, SUM(s.actual_min) AS actual_min
        FROM session s JOIN project pr ON pr.project_id=s.project_id
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
