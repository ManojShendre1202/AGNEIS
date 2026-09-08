-- AGNIES v0 — SQLite schema
-- Built incrementally, one table at a time, as each is actually needed.
-- Run once against agnies.db (DB Browser: Execute SQL tab, then Write Changes).

-- Raw task spec input + its one-time LLM-extracted structured form (see PLAN.md §8).
CREATE TABLE task_specs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_filename TEXT NOT NULL,
    raw_text        TEXT NOT NULL,
    extracted_json  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',   -- pending -> extracted -> verified
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- INCREMENT 2 — Prime bootstrap (roster + resource pools + research).
-- task_specs already exists in agnies.db, so its new column needs an
-- explicit ALTER TABLE; the rest are new tables from CREATE TABLE.
-- Run everything below this line via DB Browser's Execute SQL tab,
-- then Write Changes.
-- ============================================================

ALTER TABLE task_specs ADD COLUMN prime_overall_reasoning TEXT;

-- Stage 1 of Prime's bootstrap: grounded research findings, before the roster
-- is decided. Free text, not schema-constrained, since research output isn't
-- meant to be parsed downstream — only read by Prime itself in Stage 2.
CREATE TABLE research_notes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_spec_id INTEGER NOT NULL REFERENCES task_specs(id),
    topic        TEXT NOT NULL,          -- what Prime was researching
    findings     TEXT NOT NULL,          -- free-text research output
    sources      TEXT,                   -- JSON list of citation URLs, if the grounding tool returned any
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Stage 2 of Prime's bootstrap: the reasoning-agent roster (§3, §6).
CREATE TABLE roster (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    task_spec_id   INTEGER NOT NULL REFERENCES task_specs(id),
    role_name      TEXT NOT NULL,
    mandate        TEXT NOT NULL,
    success_metric TEXT NOT NULL,
    model_tier     TEXT NOT NULL,
    budget_calls   INTEGER NOT NULL,     -- system-assigned default, never set by Prime itself
    memory_scope   TEXT NOT NULL,        -- JSON list of state keys this role reads/writes
    owned_paths    TEXT NOT NULL DEFAULT '[]',  -- JSON list of sandbox-relative paths this role may write to
    status         TEXT NOT NULL DEFAULT 'active',   -- active -> retired
    reasoning      TEXT NOT NULL,        -- why Prime decided this role is needed
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    retired_at     TEXT
);

-- Stage 2 of Prime's bootstrap: non-agent capacity pools (§4 — never LLM agents).
CREATE TABLE resource_pools (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    task_spec_id   INTEGER NOT NULL REFERENCES task_specs(id),
    name           TEXT NOT NULL,
    unit           TEXT NOT NULL,
    initial_count  REAL NOT NULL,
    owner_role     TEXT NOT NULL,        -- must match a role_name in roster
    reasoning      TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- INCREMENT 3 — shared fact-resolution cache (experiments/agent_shell.py).
-- Agents check this before re-searching/re-asking the same real-world fact
-- (utility maps, bus routes, signal timings). Also created idempotently by
-- pipeline/10_add_resolved_facts_table.py.
-- ============================================================

CREATE TABLE IF NOT EXISTS resolved_facts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_spec_id     INTEGER NOT NULL REFERENCES task_specs(id),
    topic            TEXT NOT NULL,
    value            TEXT NOT NULL,
    status           TEXT NOT NULL,        -- 'resolved' or 'unresolved'
    source           TEXT,                 -- citation/basis, or 'none' if unresolved
    resolved_by_role TEXT NOT NULL,        -- which role's search/ask produced this
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- INCREMENT 4 — shared stack registry + per-role activity log
-- (SANDBOX_AGENT_PLAN.md follow-up: sqlite3-vs-SQLAlchemy mismatch found in
-- session 1 showed roles need a shared, checked-first record of tech
-- choices, same discipline as resolved_facts but for team decisions rather
-- than real-world facts; role_activity gives each role continuity of its
-- own past writes/installs/fixes across turns instead of re-deriving it
-- from conversation text every time).
-- ============================================================

CREATE TABLE IF NOT EXISTS stack_decisions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_spec_id     INTEGER NOT NULL REFERENCES task_specs(id),
    package          TEXT NOT NULL,        -- e.g. 'sqlite3', 'SQLAlchemy', 'FastAPI'
    version           TEXT,                 -- optional, e.g. '2.0'
    decided_by_role  TEXT NOT NULL,        -- which role first committed to this
    reasoning        TEXT NOT NULL,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS role_activity (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_spec_id     INTEGER NOT NULL REFERENCES task_specs(id),
    role_name        TEXT NOT NULL,
    action_type      TEXT NOT NULL,        -- 'write_file' | 'install_package' | 'run_shell' | 'bug_fix'
    detail           TEXT NOT NULL,        -- e.g. path + spec, or command + outcome
    turn             INTEGER,              -- which conversation step this happened on
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
