"""Concurrent worker execution for audio analysis and conversion jobs."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Callable, List, Optional

from volume_stabilizer.config import Config, load_config
from volume_stabilizer.core.scanner import scan_directory, ScannedTrack
from volume_stabilizer.core.hasher import compute_audio_hash
from volume_stabilizer.core.analyzer import analyze_track, LoudnessAnalysis
from volume_stabilizer.core.processor import process_audio
from volume_stabilizer.core.tagger import copy_metadata
from volume_stabilizer.core.backup import backup_existing_output
from volume_stabilizer.db.repository import Repository
from volume_stabilizer.api.websocket import ws_manager

logger = logging.getLogger(__name__)


def _worker_analyze_track(
    input_path_str: str,
    output_format: str,
    target_lufs: float,
    peak_ceiling_dbtp: float,
    max_limiter_reduction_db: float,
    bypass_tolerance_lu: float,
) -> tuple[str, dict]:
    """Worker task: compute audio hash and EBU R128 analysis."""
    p = Path(input_path_str)
    audio_hash = compute_audio_hash(p)
    analysis = analyze_track(
        file_path=p,
        is_mp3=(output_format == "mp3"),
        target_lufs=target_lufs,
        peak_ceiling_dbtp=peak_ceiling_dbtp,
        max_limiter_reduction_db=max_limiter_reduction_db,
        bypass_tolerance_lu=bypass_tolerance_lu,
    )
    return audio_hash, asdict(analysis)


def _worker_convert_track(
    input_path_str: str,
    output_path_str: str,
    output_format: str,
    analysis_dict: dict,
    force: bool,
    backup_dir_str: str,
    peak_ceiling_dbtp: float,
) -> str:
    """Worker task: process audio (gain/limiter), backup if needed, encode, copy tags."""
    in_p = Path(input_path_str)
    out_p = Path(output_path_str)
    bck_root = Path(backup_dir_str)
    analysis = LoudnessAnalysis(**analysis_dict)

    # 1. Back up old output if force and output exists
    if force and out_p.exists():
        backup_existing_output(out_p, bck_root, out_p.name)

    # 2. Process audio & encode
    process_audio(
        input_path=in_p,
        output_path=out_p,
        analysis=analysis,
        output_format=output_format,
        peak_ceiling_dbtp=peak_ceiling_dbtp,
    )

    # 3. Preserve metadata & Serato cues
    copy_metadata(
        source_path=in_p,
        target_path=out_p,
        preserve_from_target=force,
    )

    return "bypassed" if analysis.bypass_eligible else "converted"


class JobManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.repo = Repository(cfg.db_path)
        self.pool = ProcessPoolExecutor(max_workers=cfg.workers)

    async def run_analyze_job(self, job_id: str, subpath: str, force: bool = False):
        tracks: List[ScannedTrack] = list(scan_directory(self.cfg.input_root, self.cfg.output_root, subpath))
        total = len(tracks)
        processed = 0

        self.repo.update_job_progress(job_id, total, 0, 0, 0, 0, 0, status="RUNNING")
        await ws_manager.broadcast({
            "event": "JOB_STARTED",
            "data": {"job_id": job_id, "type": "ANALYZE", "total": total}
        })

        loop = asyncio.get_running_loop()

        for t in tracks:
            try:
                audio_hash, analysis_dict = await loop.run_in_executor(
                    self.pool,
                    _worker_analyze_track,
                    str(t.input_path),
                    t.output_format,
                    self.cfg.target_lufs,
                    self.cfg.peak_ceiling_dbtp,
                    self.cfg.max_limiter_reduction_db,
                    self.cfg.bypass_tolerance_lu,
                )

                track_rec = self.repo.upsert_track(
                    audio_hash=audio_hash,
                    relative_path=str(t.relative_path),
                    input_path=str(t.input_path),
                    output_path=str(t.output_path),
                    input_format=t.codec,
                    output_format=t.output_format,
                    file_size=t.file_size,
                    mtime=t.mtime,
                )

                self.repo.save_analysis(
                    track_id=track_rec.id,
                    integrated_lufs=analysis_dict["integrated_lufs"],
                    true_peak_dbtp=analysis_dict["true_peak_dbtp"],
                    lra_lu=analysis_dict["lra_lu"],
                    target_gain_db=analysis_dict["target_gain_db"],
                    limiter_required=analysis_dict["limiter_required"],
                    limiter_reduction_db=analysis_dict["limiter_reduction_db"],
                    bypass_eligible=analysis_dict["bypass_eligible"],
                    warning_code=analysis_dict["warning_code"],
                )

                processed += 1
                self.repo.update_job_progress(job_id, total, processed, processed, 0, 0, 0)
                await ws_manager.broadcast({
                    "event": "JOB_PROGRESS",
                    "data": {
                        "job_id": job_id,
                        "processed": processed,
                        "total": total,
                        "percent": round((processed / total) * 100, 1) if total else 100,
                        "track": str(t.relative_path),
                        "analysis": analysis_dict,
                    }
                })
            except Exception as e:
                logger.error(f"Error analyzing {t.input_path}: {e}")

        self.repo.update_job_progress(job_id, total, processed, processed, 0, 0, 0, status="COMPLETED")
        await ws_manager.broadcast({
            "event": "JOB_COMPLETED",
            "data": {"job_id": job_id, "type": "ANALYZE", "total": total}
        })

    async def run_convert_job(
        self,
        job_id: str,
        track_ids: List[str],
        force: bool = False,
    ):
        total = len(track_ids)
        processed = 0
        converted_count = 0
        bypass_count = 0
        skipped_count = 0
        error_count = 0

        self.repo.update_job_progress(job_id, total, 0, 0, 0, 0, 0, status="RUNNING")
        await ws_manager.broadcast({
            "event": "JOB_STARTED",
            "data": {"job_id": job_id, "type": "CONVERT", "total": total}
        })

        loop = asyncio.get_running_loop()

        for tid in track_ids:
            t = self.repo.get_track_by_id(tid)
            if not t:
                continue

            analysis_rec = self.repo.get_analysis(tid)
            if not analysis_rec:
                # Need analysis first
                continue

            out_p = Path(t.output_path)

            # Skip unchanged if not force
            if not force and t.status in ("converted", "bypassed") and out_p.exists():
                skipped_count += 1
                processed += 1
                continue

            try:
                status = await loop.run_in_executor(
                    self.pool,
                    _worker_convert_track,
                    t.input_path,
                    t.output_path,
                    t.output_format,
                    asdict(analysis_rec),
                    force,
                    str(self.cfg.backup_dir),
                    self.cfg.peak_ceiling_dbtp,
                )

                self.repo.update_track_status(t.id, status)
                if status == "bypassed":
                    bypass_count += 1
                else:
                    converted_count += 1

                processed += 1
                self.repo.update_job_progress(
                    job_id, total, processed, converted_count, bypass_count, 0, error_count
                )
                await ws_manager.broadcast({
                    "event": "JOB_PROGRESS",
                    "data": {
                        "job_id": job_id,
                        "processed": processed,
                        "total": total,
                        "percent": round((processed / total) * 100, 1) if total else 100,
                        "track": t.relative_path,
                        "status": status,
                    }
                })
            except Exception as e:
                logger.error(f"Error converting {t.input_path}: {e}")
                error_count += 1
                processed += 1

        self.repo.update_job_progress(
            job_id, total, processed, converted_count, bypass_count, 0, error_count, status="COMPLETED"
        )
        await ws_manager.broadcast({
            "event": "JOB_COMPLETED",
            "data": {
                "job_id": job_id,
                "type": "CONVERT",
                "converted": converted_count,
                "bypassed": bypass_count,
                "skipped": skipped_count,
                "errors": error_count,
            }
        })
