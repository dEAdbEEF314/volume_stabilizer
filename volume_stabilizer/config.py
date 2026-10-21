"""Runtime configuration for Volume Stabilizer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Automatically load environment variables from .env if present
load_dotenv()


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _resolve_data_dir() -> Path:
    env_val = os.environ.get("VS_DATA_DIR", "").strip() or os.environ.get("DATA_DIR", "").strip()
    if env_val:
        return Path(env_val).resolve()
    # Default to /data (for Docker), but fallback safely if /data is not writable (for local dev/test)
    data_path = Path("/data")
    try:
        data_path.mkdir(parents=True, exist_ok=True)
        return data_path.resolve()
    except (PermissionError, OSError):
        fallback = Path("./data").resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


@dataclass(frozen=True)
class Config:
    input_root: Path
    output_root: Path
    data_dir: Path
    workers: int
    target_lufs: float
    peak_ceiling_dbtp: float
    max_limiter_reduction_db: float
    bypass_tolerance_lu: float

    @property
    def db_path(self) -> Path:
        return self.data_dir / "volume_stabilizer.db"

    @property
    def backup_dir(self) -> Path:
        return self.output_root / ".backup"


def load_config() -> Config:
    cpu = os.cpu_count() or 2
    default_workers = max(1, cpu - 1)
    workers = _env_int("VS_WORKERS", 0) or default_workers

    input_raw = os.environ.get("VS_INPUT_ROOT", "").strip() or os.environ.get("MUSIC_DIR", "/music").strip()
    output_raw = os.environ.get("VS_OUTPUT_ROOT", "").strip() or os.environ.get("OUTPUT_DIR", "/output").strip()

    input_root = Path(input_raw).resolve()
    output_root = Path(output_raw).resolve()
    data_dir = _resolve_data_dir()

    return Config(
        input_root=input_root,
        output_root=output_root,
        data_dir=data_dir,
        workers=workers,
        target_lufs=_env_float("VS_TARGET_LUFS", -10.0),
        peak_ceiling_dbtp=_env_float("VS_PEAK_CEILING", -1.0),
        max_limiter_reduction_db=_env_float("VS_MAX_REDUCTION", 3.0),
        bypass_tolerance_lu=_env_float("VS_BYPASS_TOLERANCE", 0.5),
    )
