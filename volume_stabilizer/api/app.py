"""FastAPI application factory and static file serving."""

from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from volume_stabilizer.config import load_config
from volume_stabilizer.db.database import init_db
from volume_stabilizer.api.routes import router as api_router
from volume_stabilizer.api.websocket import ws_manager


def create_app() -> FastAPI:
    cfg = load_config()
    init_db(cfg.db_path)

    app = FastAPI(
        title="Volume Stabilizer",
        description="DJ Audio Library Loudness Normalizer (EBU R128)",
        version="0.1.0",
    )

    app.include_router(api_router)

    @app.websocket("/ws/progress")
    async def websocket_progress_endpoint(websocket: WebSocket):
        await ws_manager.connect(websocket)
        try:
            while True:
                # Keep connection alive
                await websocket.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

    # Static assets
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/")
        async def serve_index():
            index_path = static_dir / "index.html"
            if index_path.exists():
                return FileResponse(index_path)
            return {"message": "Volume Stabilizer API is running"}

    return app


app = create_app()
