"""
APScheduler 定時任務：每 N 秒抓取 PTT → 計算情緒 → 存 DB → 廣播 WebSocket
"""
import json
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import SentimentRecord
from app.scraper import scrape_ptt
from app.sentiment import analyze, batch_analyze

logger = logging.getLogger(__name__)
settings = get_settings()

# 全域 WebSocket 廣播 callback，由 main.py 注入
_broadcast_callback = None


def set_broadcast_callback(fn):
    global _broadcast_callback
    _broadcast_callback = fn


async def _run_scrape_and_analyze():
    """核心任務邏輯"""
    logger.info("--- Scrape job started at %s ---", datetime.now(timezone.utc).isoformat())

    try:
        symbol_titles = await scrape_ptt()
    except Exception as e:
        logger.error("Scrape failed: %s", e)
        return

    if not symbol_titles:
        logger.info("No relevant posts found this round.")
        return

    results = []
    async with AsyncSessionLocal() as session:
        session: AsyncSession
        for symbol, titles in symbol_titles.items():
            scores = [analyze(t) for t in titles]
            avg_score = batch_analyze(titles)
            bullish = sum(1 for s in scores if s > 0.1)
            bearish = sum(1 for s in scores if s < -0.1)

            record = SentimentRecord(
                symbol=symbol,
                score=avg_score,
                post_count=len(titles),
                bullish_count=bullish,
                bearish_count=bearish,
                sample_titles=json.dumps(titles[:5], ensure_ascii=False),
                recorded_at=datetime.now(timezone.utc),
            )
            session.add(record)
            results.append(record)

            logger.info(
                "Symbol %-8s | score=%+.3f | posts=%d (B:%d/Br:%d)",
                symbol, avg_score, len(titles), bullish, bearish,
            )

        await session.commit()

    # 廣播最新資料到所有 WebSocket 客戶端
    if _broadcast_callback and results:
        payload = [
            {
                "symbol": r.symbol,
                "score": r.score,
                "post_count": r.post_count,
                "bullish_count": r.bullish_count,
                "bearish_count": r.bearish_count,
                "sample_titles": json.loads(r.sample_titles),
                "recorded_at": r.recorded_at.isoformat(),
            }
            for r in results
        ]
        await _broadcast_callback(json.dumps({"type": "update", "data": payload}))

    logger.info("--- Scrape job finished, %d symbols updated ---", len(results))


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Taipei")
    scheduler.add_job(
        _run_scrape_and_analyze,
        trigger="interval",
        seconds=settings.SCRAPE_INTERVAL_SECONDS,
        id="scrape_ptt",
        replace_existing=True,
        misfire_grace_time=30,
    )
    return scheduler
