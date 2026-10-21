from pathlib import Path
import mutagen
from mutagen.id3 import ID3, TIT2, TPE1, TBPM, TKEY, GEOB
from volume_stabilizer.core.tagger import copy_metadata


def test_tagger_preserves_serato_geob(tmp_path: Path, test_audio_generator):
    src = test_audio_generator("src.mp3", duration=2.0)
    dst = test_audio_generator("dst.mp3", duration=2.0)

    # Attach Serato GEOB, BPM, Key to src
    id3 = ID3(str(src))
    id3.add(TIT2(encoding=3, text=["Club Banger"]))
    id3.add(TPE1(encoding=3, text=["Resident DJ"]))
    id3.add(TBPM(encoding=3, text=["128"]))
    id3.add(TKEY(encoding=3, text=["8A"]))
    serato_data = b"\x00\x01\x02SERATO_CUE_DATA\xff\xfe"
    id3.add(GEOB(encoding=0, mime="application/octet-stream", desc="Serato Markers2", data=serato_data))
    id3.save()

    copy_metadata(src, dst)

    # Inspect dst tags
    dst_id3 = ID3(str(dst))
    assert dst_id3.get("TIT2").text[0] == "Club Banger"
    assert dst_id3.get("TBPM").text[0] == "128"
    assert dst_id3.get("TKEY").text[0] == "8A"

    # Find Serato GEOB
    geobs = [f for f in dst_id3.values() if isinstance(f, GEOB) and f.desc == "Serato Markers2"]
    assert len(geobs) == 1
    assert geobs[0].data == serato_data
