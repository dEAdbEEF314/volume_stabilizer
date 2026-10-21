from pathlib import Path
from volume_stabilizer.core.analyzer import analyze_track, LoudnessAnalysis


def test_analyzer_basic(test_audio_generator):
    track = test_audio_generator("quiet.wav", duration=3.0, volume=0.1)
    analysis = analyze_track(track, is_mp3=False, target_lufs=-10.0)

    assert isinstance(analysis, LoudnessAnalysis)
    assert analysis.integrated_lufs < -15.0
    assert analysis.target_gain_db > 0.0
    assert analysis.limiter_reduction_db <= 3.0  # Cap check
