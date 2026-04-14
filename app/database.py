import ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from app.config import get_settings

settings = get_settings()

# 移除 URL 中 asyncpg 不支援的 sslmode 參數，改用 connect_args 傳入
def _clean_url(url: str) -> str:
    import re
    return re.sub(r'[?&]sslmode=[^&]*', '', url).rstrip('?').rstrip('&')

_db_url = _clean_url(settings.DATABASE_URL)

# 判斷是否需要 SSL（Neon / Supabase pooler 都需要）
_needs_ssl = any(x in _db_url for x in ["neon.tech", "pooler.supabase.com", "supabase.co"])

_ssl_ctx = ssl.create_default_context() if _needs_ssl else None

engine = create_async_engine(
    _db_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={"ssl": _ssl_ctx} if _ssl_ctx else {},
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    """建立所有資料表（首次啟動時執行）"""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
