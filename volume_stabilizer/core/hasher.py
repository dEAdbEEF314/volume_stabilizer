"""Audio stream hash calculator (ignoring ID3/metadata)."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

from .ffmpeg_runner import tracked


def compute_audio_hash(file_path: Path) -> str:
    """Decode audio to standard raw PCM (s16le, 2ch, 44100Hz) and calculate SHA-256."""
    cmd = [
        "ffmpeg",
        "-nostats",
        "-loglevel", "error",
        "-i", str(file_path),
        "-vn", "-sn", "-dn",
        "-f", "s16le",
        "-ac", "2",
        "-ar", "44100",
        "-",
    ]

    hasher = hashlib.sha256()
    # stderr はファイルへ逃がす: PIPE のまま未読だとバッファ満杯で ffmpeg がデッドロックする
    with tempfile.TemporaryFile() as errf, subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=errf
    ) as proc, tracked(proc):
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
            proc.wait(timeout=60)
        except BaseException:
            proc.kill()
            raise
        if proc.returncode != 0:
            errf.seek(0)
            err_msg = errf.read(4096).decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"Audio hash failed for {file_path}: {err_msg}")

    return hasher.hexdigest()
