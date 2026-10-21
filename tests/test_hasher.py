from pathlib import Path
from volume_stabilizer.core.hasher import compute_audio_hash
from mutagen.id3 import ID3, TIT2, TPE1, COMM, GEOB
from mutagen.mp3 import MP3


def test_hash_invariant_under_tag_edits(test_audio_generator):
    track = test_audio_generator("track_tags.mp3", duration=2.0)
    hash_before = compute_audio_hash(track)

    # Edit metadata
    tags = ID3(str(track))
    tags.add(TIT2(encoding=3, text=["Different Title"]))
    tags.add(TPE1(encoding=3, text=["Famous DJ"]))
    tags.add(GEOB(encoding=0, mime="application/octet-stream", desc="Serato Markers2", data=b"\x01\x02\x03\x04"))
    tags.save()

    hash_after = compute_audio_hash(track)
    assert hash_before == hash_after, "Hash must remain invariant under tag modifications"
