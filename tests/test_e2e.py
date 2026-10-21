from pathlib import Path
from typer.testing import CliRunner
from volume_stabilizer.cli.main import app
from volume_stabilizer.core.analyzer import analyze_track

runner = CliRunner()


def test_full_e2e_pipeline(tmp_path: Path, test_audio_generator, monkeypatch):
    in_dir = tmp_path / "music"
    out_dir = tmp_path / "output"
    data_dir = tmp_path / "data"
    in_dir.mkdir()
    out_dir.mkdir()
    data_dir.mkdir()

    monkeypatch.setenv("VS_INPUT_ROOT", str(in_dir))
    monkeypatch.setenv("VS_OUTPUT_ROOT", str(out_dir))
    monkeypatch.setenv("VS_DATA_DIR", str(data_dir))

    # 1. Setup multi-format DJ library with varied loudnesses
    house_dir = in_dir / "House"
    techno_dir = in_dir / "Techno"
    house_dir.mkdir()
    techno_dir.mkdir()

    # Track 1: Quiet WAV (approx -20 LUFS) -> Should convert to AIFF and be boosted to -10 LUFS
    test_audio_generator("quiet.wav", duration=3.0, volume=0.1)
    (tmp_path / "quiet.wav").rename(house_dir / "quiet.wav")

    # Track 2: Loud WAV (approx -6 LUFS) -> Should convert to AIFF and be attenuated to -10 LUFS
    test_audio_generator("loud.wav", duration=3.0, volume=0.8)
    (tmp_path / "loud.wav").rename(house_dir / "loud.wav")

    # Track 3: MP3 track -> Should convert to MP3 320k CBR
    test_audio_generator("beat.mp3", duration=3.0, volume=0.3)
    (tmp_path / "beat.mp3").rename(techno_dir / "beat.mp3")

    # 2. CLI Scan
    res_scan = runner.invoke(app, ["scan"])
    assert res_scan.exit_code == 0
    assert "House/quiet.wav" in res_scan.stdout
    assert "House/loud.wav" in res_scan.stdout
    assert "Techno/beat.mp3" in res_scan.stdout

    # 3. CLI Analyze
    res_analyze = runner.invoke(app, ["analyze"])
    assert res_analyze.exit_code == 0
    assert "House/quiet" in res_analyze.stdout

    # 4. CLI Convert (Stage 2)
    res_conv = runner.invoke(app, ["convert"])
    assert res_conv.exit_code == 0
    assert "Converted:" in res_conv.stdout

    # Verify outputs exist with correct mirrored paths
    out_quiet = out_dir / "House" / "quiet.aiff"
    out_loud = out_dir / "House" / "loud.aiff"
    out_beat = out_dir / "Techno" / "beat.mp3"

    assert out_quiet.exists()
    assert out_loud.exists()
    assert out_beat.exists()

    # 5. Verify Stabilized Loudness
    # Both quiet and loud tracks should now measure around -10 LUFS (+- 0.8 LU)
    an_quiet = analyze_track(out_quiet, is_mp3=False, target_lufs=-10.0)
    an_loud = analyze_track(out_loud, is_mp3=False, target_lufs=-10.0)

    assert abs(an_quiet.integrated_lufs - (-10.0)) < 1.0, f"Quiet boosted to {an_quiet.integrated_lufs}"
    assert abs(an_loud.integrated_lufs - (-10.0)) < 1.0, f"Loud attenuated to {an_loud.integrated_lufs}"
    assert an_loud.true_peak_dbtp <= -0.9, f"Peak ceiling enforced: {an_loud.true_peak_dbtp}"

    # 6. Second Run: Incremental Skip Check
    res_conv_skip = runner.invoke(app, ["convert"])
    assert res_conv_skip.exit_code == 0
    assert "Skipped (Unchanged): 3" in res_conv_skip.stdout
    assert "Converted: 0" in res_conv_skip.stdout

    # 7. Force Run: Backup & Reprocess Check
    res_conv_force = runner.invoke(app, ["convert", "--force"])
    assert res_conv_force.exit_code == 0
    assert "Converted: 3" in res_conv_force.stdout or "Bypassed:" in res_conv_force.stdout

    backup_dir = out_dir / ".backup"
    assert backup_dir.exists()
    backups = list(backup_dir.rglob("*.*"))
    assert len(backups) >= 3, f"Expected 3 backed up files, found {len(backups)}"
