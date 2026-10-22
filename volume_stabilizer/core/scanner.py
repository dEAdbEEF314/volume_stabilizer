"""Audio scanner and format sniffer."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".aiff", ".aif", ".flac"}
LOSSY_CODECS = {"mp3", "aac"}
LOSSLESS_CODECS = {"flac", "alac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_s16be", "pcm_s24be", "pcm_f32le"}


@dataclass(frozen=True)
class ScannedTrack:
    input_path: Path
    relative_path: Path
    codec: str
    is_lossy: bool
    output_format: str  # "mp3" or "aiff"
    output_path: Path
    file_size: int
    mtime: float


def detect_audio_codec(file_path: Path) -> str:
    """Detect audio codec using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "json",
        str(file_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    if res.returncode != 0:
        # Fallback to extension heuristic
        ext = file_path.suffix.lower()
        if ext == ".mp3":
            return "mp3"
        if ext in (".wav", ".aiff", ".aif"):
            return "pcm"
        if ext == ".flac":
            return "flac"
        if ext in (".m4a", ".aac"):
            return "aac"
        return "unknown"

    try:
        data = json.loads(res.stdout)
        streams = data.get("streams", [])
        if streams and "codec_name" in streams[0]:
            return streams[0]["codec_name"].lower()
    except Exception:
        pass

    return "unknown"


def scan_directory(input_root: Path, output_root: Path, subpath: str = "") -> Iterator[ScannedTrack]:
    """Recursively scan directory for audio files."""
    scan_dir = (input_root / subpath).resolve()
    if not scan_dir.exists():
        return

    for path in sorted(scan_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            rel = path.relative_to(input_root)
        except ValueError:
            continue

        stat = path.stat()
        codec = detect_audio_codec(path)
        ext = path.suffix.lower()

        # Classify lossy vs lossless
        is_lossy = (
            codec in LOSSY_CODECS
            or (codec == "unknown" and ext in (".mp3", ".aac"))
        )

        output_format = "mp3" if is_lossy else "aiff"
        new_suffix = ".mp3" if is_lossy else ".aiff"
        out_rel = rel.with_suffix(new_suffix)
        out_path = (output_root / out_rel).resolve()

        yield ScannedTrack(
            input_path=path.resolve(),
            relative_path=rel,
            codec=codec,
            is_lossy=is_lossy,
            output_format=output_format,
            output_path=out_path,
            file_size=stat.st_size,
            mtime=stat.st_mtime,
        )
