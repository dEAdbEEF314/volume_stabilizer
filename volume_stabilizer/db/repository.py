"""Database repository for tracks, analysis, jobs, and backups."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import List, Optional, Tuple
from .database import get_connection
from .models import TrackRecord, AnalysisRecord, JobRecord


class Repository:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def get_track_by_hash(self, audio_hash: str) -> Optional[TrackRecord]:
        with get_connection(self.db_path) as conn:
            cur = conn.execute("SELECT * FROM tracks WHERE audio_hash = ?", (audio_hash,))
            row = cur.fetchone()
            if not row:
                return None
            return TrackRecord(**dict(row))

    def get_track_by_id(self, track_id: str) -> Optional[TrackRecord]:
        with get_connection(self.db_path) as conn:
            cur = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
            row = cur.fetchone()
            if not row:
                return None
            return TrackRecord(**dict(row))

    def upsert_track(
        self,
        audio_hash: str,
        relative_path: str,
        input_path: str,
        output_path: str,
        input_format: str,
        output_format: str,
        file_size: int,
        mtime: float,
        status: str = "unprocessed",
    ) -> TrackRecord:
        with get_connection(self.db_path) as conn:
            existing = self.get_track_by_hash(audio_hash)
            if existing:
                conn.execute(
                    """
                    UPDATE tracks
                    SET relative_path = ?, input_path = ?, output_path = ?,
                        file_size = ?, mtime = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (relative_path, input_path, output_path, file_size, mtime, existing.id),
                )
                conn.commit()
                return self.get_track_by_id(existing.id)

            new_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO tracks (id, audio_hash, relative_path, input_path, output_path,
                                    input_format, output_format, file_size, mtime, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (new_id, audio_hash, relative_path, input_path, output_path,
                 input_format, output_format, file_size, mtime, status),
            )
            conn.commit()
            return self.get_track_by_id(new_id)

    def update_track_status(self, track_id: str, status: str) -> None:
        with get_connection(self.db_path) as conn:
            conn.execute(
                "UPDATE tracks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, track_id),
            )
            conn.commit()

    def save_analysis(
        self,
        track_id: str,
        integrated_lufs: float,
        true_peak_dbtp: float,
        lra_lu: float,
        target_gain_db: float,
        limiter_required: bool,
        limiter_reduction_db: float,
        bypass_eligible: bool,
        warning_code: str = "NONE",
    ) -> None:
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO analysis_results (
                    track_id, integrated_lufs, true_peak_dbtp, lra_lu,
                    target_gain_db, limiter_required, limiter_reduction_db,
                    bypass_eligible, warning_code, analyzed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(track_id) DO UPDATE SET
                    integrated_lufs = excluded.integrated_lufs,
                    true_peak_dbtp = excluded.true_peak_dbtp,
                    lra_lu = excluded.lra_lu,
                    target_gain_db = excluded.target_gain_db,
                    limiter_required = excluded.limiter_required,
                    limiter_reduction_db = excluded.limiter_reduction_db,
                    bypass_eligible = excluded.bypass_eligible,
                    warning_code = excluded.warning_code,
                    analyzed_at = CURRENT_TIMESTAMP
                """,
                (track_id, integrated_lufs, true_peak_dbtp, lra_lu,
                 target_gain_db, int(limiter_required), limiter_reduction_db,
                 int(bypass_eligible), warning_code),
            )
            conn.commit()

    def get_analysis(self, track_id: str) -> Optional[AnalysisRecord]:
        with get_connection(self.db_path) as conn:
            cur = conn.execute("SELECT * FROM analysis_results WHERE track_id = ?", (track_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["limiter_required"] = bool(d["limiter_required"])
            d["bypass_eligible"] = bool(d["bypass_eligible"])
            return AnalysisRecord(**d)

    def create_job(self, job_type: str, target_dir: str, force: bool = False) -> JobRecord:
        job_id = str(uuid.uuid4())
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, job_type, target_dir, force, status)
                VALUES (?, ?, ?, ?, 'PENDING')
                """,
                (job_id, job_type, target_dir, int(force)),
            )
            conn.commit()
            return self.get_job(job_id)

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with get_connection(self.db_path) as conn:
            cur = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["force"] = bool(d["force"])
            return JobRecord(**d)

    def update_job_progress(
        self,
        job_id: str,
        total_tracks: int,
        processed_tracks: int,
        success_count: int,
        bypass_count: int,
        warn_count: int,
        error_count: int,
        status: Optional[str] = None,
    ) -> None:
        with get_connection(self.db_path) as conn:
            query = """
                UPDATE jobs
                SET total_tracks = ?, processed_tracks = ?, success_count = ?,
                    bypass_count = ?, warn_count = ?, error_count = ?
            """
            params: list = [total_tracks, processed_tracks, success_count, bypass_count, warn_count, error_count]
            if status:
                query += ", status = ?"
                params.append(status)
                if status in ("COMPLETED", "FAILED", "CANCELLED"):
                    query += ", finished_at = CURRENT_TIMESTAMP"
            query += " WHERE id = ?"
            params.append(job_id)
            conn.execute(query, params)
            conn.commit()

    def record_backup(self, track_id: str, backup_path: str, file_size: int) -> None:
        backup_id = str(uuid.uuid4())
        with get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO backups (id, track_id, backup_path, file_size) VALUES (?, ?, ?, ?)",
                (backup_id, track_id, backup_path, file_size),
            )
            conn.commit()

    def get_job_tracks_details(self, job_id: str) -> List[dict]:
        with get_connection(self.db_path) as conn:
            cur = conn.execute(
                """
                SELECT t.id, t.relative_path, t.input_format, t.output_format, t.status,
                       a.integrated_lufs, a.true_peak_dbtp, a.lra_lu, a.target_gain_db,
                       a.limiter_required, a.limiter_reduction_db, a.bypass_eligible, a.warning_code
                FROM job_items ji
                JOIN tracks t ON ji.track_id = t.id
                LEFT JOIN analysis_results a ON t.id = a.track_id
                WHERE ji.job_id = ?
                ORDER BY t.relative_path ASC
                """,
                (job_id,),
            )
            return [dict(r) for r in cur.fetchall()]
