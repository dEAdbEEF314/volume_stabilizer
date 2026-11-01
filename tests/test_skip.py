import asyncio
import threading
import time
from concurrent.futures import ProcessPoolExecutor

import pytest
from fastapi.testclient import TestClient

from volume_stabilizer.api.app import app
from volume_stabilizer.config import load_config
from volume_stabilizer.core import ffmpeg_runner
from volume_stabilizer.db.database import init_db
from volume_stabilizer.db.repository import Repository
from volume_stabilizer.queue.worker_pool import JobManager


def _sleep_worker(job_id: str) -> str:
    ffmpeg_runner.set_active_job(job_id)
    ffmpeg_runner.run(["sleep", "30"])
    return "done"


def test_request_skip_kills_running_process():
    ffmpeg_runner.set_active_job("job-runner")
    result: dict = {}

    def target():
        try:
            ffmpeg_runner.run(["sleep", "30"])
        except Exception as e:  # noqa: BLE001
            result["exc"] = e

    th = threading.Thread(target=target)
    start = time.monotonic()
    th.start()
    for _ in range(50):
        if ffmpeg_runner._pid_file("job-runner").exists():
            break
        time.sleep(0.1)
    assert ffmpeg_runner.request_skip("job-runner") is True
    th.join(10)

    assert isinstance(result.get("exc"), ffmpeg_runner.SkippedByUser)
    assert time.monotonic() - start < 10
    ffmpeg_runner.set_active_job(None)
    ffmpeg_runner.clear_skip("job-runner")


def test_skip_marker_before_spawn_aborts_process():
    ffmpeg_runner.set_active_job("job-early")
    ffmpeg_runner.request_skip("job-early")
    start = time.monotonic()
    with pytest.raises(ffmpeg_runner.SkippedByUser):
        ffmpeg_runner.run(["sleep", "30"])
    assert time.monotonic() - start < 10
    ffmpeg_runner.set_active_job(None)
    ffmpeg_runner.clear_skip("job-early")


def test_job_manager_skips_current_track():
    jm = JobManager(load_config())
    jm.pool = ProcessPoolExecutor(max_workers=1)

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.call_later(1.0, jm.skip_current, "job-pool")
        with pytest.raises(ffmpeg_runner.SkippedByUser):
            await jm._run_track("job-pool", _sleep_worker)

    start = time.monotonic()
    try:
        asyncio.run(scenario())
    finally:
        jm.pool.shutdown(wait=False, cancel_futures=True)
    assert time.monotonic() - start < 15
    assert jm.skip_current("job-pool") is False


def _hang_worker(job_id: str) -> str:
    ffmpeg_runner.set_active_job(job_id)
    time.sleep(30)  # ffmpeg を介さない I/O 停止を模擬
    return "done"


def _quick_worker(job_id: str) -> str:
    ffmpeg_runner.set_active_job(job_id)
    return "ok"


def test_job_manager_abandons_worker_not_killable(monkeypatch):
    monkeypatch.setattr("volume_stabilizer.queue.worker_pool.SKIP_GRACE_SEC", 1.0)
    jm = JobManager(load_config())
    jm.pool = ProcessPoolExecutor(max_workers=2)

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.call_later(0.5, jm.skip_current, "job-hang")
        with pytest.raises(ffmpeg_runner.SkippedByUser, match="abandoned"):
            await jm._run_track("job-hang", _hang_worker)
        # 放棄後も残りのワーカーで次のトラックを処理できる
        return await jm._run_track("job-hang", _quick_worker)

    start = time.monotonic()
    try:
        assert asyncio.run(scenario()) == "ok"
    finally:
        for p in list(jm.pool._processes.values()):
            p.kill()
        jm.pool.shutdown(wait=False, cancel_futures=True)
    assert time.monotonic() - start < 10


def test_skip_api_404_and_409():
    client = TestClient(app)
    assert client.post("/api/v1/jobs/does-not-exist/skip-current").status_code == 404

    cfg = load_config()
    init_db(cfg.db_path)
    job = Repository(cfg.db_path).create_job(job_type="ANALYZE", target_dir="", force=False)
    assert client.post(f"/api/v1/jobs/{job.id}/skip-current").status_code == 409
