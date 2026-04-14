"""
非同步 PTT Stock 板爬蟲
抓取文章標題，過濾出監控標的，回傳原始標題列表
"""
import re
import asyncio
import logging
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

PTT_BASE = "https://www.ptt.cc"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://www.ptt.cc/bbs/Stock/index.html",
}
COOKIES = {"over18": "1"}

# 中文公司名 → 標的代號對照表
# PTT 文章通常用中文名稱，不用股票代號
CHINESE_NAME_MAP: dict[str, str] = {
    # 台股
    "台積電": "2330",
    "台積":   "2330",
    "tsmc":   "2330",
    "鴻海":   "2317",
    "鴻準":   "2317",
    "聯發科": "2454",
    "聯發":   "2454",
    "廣達":   "2382",
    "大立光": "3008",
    "立光":   "3008",
    "十銓":   "4967",
    "元大台灣50": "0050",
    "台灣50": "0050",
    "中鋼":   "2002",
    "台塑":   "1301",
    "南亞":   "1303",
    "中華電": "2412",
    "中華電信": "2412",
    "富邦金": "2881",
    "國泰金": "2882",
    "玉山金": "2884",
    "兆豐金": "2886",
    "台新金": "2887",
    "永豐金": "2890",
    "聯電":   "2303",
    "瑞昱":   "2379",
    "日月光": "3711",
    "華碩":   "2357",
    "宏碁":   "2353",
    "台達電": "2308",
    "研華":   "2395",
    "緯創":   "3231",
    "仁寶":   "2324",
    "緯穎":   "6669",
    "創意":   "3443",
    "世芯":   "3661",
    "力積電": "6770",
    "欣興":   "3037",
    "華邦電": "2344",
    "南亞科": "2408",
    # 美股
    "輝達":   "NVDA",
    "nvidia": "NVDA",
    "nvda":   "NVDA",
    "超微":   "AMD",
    "amd":    "AMD",
    "蘋果":   "AAPL",
    "apple":  "AAPL",
    "微軟":   "MSFT",
    "microsoft": "MSFT",
    "英特爾": "INTC",
    "intel":  "INTC",
}


@dataclass
class PostInfo:
    title: str
    symbols: list[str] = field(default_factory=list)
    url: str = ""


def _extract_symbols(title: str, watch_symbols: list[str]) -> list[str]:
    """
    從標題中抽取標的代號。
    支援：
      1. $2330$ $NVDA$ 格式
      2. 純數字/英文代號（用非英數字元做邊界，相容中文語境）
      3. 中文公司名稱對照
    """
    found = set()
    watch_upper = {s.upper() for s in watch_symbols}

    # ── 1. $XXX$ 格式 ─────────────────────────────────────────────
    for m in re.findall(r'\$([A-Z0-9]{2,10})\$', title.upper()):
        if m in watch_upper:
            found.add(m)

    # ── 2. 代號直接出現（用非英數字元做邊界，相容中文）────────────
    for sym in watch_upper:
        # (?<![0-9A-Za-z]) 確保前面不是英數；(?![0-9A-Za-z]) 確保後面不是英數
        if re.search(rf'(?<![0-9A-Za-z]){re.escape(sym)}(?![0-9A-Za-z])', title.upper()):
            found.add(sym)

    # ── 3. 中文公司名稱對照 ───────────────────────────────────────
    title_lower = title.lower()
    for name, sym in CHINESE_NAME_MAP.items():
        sym_upper = sym.upper()
        if sym_upper not in watch_upper:
            continue
        if name.lower() in title_lower:
            found.add(sym_upper)

    return list(found)


async def _fetch_page(client: httpx.AsyncClient, url: str) -> list[PostInfo]:
    """爬取單頁文章列表，回傳 PostInfo 列表"""
    try:
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.warning("PTT fetch error %s: %s", url, e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    posts: list[PostInfo] = []

    watch_upper = [s.upper() for s in settings.WATCH_SYMBOLS]

    for div in soup.select("div.r-ent"):
        title_tag = div.select_one("div.title a")
        if title_tag is None:
            continue   # 被刪除的文章

        title = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")
        syms = _extract_symbols(title, watch_upper)

        if syms:
            posts.append(PostInfo(title=title, symbols=syms, url=PTT_BASE + href))

    logger.debug("Page %s: found %d matching posts", url, len(posts))
    return posts


async def _get_prev_page_url(client: httpx.AsyncClient, current_url: str) -> str | None:
    """取得上一頁的 URL"""
    try:
        resp = await client.get(current_url, timeout=10)
        resp.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    prev = soup.select_one("a.btn.wide:nth-of-type(2)")
    if prev and prev.get("href"):
        return PTT_BASE + prev["href"]
    return None


async def scrape_ptt(max_pages: int | None = None) -> dict[str, list[str]]:
    """
    爬取 PTT Stock 板最近 N 頁的標題。

    回傳格式:
        { "2330": ["標題A", "標題B", ...], "NVDA": [...], ... }
    """
    pages = max_pages or settings.MAX_PAGES
    index_url = f"{PTT_BASE}/bbs/{settings.PTT_BOARD}/index.html"

    symbol_titles: dict[str, list[str]] = {
        s.upper(): [] for s in settings.WATCH_SYMBOLS
    }

    async with httpx.AsyncClient(headers=HEADERS, cookies=COOKIES) as client:
        current_url = index_url
        for page_num in range(pages):
            logger.info("Scraping PTT page %d: %s", page_num + 1, current_url)
            posts = await _fetch_page(client, current_url)

            for post in posts:
                for sym in post.symbols:
                    if sym in symbol_titles:
                        symbol_titles[sym].append(post.title)

            if page_num < pages - 1:
                prev = await _get_prev_page_url(client, current_url)
                if prev is None:
                    break
                current_url = prev
                await asyncio.sleep(0.5)

    matched = {k: v for k, v in symbol_titles.items() if v}
    logger.info("Scrape complete: %d symbols matched", len(matched))
    return matched
