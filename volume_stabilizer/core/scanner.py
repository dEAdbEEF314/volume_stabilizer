"""Audio scanner and format sniffer."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

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
        return guess_codec_by_extension(file_path)

    try:
        data = json.loads(res.stdout)
        streams = data.get("streams", [])
        if streams and "codec_name" in streams[0]:
            return streams[0]["codec_name"].lower()
    except Exception:
        pass

    return guess_codec_by_extension(file_path)


def guess_codec_by_extension(file_path: Path) -> str:
    """Fast codec heuristic based purely on file extension."""
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


def scan_directory(
    input_root: Path,
    output_root: Path,
    subpath: str = "",
    fast_mode: bool = False,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Iterator[ScannedTrack]:
    """Recursively scan directory for audio files.

    If fast_mode is True, avoids ffprobe subprocesses during directory crawl
    and resolves codecs via fast extension heuristics.
    progress_callback is called periodically with (folders_scanned, audio_found, current_folder).
    """
    scan_dir = (input_root / subpath).resolve()
    if not scan_dir.exists():
        return

    folders_scanned = 0
    audio_found = 0
    seen_dirs = set()

    for path in sorted(scan_dir.rglob("*")):
        parent = path.parent
        if parent not in seen_dirs:
            seen_dirs.add(parent)
            folders_scanned += 1
            if progress_callback:
                rel_folder = str(parent.relative_to(input_root)) if parent != input_root else "/"
                progress_callback(folders_scanned, audio_found, rel_folder)

        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            rel = path.relative_to(input_root)
        except ValueError:
            continue

        stat = path.stat()
        ext = path.suffix.lower()

        if fast_mode:
            codec = guess_codec_by_extension(path)
        else:
            codec = detect_audio_codec(path)

        # Classify lossy vs lossless
        is_lossy = (
            codec in LOSSY_CODECS
            or (codec == "unknown" and ext in (".mp3", ".aac"))
        )

        output_format = "mp3" if is_lossy else "aiff"
        new_suffix = ".mp3" if is_lossy else ".aiff"
        out_rel = rel.with_suffix(new_suffix)
        out_path = (output_root / out_rel).resolve()

        audio_found += 1
        if progress_callback and audio_found % 10 == 0:
            rel_folder = str(parent.relative_to(input_root)) if parent != input_root else "/"
            progress_callback(folders_scanned, audio_found, rel_folder)

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

    if progress_callback:
        progress_callback(folders_scanned, audio_found, "Scan complete")
