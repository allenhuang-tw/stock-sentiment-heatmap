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
# PTT 需要帶 over18 cookie
COOKIES = {"over18": "1"}


@dataclass
class PostInfo:
    title: str
    symbols: list[str] = field(default_factory=list)
    url: str = ""


def _extract_symbols(title: str, watch_symbols: list[str]) -> list[str]:
    """
    從標題中抽取標的代號。
    支援格式：
      - $2330$  $NVDA$  (PTT 慣用標記法)
      - 純數字代號（2330, 4967）
      - 英文代號（NVDA, AAPL）
    """
    found = set()

    # 格式 $XXX$
    dollar_matches = re.findall(r'\$([A-Z0-9]{2,10})\$', title.upper())
    found.update(dollar_matches)

    title_upper = title.upper()
    for sym in watch_symbols:
        sym_upper = sym.upper()
        # 全詞比對，避免 "23300" 誤命中 "2330"
        if re.search(rf'\b{re.escape(sym_upper)}\b', title_upper):
            found.add(sym_upper)

    return [s for s in found if s in [w.upper() for w in watch_symbols]]


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
                    symbol_titles[sym].append(post.title)

            # 翻到上一頁
            if page_num < pages - 1:
                prev = await _get_prev_page_url(client, current_url)
                if prev is None:
                    break
                current_url = prev
                await asyncio.sleep(0.5)  # 禮貌性延遲，避免被擋

    # 移除沒有資料的標的
    return {k: v for k, v in symbol_titles.items() if v}
