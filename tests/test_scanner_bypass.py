from pathlib import Path
import subprocess
import pytest
from volume_stabilizer.core.scanner import classify_codec, detect_audio_codec, scan_directory
from volume_stabilizer.core.analyzer import analyze_track
from volume_stabilizer.core.processor import process_audio
from volume_stabilizer.core.hasher import compute_audio_hash


def test_scanner_rejects_subpath_outside_input_root(tmp_path: Path):
    input_root = tmp_path / "music"
    output_root = tmp_path / "output"
    outside_root = tmp_path / "outside"
    input_root.mkdir()
    output_root.mkdir()
    outside_root.mkdir()

    with pytest.raises(ValueError, match="inside input root"):
        list(scan_directory(input_root, output_root, "../outside"))


def test_scanner_skips_audio_symlink_outside_input_root(tmp_path: Path):
    input_root = tmp_path / "music"
    output_root = tmp_path / "output"
    outside_audio = tmp_path / "private.wav"
    input_root.mkdir()
    output_root.mkdir()
    outside_audio.write_bytes(b"not an audio file")
    (input_root / "linked.wav").symlink_to(outside_audio)

    assert list(scan_directory(input_root, output_root)) == []


def test_m4a_codec_detection_distinguishes_aac_and_alac(tmp_path: Path, test_audio_generator):
    input_root = tmp_path / "music"
    input_root.mkdir()
    source = test_audio_generator("source.wav", duration=0.2)

    for codec, expected_format in (("aac", "mp3"), ("alac", "aiff")):
        target = input_root / f"track-{codec}.m4a"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-c:a", codec, str(target)],
            check=True,
        )
        detected_codec = detect_audio_codec(target)

        assert detected_codec == codec
        assert classify_codec(detected_codec, target.suffix)[1] == expected_format


def test_scanner_and_bypass(tmp_path: Path, test_audio_generator):
    in_dir = tmp_path / "music"
    out_dir = tmp_path / "output"
    in_dir.mkdir()
    out_dir.mkdir()

    # Generate a track that is already around -10 LUFS
    # A sine wave with volume ~0.45 hits approx -10.5 to -9.5 LUFS
    tr = in_dir / "Sub" / "almost_compliant.mp3"
    tr.parent.mkdir(parents=True)
    test_audio_generator("almost_compliant.mp3", duration=3.0, volume=0.45)
    (tmp_path / "almost_compliant.mp3").rename(tr)

    scanned = list(scan_directory(in_dir, out_dir))
    assert len(scanned) == 1
    t = scanned[0]
    assert t.relative_path == Path("Sub/almost_compliant.mp3")
    assert t.output_format == "mp3"
    assert t.output_path == out_dir / "Sub/almost_compliant.mp3"

    analysis = analyze_track(t.input_path, is_mp3=True, target_lufs=-10.0)
    if analysis.bypass_eligible:
        # If bypass eligible, test that process_audio does stream copy (identical PCM hash)
        process_audio(t.input_path, t.output_path, analysis, "mp3")
        assert t.output_path.exists()
        assert compute_audio_hash(t.input_path) == compute_audio_hash(t.output_path)
