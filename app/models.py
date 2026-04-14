from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class SentimentRecord(SQLModel, table=True):
    """每分鐘的標的情緒快照"""
    __tablename__ = "sentiment_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, max_length=20)
    score: float = Field(ge=-1.0, le=1.0)
    post_count: int = Field(default=0)
    bullish_count: int = Field(default=0)
    bearish_count: int = Field(default=0)
    sample_titles: str = Field(default="")   # JSON 字串，存最多 5 筆標題
    recorded_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class LatestSentiment(SQLModel):
    """API 回傳用 Schema（非資料表）"""
    symbol: str
    score: float
    post_count: int
    bullish_count: int
    bearish_count: int
    sample_titles: list[str]
    recorded_at: datetime
    trend: str  # "up" | "down" | "flat"
    prev_score: Optional[float] = None
