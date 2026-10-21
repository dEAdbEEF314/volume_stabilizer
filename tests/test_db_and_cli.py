from pathlib import Path
from typer.testing import CliRunner
from volume_stabilizer.cli.main import app
from volume_stabilizer.db.database import init_db
from volume_stabilizer.db.repository import Repository

runner = CliRunner()


def test_db_repository(tmp_path: Path):
    db_file = tmp_path / "test.db"
    init_db(db_file)
    repo = Repository(db_file)

    t = repo.upsert_track(
        audio_hash="dummy_hash_12345",
        relative_path="House/track.flac",
        input_path="/music/House/track.flac",
        output_path="/output/House/track.aiff",
        input_format="flac",
        output_format="aiff",
        file_size=10485760,
        mtime=1700000000.0,
    )
    assert t.id is not None
    assert t.audio_hash == "dummy_hash_12345"

    repo.save_analysis(
        track_id=t.id,
        integrated_lufs=-14.0,
        true_peak_dbtp=-2.0,
        lra_lu=6.0,
        target_gain_db=4.0,
        limiter_required=False,
        limiter_reduction_db=0.0,
        bypass_eligible=False,
    )

    analysis = repo.get_analysis(t.id)
    assert analysis is not None
    assert analysis.integrated_lufs == -14.0
    assert analysis.target_gain_db == 4.0


def test_cli_scan_and_convert_incremental(tmp_path: Path, test_audio_generator, monkeypatch):
    in_dir = tmp_path / "music"
    out_dir = tmp_path / "output"
    data_dir = tmp_path / "data"
    in_dir.mkdir()
    out_dir.mkdir()
    data_dir.mkdir()

    # Set environment variables for CLI
    monkeypatch.setenv("VS_INPUT_ROOT", str(in_dir))
    monkeypatch.setenv("VS_OUTPUT_ROOT", str(out_dir))
    monkeypatch.setenv("VS_DATA_DIR", str(data_dir))

    # Generate a sample track
    sub = in_dir / "Techno"
    sub.mkdir()
    test_audio_generator("track.wav", duration=2.5, volume=0.3)
    (tmp_path / "track.wav").rename(sub / "track.wav")

    # 1. Test scan
    res_scan = runner.invoke(app, ["scan"])
    assert res_scan.exit_code == 0
    assert "Techno/track.wav" in res_scan.stdout

    # 2. Test convert (first run -> converted)
    res_conv1 = runner.invoke(app, ["convert"])
    assert res_conv1.exit_code == 0
    assert "Converted: 1" in res_conv1.stdout
    expected_out = out_dir / "Techno" / "track.aiff"
    assert expected_out.exists()

    # 3. Test convert again without --force (should be skipped!)
    res_conv2 = runner.invoke(app, ["convert"])
    assert res_conv2.exit_code == 0
    assert "Skipped (Unchanged): 1" in res_conv2.stdout
    assert "Converted: 0" in res_conv2.stdout

    # 4. Test convert with --force (should re-convert and create backup)
    res_conv3 = runner.invoke(app, ["convert", "--force"])
    assert res_conv3.exit_code == 0
    assert "Converted: 1" in res_conv3.stdout
    backup_dir = out_dir / ".backup"
    assert backup_dir.exists()
    backup_files = list(backup_dir.rglob("*.aiff"))
    assert len(backup_files) >= 1
