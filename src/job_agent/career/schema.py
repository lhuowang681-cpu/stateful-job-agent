SCHEMA_VERSION = 5

DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS companies (
 id TEXT PRIMARY KEY, normalized_name TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
 priority TEXT NOT NULL DEFAULT 'normal', website_url TEXT, notes TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_tags (company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE, tag TEXT NOT NULL, PRIMARY KEY(company_id, tag));
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, company_id TEXT REFERENCES companies(id), legacy_job_id TEXT,
 title TEXT NOT NULL, city TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', source TEXT NOT NULL,
 current_state TEXT NOT NULL, session_dir TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_legacy ON jobs(legacy_job_id) WHERE legacy_job_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS stage_events (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, state TEXT NOT NULL,
 occurred_at TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL, source_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_stage_events_job_time ON stage_events(job_id, occurred_at);
CREATE TABLE IF NOT EXISTS interviews (
 id TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs(id), company_id TEXT REFERENCES companies(id), kind TEXT NOT NULL,
 round_label TEXT NOT NULL DEFAULT '', occurred_at TEXT, session_dir TEXT NOT NULL, artifact_path TEXT NOT NULL,
 ai_review_path TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_interviews_artifact ON interviews(session_dir, artifact_path);
CREATE TABLE IF NOT EXISTS artifact_links (
 id TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs(id), session_dir TEXT NOT NULL, artifact_type TEXT NOT NULL,
 relative_path TEXT NOT NULL, content_hash TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_artifact_unique ON artifact_links(job_id, session_dir, relative_path);
CREATE TABLE IF NOT EXISTS migration_runs (
 id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT, source_root TEXT NOT NULL, summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS migration_items (
 run_id TEXT NOT NULL REFERENCES migration_runs(id) ON DELETE CASCADE, source_key TEXT NOT NULL,
 source_path TEXT NOT NULL, content_hash TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT,
 decision TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(run_id, source_key)
);
DROP INDEX IF EXISTS idx_migration_success;
CREATE INDEX IF NOT EXISTS idx_migration_source_hash ON migration_items(source_key, content_hash);
CREATE TABLE IF NOT EXISTS migration_issues (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES migration_runs(id) ON DELETE CASCADE, kind TEXT NOT NULL,
 source_key TEXT NOT NULL, payload_json TEXT NOT NULL, resolution TEXT
);
CREATE TABLE IF NOT EXISTS durable_jobs (
 job_id TEXT PRIMARY KEY, company TEXT NOT NULL, normalized_company TEXT NOT NULL,
 title TEXT NOT NULL, location TEXT NOT NULL DEFAULT '', job_type TEXT NOT NULL DEFAULT '',
 source_type TEXT NOT NULL, source_uri TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_durable_jobs_company ON durable_jobs(normalized_company);
CREATE TABLE IF NOT EXISTS jd_snapshots (
 snapshot_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES durable_jobs(job_id) ON DELETE CASCADE,
 version INTEGER NOT NULL, text TEXT NOT NULL, content_hash TEXT NOT NULL,
 source_uri TEXT, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
 UNIQUE(job_id, version), UNIQUE(job_id, content_hash)
);
CREATE TABLE IF NOT EXISTS analysis_snapshots (
 analysis_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES durable_jobs(job_id) ON DELETE CASCADE,
 version INTEGER NOT NULL, jd_snapshot_id TEXT NOT NULL REFERENCES jd_snapshots(snapshot_id),
 producer_run_id TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL,
 UNIQUE(job_id, version), UNIQUE(job_id, producer_run_id)
);
CREATE TABLE IF NOT EXISTS career_application_links (
 job_id TEXT PRIMARY KEY REFERENCES durable_jobs(job_id) ON DELETE CASCADE,
 application_id TEXT NOT NULL UNIQUE, linked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interview_prep_snapshots (
 prep_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES durable_jobs(job_id) ON DELETE CASCADE,
 version INTEGER NOT NULL, application_id TEXT NOT NULL,
 analysis_id TEXT NOT NULL REFERENCES analysis_snapshots(analysis_id),
 producer_run_id TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL,
 UNIQUE(job_id, version), UNIQUE(job_id, producer_run_id)
);
CREATE TABLE IF NOT EXISTS job_workspace (
 job_id TEXT PRIMARY KEY REFERENCES durable_jobs(job_id) ON DELETE CASCADE,
 employment_type TEXT NOT NULL DEFAULT '', seniority TEXT NOT NULL DEFAULT '',
 job_family TEXT NOT NULL DEFAULT 'OTHER', source_identifier TEXT,
 canonical_url TEXT, normalized_title TEXT NOT NULL,
 normalized_location TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL, workspace_status TEXT NOT NULL DEFAULT 'NEW',
 analysis_status TEXT NOT NULL DEFAULT 'UNANALYZED', lineage TEXT NOT NULL,
 raw_metadata_json TEXT NOT NULL DEFAULT '{}', possible_duplicate_of TEXT,
 status_updated_at TEXT NOT NULL, status_source TEXT NOT NULL DEFAULT 'import'
);
CREATE INDEX IF NOT EXISTS idx_job_workspace_status
 ON job_workspace(workspace_status, analysis_status, job_family);
CREATE INDEX IF NOT EXISTS idx_job_workspace_source
 ON job_workspace(source_identifier, canonical_url);
CREATE TABLE IF NOT EXISTS job_identities (
 identity_type TEXT NOT NULL, identity_value TEXT NOT NULL,
 job_id TEXT NOT NULL REFERENCES durable_jobs(job_id) ON DELETE CASCADE,
 created_at TEXT NOT NULL,
 PRIMARY KEY(identity_type, identity_value)
);
CREATE INDEX IF NOT EXISTS idx_job_identities_job ON job_identities(job_id);
CREATE TABLE IF NOT EXISTS job_workspace_events (
 event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES durable_jobs(job_id),
 old_status TEXT NOT NULL, new_status TEXT NOT NULL, action_id TEXT NOT NULL UNIQUE,
 occurred_at TEXT NOT NULL, source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_batch_runs (
 batch_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, filters_json TEXT NOT NULL,
 job_ids_json TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
 failed INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
 started_at TEXT, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS job_batch_items (
 batch_id TEXT NOT NULL REFERENCES job_batch_runs(batch_id) ON DELETE CASCADE,
 job_id TEXT NOT NULL REFERENCES durable_jobs(job_id), status TEXT NOT NULL,
 analysis_id TEXT, error TEXT, started_at TEXT, finished_at TEXT,
 PRIMARY KEY(batch_id, job_id)
);
CREATE TABLE IF NOT EXISTS application_handoffs (
 job_id TEXT PRIMARY KEY REFERENCES durable_jobs(job_id),
 application_id TEXT NOT NULL UNIQUE, jd_snapshot_id TEXT NOT NULL,
 jd_version INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_workspace_metadata (
 key TEXT PRIMARY KEY, value TEXT NOT NULL
);
INSERT OR IGNORE INTO job_workspace_metadata(key, value)
 VALUES ('corpus_version', '0');
"""
