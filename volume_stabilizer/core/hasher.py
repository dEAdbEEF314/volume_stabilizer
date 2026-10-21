"""Audio stream hash calculator (ignoring ID3/metadata)."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


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
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
        _, err = proc.communicate()
        if proc.returncode != 0:
            err_msg = err.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"Audio hash failed for {file_path}: {err_msg}")

    return hasher.hexdigest()
