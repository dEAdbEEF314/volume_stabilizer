"""Backup manager for existing output files during --force reprocessing."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def backup_existing_output(
    output_path: Path,
    backup_root: Path,
    relative_path: Path,
) -> Path | None:
    """Safely back up an existing stabilized file before overwriting under --force."""
    if not output_path.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = (backup_root / timestamp / relative_path).resolve()
    backup_file.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(str(output_path), str(backup_file))
    return backup_file
