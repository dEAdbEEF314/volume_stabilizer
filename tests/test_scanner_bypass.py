from pathlib import Path
from volume_stabilizer.core.scanner import scan_directory
from volume_stabilizer.core.analyzer import analyze_track
from volume_stabilizer.core.processor import process_audio
from volume_stabilizer.core.hasher import compute_audio_hash


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
