from pathlib import Path
from volume_stabilizer.core.analyzer import analyze_track
from volume_stabilizer.core.processor import process_audio


def test_process_to_aiff_and_mp3(tmp_path: Path, test_audio_generator):
    track = test_audio_generator("source.wav", duration=4.0, volume=0.2)
    analysis = analyze_track(track, is_mp3=False, target_lufs=-10.0)

    # Output to AIFF
    out_aiff = tmp_path / "out.aiff"
    process_audio(track, out_aiff, analysis, output_format="aiff")
    assert out_aiff.exists()
    assert out_aiff.stat().st_size > 0

    # Output to MP3
    out_mp3 = tmp_path / "out.mp3"
    process_audio(track, out_mp3, analysis, output_format="mp3")
    assert out_mp3.exists()
    assert out_mp3.stat().st_size > 0

    # Verify stabilized loudness is close to target (-10.0)
    post_analysis = analyze_track(out_aiff, is_mp3=False, target_lufs=-10.0)
    assert abs(post_analysis.integrated_lufs - (-10.0)) < 0.6
