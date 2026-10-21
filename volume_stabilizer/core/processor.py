"""Audio signal processing and encoding engine using ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path
from .analyzer import LoudnessAnalysis


def process_audio(
    input_path: Path,
    output_path: Path,
    analysis: LoudnessAnalysis,
    output_format: str,  # "mp3" or "aiff"
    peak_ceiling_dbtp: float = -1.0,
) -> None:
    """Process audio file: apply gain and optional true-peak limiter, then encode."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. MP3 Bit-perfect bypass (Q24)
    if analysis.bypass_eligible and output_format == "mp3":
        cmd = [
            "ffmpeg",
            "-y",
            "-nostats",
            "-loglevel", "error",
            "-i", str(input_path),
            "-c:a", "copy",
            "-map_metadata", "-1",
            str(output_path),
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Bypass stream copy failed: {res.stderr}")
        return

    # 2. Build audio filter graph (Q4, Q17, Q19)
    gain = analysis.effective_gain_db
    if analysis.limiter_required:
        # Use 4x oversampling (192kHz) to accurately tame inter-sample peaks (ISPs)
        af_filter = (
            f"volume={gain:.2f}dB,"
            f"aresample=192000,"
            f"alimiter=limit={peak_ceiling_dbtp:.1f}dB:attack=5:release=50:asc=0:asc_level=1.0,"
            f"aresample=48000"
        )
    else:
        af_filter = f"volume={gain:.2f}dB"

    # 3. Audio encoder options (Q5)
    if output_format == "mp3":
        enc_opts = [
            "-c:a", "libmp3lame",
            "-b:a", "320k",
            "-id3v2_version", "3",
            "-write_id3v1", "1",
        ]
    elif output_format == "aiff":
        enc_opts = [
            "-c:a", "pcm_s24be",
            "-ar", "48000",
        ]
    else:
        raise ValueError(f"Unsupported output format: {output_format}")

    cmd = [
        "ffmpeg",
        "-y",
        "-nostats",
        "-loglevel", "error",
        "-i", str(input_path),
        "-vn", "-sn", "-dn",
        "-af", af_filter,
        *enc_opts,
        "-map_metadata", "-1",  # Stripped; mutagen will copy clean tags
        str(output_path),
    ]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Audio encoding failed: {res.stderr}")
