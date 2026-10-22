"""EBU R128 loudness analyzer and gain/limiter calculator."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LoudnessAnalysis:
    integrated_lufs: float
    true_peak_dbtp: float
    lra_lu: float
    target_gain_db: float
    limiter_required: bool
    limiter_reduction_db: float
    effective_gain_db: float
    bypass_eligible: bool
    warning_code: str  # 'NONE', 'LOUDNESS_UNDER_TARGET', 'HIGH_PEAK'


def analyze_track(
    file_path: Path,
    is_mp3: bool,
    target_lufs: float = -10.0,
    peak_ceiling_dbtp: float = -1.0,
    max_limiter_reduction_db: float = 3.0,
    bypass_tolerance_lu: float = 0.5,
) -> LoudnessAnalysis:
    """Analyze track loudness using ffmpeg ebur128 and compute stabilization parameters."""
    cmd = [
        "ffmpeg",
        "-nostats",
        "-i", str(file_path),
        "-filter_complex", "ebur128=peak=true",
        "-f", "null",
        "-",
    ]

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    stderr = proc.stderr

    i_match = re.search(r"Integrated loudness:.*?I:\s*([-\d.]+)\s*LUFS", stderr, re.DOTALL)
    tp_match = re.search(r"True peak:.*?Peak:\s*([-\d.]+)\s*dBFS", stderr, re.DOTALL)
    lra_match = re.search(r"Loudness range:.*?LRA:\s*([-\d.]+)\s*LU", stderr, re.DOTALL)

    if not i_match or not tp_match:
        raise ValueError(f"Could not parse ebur128 output for {file_path}. Stderr: {stderr[-500:]}")

    i_lufs = float(i_match.group(1))
    tp_dbtp = float(tp_match.group(1))
    lra_lu = float(lra_match.group(1)) if lra_match else 0.0

    raw_gain = target_lufs - i_lufs
    pred_tp = tp_dbtp + raw_gain

    limiter_required = pred_tp > peak_ceiling_dbtp
    limiter_reduction = max(0.0, pred_tp - peak_ceiling_dbtp) if limiter_required else 0.0

    warning_code = "NONE"
    effective_gain = raw_gain

    # Cap limiter reduction to preserve dynamics/transients (Q19)
    if limiter_reduction > max_limiter_reduction_db:
        excess = limiter_reduction - max_limiter_reduction_db
        effective_gain = raw_gain - excess
        limiter_reduction = max_limiter_reduction_db
        warning_code = "LOUDNESS_UNDER_TARGET"

    # Bypass eligible for MP3 within tolerance and under peak ceiling (Q24)
    bypass_eligible = (
        is_mp3
        and (abs(raw_gain) <= bypass_tolerance_lu)
        and (tp_dbtp <= peak_ceiling_dbtp)
    )

    return LoudnessAnalysis(
        integrated_lufs=i_lufs,
        true_peak_dbtp=tp_dbtp,
        lra_lu=lra_lu,
        target_gain_db=raw_gain,
        limiter_required=limiter_required,
        limiter_reduction_db=limiter_reduction,
        effective_gain_db=effective_gain,
        bypass_eligible=bypass_eligible,
        warning_code=warning_code,
    )
