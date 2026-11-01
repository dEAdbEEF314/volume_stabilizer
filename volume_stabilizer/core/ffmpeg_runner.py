"""ffmpeg subprocess helpers with manual-skip support.

A worker process registers its ffmpeg PID in a shared temp dir; the API process
can then kill it (see `request_skip`) and the worker raises `SkippedByUser`.
"""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Sequence

_STATE_DIR = Path(tempfile.gettempdir()) / "vstab_active"

# One task runs at a time per pool worker process, so a module global is safe.
_active_job_id: Optional[str] = None


class SkippedByUser(OSError):
    """The current track was aborted manually (treated as an I/O error)."""


def _pid_file(job_id: str) -> Path:
    return _STATE_DIR / f"{job_id}.pid"


def _skip_file(job_id: str) -> Path:
    return _STATE_DIR / f"{job_id}.skip"


def set_active_job(job_id: Optional[str]) -> None:
    global _active_job_id
    _active_job_id = job_id


def request_skip(job_id: str) -> bool:
    """Kill the job's running ffmpeg. Returns True if a process was killed."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Marker also covers an ffmpeg that has not been spawned yet.
    _skip_file(job_id).touch()
    try:
        pid = int(_pid_file(job_id).read_text())
        os.kill(pid, signal.SIGKILL)
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return False
    return True


def clear_skip(job_id: str) -> None:
    _skip_file(job_id).unlink(missing_ok=True)
    _pid_file(job_id).unlink(missing_ok=True)


@contextmanager
def tracked(proc: subprocess.Popen) -> Iterator[None]:
    """Register `proc` as the job's active ffmpeg; raise SkippedByUser if it was skipped."""
    job_id = _active_job_id
    if job_id is None:
        yield
        return

    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _pid_file(job_id).write_text(str(proc.pid))
    try:
        if _skip_file(job_id).exists():
            proc.kill()
        yield
    finally:
        _pid_file(job_id).unlink(missing_ok=True)
        if _skip_file(job_id).exists():
            _skip_file(job_id).unlink(missing_ok=True)
            raise SkippedByUser("Skipped by user (I/O stalled)")


def run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    """Like subprocess.run(capture_output, text) but skippable."""
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    ) as proc:
        with tracked(proc):
            out, err = proc.communicate()
    return subprocess.CompletedProcess(list(cmd), proc.returncode, out, err)
