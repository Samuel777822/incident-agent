CREATE TABLE IF NOT EXISTS log_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, level TEXT, service TEXT, message TEXT,
  traceback TEXT, signature TEXT,
  incident_id INTEGER
);

CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  signature TEXT,
  status TEXT DEFAULT 'diagnosing',
  category TEXT,
  confidence TEXT,
  occurrences INTEGER DEFAULT 1,
  first_seen TEXT, last_seen TEXT,
  root_cause TEXT, explanation TEXT, report TEXT, pr_url TEXT, pr_number INTEGER,
  ci_status TEXT DEFAULT 'unknown',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS fixes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id INTEGER, branch TEXT, file_path TEXT, fixed_file TEXT, diff TEXT DEFAULT '',
  tests_passed INTEGER, ci_result TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
