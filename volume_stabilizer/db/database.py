"""SQLite connection and schema setup."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    audio_hash TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL,
    input_path TEXT NOT NULL,
    output_path TEXT NOT NULL,
    input_format TEXT NOT NULL,
    output_format TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'unprocessed',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tracks_audio_hash ON tracks(audio_hash);
CREATE INDEX IF NOT EXISTS idx_tracks_relative_path ON tracks(relative_path);
CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status);

CREATE TABLE IF NOT EXISTS analysis_results (
    track_id TEXT PRIMARY KEY,
    integrated_lufs REAL NOT NULL,
    true_peak_dbtp REAL NOT NULL,
    lra_lu REAL NOT NULL,
    target_gain_db REAL NOT NULL,
    limiter_required INTEGER NOT NULL DEFAULT 0,
    limiter_reduction_db REAL NOT NULL DEFAULT 0.0,
    bypass_eligible INTEGER NOT NULL DEFAULT 0,
    warning_code TEXT DEFAULT 'NONE',
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    target_dir TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    force INTEGER NOT NULL DEFAULT 0,
    total_tracks INTEGER DEFAULT 0,
    processed_tracks INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    bypass_count INTEGER DEFAULT 0,
    warn_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_items (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    track_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    message TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_items_job_id ON job_items(job_id);

CREATE TABLE IF NOT EXISTS backups (
    id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL,
    backup_path TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    backed_up_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE CASCADE
);
"""


def init_db(db_path: Path) -> None:
    """Initialize database schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Return a configured sqlite3 connection."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
