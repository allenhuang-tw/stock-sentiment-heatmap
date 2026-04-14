"""
非同步 PTT Stock 板爬蟲
- 第一層：掃描文章列表，從標題過濾相關標的
- 第二層：進入文章頁面，抓取推文（推/噓/→）
防封措施：隨機延遲、Semaphore 限制並發、每輪上限篇數
"""
import re
import asyncio
import random
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

# 推文類型對情緒的影響
PUSH_SENTIMENT = {"推": 0.3, "噓": -0.4, "→": 0.0}

# 中文公司名 → 標的代號對照表
CHINESE_NAME_MAP: dict[str, str] = {
    "台積電": "2330", "台積": "2330", "tsmc": "2330",
    "鴻海": "2317", "鴻準": "2317",
    "聯發科": "2454", "聯發": "2454",
    "廣達": "2382",
    "大立光": "3008", "立光": "3008",
    "十銓": "4967",
    "元大台灣50": "0050", "台灣50": "0050",
    "中鋼": "2002",
    "台塑": "1301",
    "南亞": "1303",
    "中華電": "2412", "中華電信": "2412",
    "富邦金": "2881",
    "國泰金": "2882",
    "玉山金": "2884",
    "兆豐金": "2886",
    "台新金": "2887",
    "永豐金": "2890",
    "聯電": "2303",
    "瑞昱": "2379",
    "日月光": "3711",
    "華碩": "2357",
    "宏碁": "2353",
    "台達電": "2308",
    "研華": "2395",
    "緯創": "3231",
    "仁寶": "2324",
    "緯穎": "6669",
    "世芯": "3661",
    "力積電": "6770",
    "欣興": "3037",
    "華邦電": "2344",
    "南亞科": "2408",
    "輝達": "NVDA", "nvidia": "NVDA", "nvda": "NVDA",
    "超微": "AMD", "amd": "AMD",
    "蘋果": "AAPL", "apple": "AAPL",
    "微軟": "MSFT", "microsoft": "MSFT",
    "英特爾": "INTC", "intel": "INTC",
}


@dataclass
class PostInfo:
    title: str
    url: str
    symbols: list[str] = field(default_factory=list)
    push_texts: list[str] = field(default_factory=list)   # 推文內容
    push_scores: list[float] = field(default_factory=list) # 推/噓權重


def _extract_symbols(text: str, watch_symbols: set[str]) -> list[str]:
    """從任意文字中抽取標的代號（標題或推文皆可用）"""
    found = set()

    # $XXX$ 格式
    for m in re.findall(r'\$([A-Z0-9]{2,10})\$', text.upper()):
        if m in watch_symbols:
            found.add(m)

    # 代號直接出現（非英數字元邊界，相容中文）
    for sym in watch_symbols:
        if re.search(rf'(?<![0-9A-Za-z]){re.escape(sym)}(?![0-9A-Za-z])', text.upper()):
            found.add(sym)

    # 中文公司名稱
    text_lower = text.lower()
    for name, sym in CHINESE_NAME_MAP.items():
        if sym.upper() in watch_symbols and name.lower() in text_lower:
            found.add(sym.upper())

    return list(found)


async def _polite_delay():
    """禮貌性隨機延遲，避免觸發 PTT 的速率限制"""
    delay = random.uniform(settings.REQ_DELAY_MIN, settings.REQ_DELAY_MAX)
    await asyncio.sleep(delay)


async def _fetch_post_content(
    client: httpx.AsyncClient,
    post: PostInfo,
    sem: asyncio.Semaphore,
    watch_symbols: set[str],
):
    """
    進入單篇文章頁面，抓取：
    1. 文章內文中的標的提及
    2. 推文（推/噓/→）的情緒與內容
    """
    async with sem:
        await _polite_delay()
        try:
            resp = await client.get(post.url, timeout=12)
            resp.raise_for_status()
        except Exception as e:
            logger.debug("Failed to fetch post %s: %s", post.url, e)
            return

    soup = BeautifulSoup(resp.text, "html.parser")

    # 抓內文（#main-content，去掉 meta 區塊）
    main = soup.select_one("#main-content")
    if main:
        # 移除 meta 標籤文字
        for tag in main.select(".article-metaline, .article-metaline-right"):
            tag.decompose()
        body_text = main.get_text(" ", strip=True)[:2000]  # 最多取 2000 字
        extra_syms = _extract_symbols(body_text, watch_symbols)
        for s in extra_syms:
            if s not in post.symbols:
                post.symbols.append(s)

    # 抓推文
    for push_div in soup.select("div.push"):
        tag_span = push_div.select_one("span.push-tag")
        content_span = push_div.select_one("span.push-content")
        if not tag_span or not content_span:
            continue

        tag = tag_span.get_text(strip=True)          # "推", "噓", "→"
        content = content_span.get_text(strip=True)  # ": 推文內容"
        content = re.sub(r'^:\s*', '', content)       # 去掉開頭的冒號

        score = PUSH_SENTIMENT.get(tag, 0.0)
        post.push_texts.append(content)
        post.push_scores.append(score)

    logger.debug(
        "Post fetched: %d push comments, %d symbols | %s",
        len(post.push_texts), len(post.symbols), post.title[:40]
    )


async def _fetch_index_page(
    client: httpx.AsyncClient,
    url: str,
    watch_symbols: set[str],
) -> tuple[list[PostInfo], str | None]:
    """
    爬取一頁文章列表。
    回傳 (符合標的的文章列表, 上一頁URL)
    """
    try:
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Index fetch error %s: %s", url, e)
        return [], None

    soup = BeautifulSoup(resp.text, "html.parser")
    posts: list[PostInfo] = []

    for div in soup.select("div.r-ent"):
        title_tag = div.select_one("div.title a")
        if title_tag is None:
            continue
        title = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")
        syms = _extract_symbols(title, watch_symbols)
        if syms:
            posts.append(PostInfo(
                title=title,
                url=PTT_BASE + href,
                symbols=syms,
            ))

    # 取得上一頁連結
    prev_url = None
    prev_btn = soup.select_one("a.btn.wide:nth-of-type(2)")
    if prev_btn and prev_btn.get("href"):
        prev_url = PTT_BASE + prev_btn["href"]

    return posts, prev_url


async def scrape_ptt(max_pages: int | None = None) -> dict[str, list[str]]:
    """
    完整爬取流程：
    1. 掃描多頁文章列表，找出標的相關文章
    2. （若啟用）進入每篇文章抓推文與內文
    3. 整合後回傳 { symbol: [相關文字列表] }
    """
    pages = max_pages or settings.MAX_PAGES
    index_url = f"{PTT_BASE}/bbs/{settings.PTT_BOARD}/index.html"
    watch_symbols = {s.upper() for s in settings.WATCH_SYMBOLS}

    all_posts: list[PostInfo] = []

    async with httpx.AsyncClient(headers=HEADERS, cookies=COOKIES) as client:
        # ── 第一層：掃描列表頁 ─────────────────────────────────────
        current_url = index_url
        for page_num in range(pages):
            logger.info("Scanning PTT page %d: %s", page_num + 1, current_url)
            posts, prev_url = await _fetch_index_page(client, current_url, watch_symbols)
            all_posts.extend(posts)

            if page_num < pages - 1 and prev_url:
                current_url = prev_url
                await _polite_delay()
            else:
                break

        logger.info("Phase 1 complete: %d candidate posts found", len(all_posts))

        # ── 第二層：進入文章抓推文（有上限保護）──────────────────
        if settings.SCRAPE_CONTENT and all_posts:
            limit = min(len(all_posts), settings.MAX_POSTS_PER_RUN)
            targets = all_posts[:limit]
            sem = asyncio.Semaphore(2)   # 同時最多 2 個請求

            logger.info("Phase 2: fetching content for %d posts (max %d)",
                        len(targets), settings.MAX_POSTS_PER_RUN)

            tasks = [
                _fetch_post_content(client, post, sem, watch_symbols)
                for post in targets
            ]
            await asyncio.gather(*tasks)

    # ── 整合結果 ───────────────────────────────────────────────────
    # 結構：{ symbol: {"titles": [...], "push_texts": [...], "push_scores": [...]} }
    symbol_data: dict[str, dict] = {
        s: {"titles": [], "push_texts": [], "push_scores": []}
        for s in watch_symbols
    }

    for post in all_posts:
        for sym in post.symbols:
            if sym not in symbol_data:
                continue

            # 文章標題一定歸屬於該標的
            symbol_data[sym]["titles"].append(post.title)

            # 推文：只加入「有提到該標的」或「來自只討論該標的的文章」的推文
            single_symbol_post = len(post.symbols) == 1
            for text, score in zip(post.push_texts, post.push_scores):
                if not text.strip():
                    continue
                push_mentions = _extract_symbols(text, watch_symbols)
                if single_symbol_post or sym in push_mentions or not push_mentions:
                    # 文章只提一個標的 → 所有推文都歸它
                    # 推文有明確提到該標的 → 歸它
                    # 推文沒提任何標的 → 視為對該文章的通用回應，歸屬文章標的
                    prefix = "好棒 " if score > 0 else ("救命 " if score < 0 else "")
                    symbol_data[sym]["push_texts"].append(prefix + text)
                    symbol_data[sym]["push_scores"].append(score)

    # 回傳格式轉換：合併 titles + push_texts 供情緒分析，titles 另外保留供展示
    result: dict[str, dict] = {}
    for sym, data in symbol_data.items():
        if not data["titles"]:
            continue
        result[sym] = {
            "all_texts": data["titles"] + data["push_texts"],
            "titles": data["titles"],          # 只有文章標題（給 sample_titles 用）
            "push_scores": data["push_scores"],
        }

    logger.info("Scrape complete: %d symbols matched", len(result))
    return result
