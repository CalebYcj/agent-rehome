-- Synthetic schema fixture; no application database or user data is required.
CREATE TABLE projects (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, metadata TEXT NOT NULL,
 position INTEGER NOT NULL, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL
);
CREATE TABLE project_roots (project_id TEXT NOT NULL, position INTEGER NOT NULL, path TEXT NOT NULL);
CREATE TABLE threads (
 id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, created_at INTEGER NOT NULL,
 updated_at INTEGER NOT NULL, source TEXT NOT NULL, model_provider TEXT NOT NULL,
 cwd TEXT NOT NULL, title TEXT NOT NULL, sandbox_policy TEXT NOT NULL,
 approval_mode TEXT NOT NULL, tokens_used INTEGER NOT NULL DEFAULT 0,
 has_user_event INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
 cli_version TEXT NOT NULL, first_user_message TEXT NOT NULL, memory_mode TEXT NOT NULL,
 model TEXT, reasoning_effort TEXT, created_at_ms INTEGER, updated_at_ms INTEGER,
 thread_source TEXT, preview TEXT, recency_at INTEGER, recency_at_ms INTEGER,
 history_mode TEXT, name TEXT, project_id TEXT, originator TEXT
);
