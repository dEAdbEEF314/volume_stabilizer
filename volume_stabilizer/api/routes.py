"""FastAPI REST routes for Volume Stabilizer."""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from volume_stabilizer.config import Config, load_config
from volume_stabilizer.core.scanner import scan_directory, SUPPORTED_EXTENSIONS
from volume_stabilizer.db.database import get_connection, init_db
from volume_stabilizer.db.repository import Repository
from volume_stabilizer.queue.worker_pool import JobManager

router = APIRouter(prefix="/api/v1")
_job_manager: Optional[JobManager] = None


def get_cfg() -> Config:
    return load_config()


def get_job_manager(cfg: Config = Depends(get_cfg)) -> JobManager:
    global _job_manager
    if _job_manager is None:
        init_db(cfg.db_path)
        _job_manager = JobManager(cfg)
    return _job_manager


def _resolve_input_path(cfg: Config, subpath: str) -> Path:
    input_root = cfg.input_root.resolve()
    target = (input_root / subpath).resolve()
    try:
        target.relative_to(input_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path must be inside input root") from exc
    return target


def _track_path_filter(path: str) -> tuple[str, str, str]:
    directory = path.strip("/")
    if not directory:
        return "", "", "%"
    escaped = directory.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return directory, directory, f"{escaped}/%"


class AnalyzeRequest(BaseModel):
    subpath: str = ""
    force: bool = False


class ConvertRequest(BaseModel):
    analyze_job_id: Optional[str] = None
    track_ids: Optional[List[str]] = None
    force: bool = False


@router.get("/system/status")
def get_system_status(cfg: Config = Depends(get_cfg)):
    init_db(cfg.db_path)
    with get_connection(cfg.db_path) as conn:
        track_count = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        converted_count = conn.execute("SELECT COUNT(*) FROM tracks WHERE status IN ('converted', 'bypassed')").fetchone()[0]

    return {
        "workers": cfg.workers,
        "input_root": str(cfg.input_root),
        "output_root": str(cfg.output_root),
        "target_lufs": cfg.target_lufs,
        "peak_ceiling_dbtp": cfg.peak_ceiling_dbtp,
        "total_tracks": track_count,
        "stabilized_tracks": converted_count,
    }


@router.get("/fs/tree")
def get_directory_tree(path: str = Query("", description="Relative path inside /music"), cfg: Config = Depends(get_cfg)):
    target = _resolve_input_path(cfg, path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    subdirs = []
    audio_files = []

    try:
        for entry in sorted(target.iterdir()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                subdirs.append(entry.name)
            elif entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
                audio_files.append(entry.name)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied reading directory")

    return {
        "current": path,
        "subdirs": subdirs,
        "audio_count": len(audio_files),
        "audio_files": audio_files[:50],  # preview top 50
    }


@router.get("/tracks")
def list_tracks(
    path: str = Query("", description="Relative subpath in /music"),
    cfg: Config = Depends(get_cfg),
):
    init_db(cfg.db_path)
    with get_connection(cfg.db_path) as conn:
        path_filter = _track_path_filter(path)
        cur = conn.execute(
            """
            SELECT t.id, t.relative_path, t.input_format, t.output_format, t.status,
                   a.integrated_lufs, a.true_peak_dbtp, a.lra_lu, a.target_gain_db,
                   a.limiter_required, a.limiter_reduction_db, a.bypass_eligible, a.warning_code
            FROM tracks t
            LEFT JOIN analysis_results a ON t.id = a.track_id
            WHERE (? = '' OR t.relative_path = ? OR t.relative_path LIKE ? ESCAPE char(92))
            ORDER BY t.relative_path ASC
            """,
            path_filter,
        )
        tracks = [dict(r) for r in cur.fetchall()]

    stabilized_count = sum(1 for t in tracks if t.get("status") in ("converted", "bypassed"))
    return {
        "path": path,
        "total": len(tracks),
        "stabilized_count": stabilized_count,
        "tracks": tracks,
    }


@router.post("/jobs/analyze")
def start_analyze_job(
    req: AnalyzeRequest,
    bg_tasks: BackgroundTasks,
    cfg: Config = Depends(get_cfg),
    jm: JobManager = Depends(get_job_manager),
):
    _resolve_input_path(cfg, req.subpath)
    repo = Repository(cfg.db_path)
    job = repo.create_job(job_type="ANALYZE", target_dir=req.subpath, force=req.force)
    bg_tasks.add_task(jm.run_analyze_job, job.id, req.subpath, req.force)
    return {"job_id": job.id, "status": "PENDING"}


@router.get("/jobs/{job_id}")
def get_job_status(job_id: str, cfg: Config = Depends(get_cfg)):
    repo = Repository(cfg.db_path)
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/skip-current", status_code=202)
def skip_current_track(
    job_id: str,
    cfg: Config = Depends(get_cfg),
    jm: JobManager = Depends(get_job_manager),
):
    repo = Repository(cfg.db_path)
    if not repo.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    if not jm.skip_current(job_id):
        raise HTTPException(status_code=409, detail="No track is currently being processed")
    return {"skipped": True}


@router.get("/jobs/{job_id}/tracks")
def get_job_tracks(job_id: str, cfg: Config = Depends(get_cfg)):
    repo = Repository(cfg.db_path)
    job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Fetch tracks inside this job's target_dir from tracks + analysis_results
    with get_connection(cfg.db_path) as conn:
        path_filter = _track_path_filter(job.target_dir)
        cur = conn.execute(
            """
            SELECT t.id, t.relative_path, t.input_format, t.output_format, t.status,
                   a.integrated_lufs, a.true_peak_dbtp, a.lra_lu, a.target_gain_db,
                   a.limiter_required, a.limiter_reduction_db, a.bypass_eligible, a.warning_code
            FROM tracks t
            LEFT JOIN analysis_results a ON t.id = a.track_id
            WHERE (? = '' OR t.relative_path = ? OR t.relative_path LIKE ? ESCAPE char(92))
            ORDER BY t.relative_path ASC
            """,
            path_filter,
        )
        tracks = [dict(r) for r in cur.fetchall()]

    return {"job_id": job_id, "tracks": tracks}


@router.post("/jobs/convert")
def start_convert_job(
    req: ConvertRequest,
    bg_tasks: BackgroundTasks,
    cfg: Config = Depends(get_cfg),
    jm: JobManager = Depends(get_job_manager),
):
    repo = Repository(cfg.db_path)
    track_ids = req.track_ids or []

    if not track_ids and req.analyze_job_id:
        job = repo.get_job(req.analyze_job_id)
        if job:
            with get_connection(cfg.db_path) as conn:
                path_filter = _track_path_filter(job.target_dir)
                cur = conn.execute(
                    """
                    SELECT id FROM tracks
                    WHERE (? = '' OR relative_path = ? OR relative_path LIKE ? ESCAPE char(92))
                    """,
                    path_filter,
                )
                track_ids = [r[0] for r in cur.fetchall()]

    if not track_ids:
        raise HTTPException(status_code=400, detail="No tracks specified for conversion")

    convert_job = repo.create_job(job_type="CONVERT", target_dir="", force=req.force)
    bg_tasks.add_task(jm.run_convert_job, convert_job.id, track_ids, req.force)
    return {"job_id": convert_job.id, "status": "PENDING", "track_count": len(track_ids)}


@router.post("/tracks/{track_id}/reprocess")
def reprocess_single_track(
    track_id: str,
    bg_tasks: BackgroundTasks,
    cfg: Config = Depends(get_cfg),
    jm: JobManager = Depends(get_job_manager),
):
    repo = Repository(cfg.db_path)
    track = repo.get_track_by_id(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    job = repo.create_job(job_type="CONVERT", target_dir=track.relative_path, force=True)
    bg_tasks.add_task(jm.run_convert_job, job.id, [track_id], force=True)
    return {"job_id": job.id, "status": "PENDING"}


@router.get("/reports/export")
def export_csv_report(cfg: Config = Depends(get_cfg)):
    with get_connection(cfg.db_path) as conn:
        cur = conn.execute(
            """
            SELECT t.relative_path, t.input_format, t.output_format, t.status,
                   a.integrated_lufs, a.true_peak_dbtp, a.lra_lu, a.target_gain_db,
                   a.limiter_required, a.limiter_reduction_db, a.bypass_eligible, a.warning_code,
                   t.updated_at
            FROM tracks t
            LEFT JOIN analysis_results a ON t.id = a.track_id
            ORDER BY t.relative_path ASC
            """
        )
        rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Relative Path", "Input Format", "Output Format", "Status",
        "Integrated LUFS", "True Peak (dBTP)", "LRA (LU)", "Target Gain (dB)",
        "Limiter Required", "Limiter Reduction (dB)", "Bypass Eligible", "Warning", "Last Updated"
    ])

    for r in rows:
        writer.writerow(list(r))

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=volume_stabilizer_report.csv"},
    )
