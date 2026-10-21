"""Data structures and representations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class TrackRecord:
    id: str
    audio_hash: str
    relative_path: str
    input_path: str
    output_path: str
    input_format: str
    output_format: str
    file_size: int
    mtime: float
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class AnalysisRecord:
    track_id: str
    integrated_lufs: float
    true_peak_dbtp: float
    lra_lu: float
    target_gain_db: float
    limiter_required: bool
    limiter_reduction_db: float
    bypass_eligible: bool
    warning_code: str
    analyzed_at: Optional[str] = None


@dataclass
class JobRecord:
    id: str
    job_type: str
    target_dir: str
    status: str
    force: bool
    total_tracks: int = 0
    processed_tracks: int = 0
    success_count: int = 0
    bypass_count: int = 0
    warn_count: int = 0
    error_count: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
