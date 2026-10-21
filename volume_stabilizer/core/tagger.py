"""Metadata and Serato DJ tag management using mutagen."""

from __future__ import annotations

import logging
from pathlib import Path
import mutagen
from mutagen.id3 import (
    ID3,
    GEOB,
    APIC,
    TBPM,
    TKEY,
    TIT2,
    TPE1,
    TALB,
    TCON,
    TDRC,
    TRCK,
    COMM,
)
from mutagen.aiff import AIFF
from mutagen.mp3 import MP3

logger = logging.getLogger(__name__)

SERATO_GEOB_PREFIXES = (
    "Serato Markers_",
    "Serato Markers2",
    "Serato Beatgrid",
    "Serato Autotags",
    "Serato Overview",
)


def copy_metadata(
    source_path: Path,
    target_path: Path,
    preserve_from_target: bool = False,
) -> None:
    """
    Copy tags and Serato cues/beatgrid from source to target.
    If preserve_from_target is True (--force reprocess), prefer tags already on target.
    """
    read_source = target_path if (preserve_from_target and target_path.exists()) else source_path

    try:
        src = mutagen.File(str(read_source))
    except Exception as e:
        logger.warning(f"Could not read metadata from {read_source}: {e}")
        return

    if src is None:
        return

    try:
        dst = mutagen.File(str(target_path))
    except Exception as e:
        logger.warning(f"Could not open target for metadata writing: {target_path}: {e}")
        return

    if dst is None:
        return

    # Ensure target has ID3 container (MP3 or AIFF)
    if dst.tags is None:
        try:
            dst.add_tags()
        except Exception:
            pass

    if dst.tags is None:
        return

    # Case A: Source has ID3 tags (MP3, AIFF, WAV with ID3)
    if hasattr(src, "tags") and src.tags is not None and hasattr(src.tags, "items"):
        for key, frame in src.tags.items():
            key_upper = str(key).upper()

            # 1. Strip ReplayGain / R128 tags (now invalid)
            if "REPLAYGAIN" in key_upper or "R128" in key_upper:
                continue

            # 2. Serato GEOB tags: copy verbatim
            if isinstance(frame, GEOB):
                try:
                    dst.tags.add(frame)
                except Exception as e:
                    logger.debug(f"Failed to copy GEOB frame {key}: {e}")
                continue

            # 3. Standard ID3 frames
            try:
                dst.tags.add(frame)
            except Exception:
                pass

    # Case B: Source is FLAC / VorbisComment
    elif hasattr(src, "items"):
        for k, v in src.items():
            k_upper = k.upper()
            if "REPLAYGAIN" in k_upper or "R128" in k_upper:
                continue

            val = v[0] if isinstance(v, list) and v else str(v)

            if k_upper == "TITLE":
                dst.tags.add(TIT2(encoding=3, text=[val]))
            elif k_upper in ("ARTIST", "PERFORMER"):
                dst.tags.add(TPE1(encoding=3, text=[val]))
            elif k_upper == "ALBUM":
                dst.tags.add(TALB(encoding=3, text=[val]))
            elif k_upper == "GENRE":
                dst.tags.add(TCON(encoding=3, text=[val]))
            elif k_upper in ("DATE", "YEAR"):
                dst.tags.add(TDRC(encoding=3, text=[val]))
            elif k_upper == "TRACKNUMBER":
                dst.tags.add(TRCK(encoding=3, text=[val]))
            elif k_upper == "BPM":
                dst.tags.add(TBPM(encoding=3, text=[val]))
            elif k_upper in ("KEY", "INITIALKEY"):
                dst.tags.add(TKEY(encoding=3, text=[val]))
            elif k_upper == "COMMENT":
                dst.tags.add(COMM(encoding=3, lang="eng", desc="", text=[val]))

        # FLAC pictures to ID3 APIC
        if hasattr(src, "pictures"):
            for pic in src.pictures:
                apic = APIC(
                    encoding=3,
                    mime=pic.mime,
                    type=pic.type,
                    desc=pic.desc,
                    data=pic.data,
                )
                dst.tags.add(apic)

    try:
        dst.save()
    except Exception as e:
        logger.warning(f"Error saving tags to {target_path}: {e}")
