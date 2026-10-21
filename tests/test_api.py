from fastapi.testclient import TestClient
from volume_stabilizer.api.app import app
from volume_stabilizer.db.database import init_db
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
