"""
FastAPI 應用程式入口
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import init_db
from app.routers.api import router as api_router
from app.routers.ws import router as ws_router, manager
from app.scheduler import create_scheduler, set_broadcast_callback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 啟動 ──────────────────────────────
    logger.info("Initializing database...")
    await init_db()

    logger.info("Injecting WebSocket broadcast callback...")
    set_broadcast_callback(manager.broadcast)

    logger.info("Starting scheduler...")
    scheduler = create_scheduler()
    scheduler.start()

    yield  # 應用程式運行中

    # ── 關閉 ──────────────────────────────
    logger.info("Shutting down scheduler...")
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="股市情緒即時熱力圖",
    description="PTT Stock 板情緒分析 API",
    version="1.0.0",
    lifespan=lifespan,
)

# 路由
app.include_router(api_router)
app.include_router(ws_router)

# 靜態檔案（前端）
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_frontend():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Frontend not found. Place index.html in app/static/"}


@app.get("/health")
async def health():
    return {"status": "ok"}
