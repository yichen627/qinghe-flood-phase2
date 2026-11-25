"""schema 1→2的事务迁移；不重建或清空既有事件和预报。"""

SCHEMA_V2 = '''
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS audit_log(
 id TEXT PRIMARY KEY,created_at TEXT NOT NULL,actor TEXT NOT NULL,
 action TEXT NOT NULL,entity_id TEXT NOT NULL,detail_json TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT,'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT,'audit is append-only'); END;
CREATE TABLE IF NOT EXISTS model_versions(
 id TEXT PRIMARY KEY,name TEXT NOT NULL,image_ref TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS parameter_sets(
 id TEXT PRIMARY KEY,name TEXT NOT NULL,params_json TEXT NOT NULL,sha256 TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS params_no_update BEFORE UPDATE ON parameter_sets BEGIN SELECT RAISE(ABORT,'parameters are immutable'); END;
CREATE TRIGGER IF NOT EXISTS params_no_delete BEFORE DELETE ON parameter_sets BEGIN SELECT RAISE(ABORT,'parameters are immutable'); END;
CREATE TABLE IF NOT EXISTS schemes(
 id TEXT PRIMARY KEY,name TEXT NOT NULL,parameter_id TEXT NOT NULL REFERENCES parameter_sets(id),
 model_version TEXT NOT NULL REFERENCES model_versions(id),created_at TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS system_state(key TEXT PRIMARY KEY,value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products(
 id TEXT PRIMARY KEY,forecast_id TEXT NOT NULL REFERENCES forecasts(id),title TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('DRAFT','REVIEWED','SIGNED','PUBLISHED')),
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,content_json TEXT NOT NULL,content_sha256 TEXT NOT NULL,
 review_note TEXT,reviewed_by TEXT,reviewed_at TEXT,signed_by TEXT,signed_at TEXT,published_by TEXT,published_at TEXT);
CREATE TRIGGER IF NOT EXISTS product_no_content_change BEFORE UPDATE OF content_json,content_sha256,title,forecast_id ON products
BEGIN SELECT RAISE(ABORT,'product content is immutable'); END;
CREATE TABLE IF NOT EXISTS schedules(
 id TEXT PRIMARY KEY,name TEXT NOT NULL,event_id TEXT NOT NULL REFERENCES events(id),scheme_id TEXT REFERENCES schemes(id),
 interval_seconds INTEGER NOT NULL,enabled INTEGER NOT NULL,next_run_at TEXT NOT NULL,created_at TEXT NOT NULL,last_error TEXT);
CREATE TABLE IF NOT EXISTS schedule_runs(
 id TEXT PRIMARY KEY,schedule_id TEXT NOT NULL REFERENCES schedules(id),scheduled_for TEXT NOT NULL,
 created_at TEXT NOT NULL,forecast_id TEXT REFERENCES forecasts(id),error TEXT,UNIQUE(schedule_id,scheduled_for));
CREATE TABLE IF NOT EXISTS qc_status(
 id TEXT PRIMARY KEY REFERENCES events(id),created_at TEXT NOT NULL,issues_json TEXT NOT NULL,rules_sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS qc_scans(
 id TEXT PRIMARY KEY,created_at TEXT NOT NULL,checked_count INTEGER NOT NULL,error_count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS alerts(
 id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id),signature TEXT NOT NULL,
 created_at TEXT NOT NULL,issues_json TEXT NOT NULL,acknowledged_by TEXT,acknowledged_at TEXT,UNIQUE(event_id,signature));
CREATE TABLE IF NOT EXISTS notification_outbox(
 id TEXT PRIMARY KEY,created_at TEXT NOT NULL,dedup_key TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,
 reference_id TEXT NOT NULL,payload_json TEXT NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
 available_at TEXT NOT NULL,delivered_at TEXT,last_error TEXT);
CREATE TABLE IF NOT EXISTS inbox(
 id TEXT PRIMARY KEY,outbox_id TEXT NOT NULL UNIQUE REFERENCES notification_outbox(id),created_at TEXT NOT NULL,
 recipient TEXT NOT NULL,payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runtime_status(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,detail_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS schedule_due ON schedules(enabled,next_run_at);
CREATE INDEX IF NOT EXISTS outbox_due ON notification_outbox(status,available_at);
CREATE TRIGGER IF NOT EXISTS forecast_snapshot_immutable BEFORE UPDATE OF snapshot_json,event_id,scheme_id ON forecasts
BEGIN SELECT RAISE(ABORT,'forecast snapshot is immutable'); END;
PRAGMA user_version=2;
COMMIT;
'''
