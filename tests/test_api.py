from fastapi.testclient import TestClient
from volume_stabilizer.api.app import app
from volume_stabilizer.api.routes import get_job_manager
from volume_stabilizer.db.database import init_db
from volume_stabilizer.db.repository import Repository
from pathlib import Path

client = TestClient(app)


def test_api_status():
    res = client.get("/api/v1/system/status")
    assert res.status_code == 200
    data = res.json()
    assert "target_lufs" in data
    assert data["target_lufs"] == -10.0


def test_api_export_csv():
    res = client.get("/api/v1/reports/export")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "Relative Path" in res.text

def test_api_serve_index():
    res = client.get("/")
    assert res.status_code == 200
    assert "Volume Stabilizer" in res.text


def test_api_list_tracks():
    res = client.get("/api/v1/tracks")
    assert res.status_code == 200
    data = res.json()
    assert "tracks" in data
    assert "total" in data
    assert "stabilized_count" in data


def test_api_directory_tree_rejects_paths_outside_input_root(tmp_path: Path, monkeypatch):
    input_root = tmp_path / "music"
    outside_root = tmp_path / "outside"
    input_root.mkdir()
    outside_root.mkdir()
    (outside_root / "private").mkdir()
    (input_root / "escape").symlink_to(outside_root, target_is_directory=True)

    monkeypatch.setenv("VS_INPUT_ROOT", str(input_root))
    monkeypatch.setenv("VS_OUTPUT_ROOT", str(tmp_path / "output"))
    monkeypatch.setenv("VS_DATA_DIR", str(tmp_path / "data"))

    traversal_response = client.get("/api/v1/fs/tree", params={"path": "../outside"})
    symlink_response = client.get("/api/v1/fs/tree", params={"path": "escape"})

    assert traversal_response.status_code == 400
    assert symlink_response.status_code == 400


def test_api_analyze_rejects_subpath_outside_input_root(tmp_path: Path, monkeypatch):
    input_root = tmp_path / "music"
    input_root.mkdir()
    monkeypatch.setenv("VS_INPUT_ROOT", str(input_root))
    monkeypatch.setenv("VS_OUTPUT_ROOT", str(tmp_path / "output"))
    monkeypatch.setenv("VS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setitem(app.dependency_overrides, get_job_manager, lambda: None)

    response = client.post("/api/v1/jobs/analyze", json={"subpath": "../outside"})

    assert response.status_code == 400


def test_api_list_tracks_matches_directory_boundary(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("VS_INPUT_ROOT", str(tmp_path / "music"))
    monkeypatch.setenv("VS_OUTPUT_ROOT", str(tmp_path / "output"))
    monkeypatch.setenv("VS_DATA_DIR", str(data_dir))
    db_path = data_dir / "volume_stabilizer.db"
    init_db(db_path)
    repo = Repository(db_path)
    for name in ("House", "House2", "Set_1", "SetA1"):
        relative_path = f"{name}/track.mp3"
        repo.upsert_track(
            audio_hash=name,
            relative_path=relative_path,
            input_path=f"/music/{relative_path}",
            output_path=f"/output/{relative_path}",
            input_format="mp3",
            output_format="mp3",
            file_size=1,
            mtime=1.0,
        )

    response = client.get("/api/v1/tracks", params={"path": "House"})
    wildcard_response = client.get("/api/v1/tracks", params={"path": "Set_1"})

    assert response.status_code == 200
    assert [track["relative_path"] for track in response.json()["tracks"]] == ["House/track.mp3"]
    assert [track["relative_path"] for track in wildcard_response.json()["tracks"]] == ["Set_1/track.mp3"]


def test_api_job_track_queries_match_directory_boundary(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("VS_INPUT_ROOT", str(tmp_path / "music"))
    monkeypatch.setenv("VS_OUTPUT_ROOT", str(tmp_path / "output"))
    monkeypatch.setenv("VS_DATA_DIR", str(data_dir))
    db_path = data_dir / "volume_stabilizer.db"
    init_db(db_path)
    repo = Repository(db_path)
    for name in ("House", "House2"):
        relative_path = f"{name}/track.mp3"
        repo.upsert_track(
            audio_hash=name,
            relative_path=relative_path,
            input_path=f"/music/{relative_path}",
            output_path=f"/output/{relative_path}",
            input_format="mp3",
            output_format="mp3",
            file_size=1,
            mtime=1.0,
        )
    analyze_job = repo.create_job("ANALYZE", "House")

    class JobManagerStub:
        def run_convert_job(self, *args, **kwargs):
            pass

    monkeypatch.setitem(app.dependency_overrides, get_job_manager, lambda: JobManagerStub())
    job_tracks = client.get(f"/api/v1/jobs/{analyze_job.id}/tracks")
    convert_job = client.post("/api/v1/jobs/convert", json={"analyze_job_id": analyze_job.id})

    assert [track["relative_path"] for track in job_tracks.json()["tracks"]] == ["House/track.mp3"]
    assert convert_job.status_code == 200
    assert convert_job.json()["track_count"] == 1
