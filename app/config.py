from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/sentiment"
    SCRAPE_INTERVAL_SECONDS: int = 60
    PTT_BOARD: str = "Stock"
    MAX_PAGES: int = 3

    # 監控的股票標的（$標的$格式 或純代號）
    WATCH_SYMBOLS: list[str] = [
        "2330", "2317", "2454", "2382", "3008",
        "4967", "0050", "NVDA", "TSMC", "AAPL",
        "MSFT", "AMD", "INTC", "TSM",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
