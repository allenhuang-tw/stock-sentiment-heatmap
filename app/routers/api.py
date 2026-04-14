"""
REST API 路由
GET /api/latest      - 所有標的最新情緒
GET /api/history/{symbol} - 指定標的歷史走勢（預設最近 60 筆）
POST /api/trigger    - 手動觸發一次爬蟲（測試用）
"""
import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import SentimentRecord, LatestSentiment
from app.sentiment import classify_score

router = APIRouter(prefix="/api", tags=["sentiment"])
logger = logging.getLogger(__name__)


@router.get("/latest", response_model=list[LatestSentiment])
async def get_latest(session: AsyncSession = Depends(get_session)):
    """每個標的取最新一筆情緒快照，並附上趨勢方向"""
    # 取最近 2 小時內的最新記錄
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)

    stmt = (
        select(SentimentRecord)
        .where(SentimentRecord.recorded_at >= cutoff)
        .order_by(SentimentRecord.symbol, desc(SentimentRecord.recorded_at))
    )
    result = await session.execute(stmt)
    all_records = result.scalars().all()

    # 每個 symbol 取最新 2 筆，計算趨勢
    latest_map: dict[str, list[SentimentRecord]] = {}
    for rec in all_records:
        if rec.symbol not in latest_map:
            latest_map[rec.symbol] = []
        if len(latest_map[rec.symbol]) < 2:
            latest_map[rec.symbol].append(rec)

    output = []
    for symbol, records in latest_map.items():
        current = records[0]
        prev = records[1] if len(records) > 1 else None

        if prev is None or abs(current.score - prev.score) < 0.05:
            trend = "flat"
        elif current.score > prev.score:
            trend = "up"
        else:
            trend = "down"

        output.append(LatestSentiment(
            symbol=symbol,
            score=current.score,
            post_count=current.post_count,
            bullish_count=current.bullish_count,
            bearish_count=current.bearish_count,
            sample_titles=json.loads(current.sample_titles or "[]"),
            recorded_at=current.recorded_at,
            trend=trend,
            prev_score=prev.score if prev else None,
        ))

    # 依分數降序排列
    output.sort(key=lambda x: x.score, reverse=True)
    return output


@router.get("/history/{symbol}")
async def get_history(
    symbol: str,
    limit: int = Query(default=60, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """取得指定標的的歷史情緒走勢"""
    stmt = (
        select(SentimentRecord)
        .where(SentimentRecord.symbol == symbol.upper())
        .order_by(desc(SentimentRecord.recorded_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    if not records:
        raise HTTPException(status_code=404, detail=f"No data for symbol {symbol}")

    return [
        {
            "score": r.score,
            "label": classify_score(r.score),
            "post_count": r.post_count,
            "recorded_at": r.recorded_at.isoformat(),
        }
        for r in reversed(records)  # 時間正序
    ]


@router.post("/trigger")
async def manual_trigger():
    """手動觸發一次爬蟲任務（開發 / 測試用）"""
    from app.scheduler import _run_scrape_and_analyze
    import asyncio
    asyncio.create_task(_run_scrape_and_analyze())
    return {"message": "Scrape job triggered in background"}


@router.get("/symbols")
async def list_symbols():
    """列出所有監控中的標的"""
    from app.config import get_settings
    return {"symbols": get_settings().WATCH_SYMBOLS}
