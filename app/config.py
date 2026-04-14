from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/sentiment"
    SCRAPE_INTERVAL_SECONDS: int = 60
    PTT_BOARD: str = "Stock"
    MAX_PAGES: int = 3
    SCRAPE_CONTENT: bool = True       # 是否進入文章抓推文
    MAX_POSTS_PER_RUN: int = 15       # 每輪最多深入爬幾篇
    REQ_DELAY_MIN: float = 0.8        # 最短請求間隔（秒）
    REQ_DELAY_MAX: float = 2.5        # 最長請求間隔（秒）

    # 監控的股票標的（$標的$格式 或純代號）
    WATCH_SYMBOLS: list[str] = [
        # 台股熱門
        "2330", "2317", "2454", "2382", "3008",
        "4967", "0050", "2303", "2308", "2357",
        "2379", "3711", "2002", "2412", "2881",
        "2882", "2884", "2886", "6669", "3661",
        # 美股熱門
        "NVDA", "AAPL", "MSFT", "AMD", "INTC", "TSM",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
