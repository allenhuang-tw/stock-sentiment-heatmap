"""
股民情緒分析引擎
使用 jieba 斷詞 + 自定義情緒字典計算 -1.0 ~ +1.0 分數
"""
import re
import jieba
import jieba.analyse

# ── 自定義股民情緒字典 ──────────────────────────────────────────────
# 格式: { 詞語: 分數 }  正值=看漲/樂觀  負值=看跌/恐慌
SENTIMENT_DICT: dict[str, float] = {
    # ── 極度看漲 (+0.8 ~ +1.0) ──
    "噴發":     0.95,
    "大噴":     0.95,
    "飆漲":     0.90,
    "直接噴":   0.90,
    "漲停":     0.85,
    "漲停鎖死": 0.95,
    "暴漲":     0.85,
    "狂噴":     0.90,
    "起飛":     0.85,
    "火箭":     0.85,
    "賺爛":     0.90,
    "賺翻":     0.90,
    "賺到笑":   0.90,
    "爆量大漲": 0.90,
    "買爆":     0.80,
    "全梭":     0.75,
    "梭哈":     0.70,

    # ── 看漲 (+0.4 ~ +0.79) ──
    "看漲":     0.60,
    "看多":     0.60,
    "多頭":     0.65,
    "強勢":     0.60,
    "突破":     0.60,
    "解套":     0.65,
    "回補":     0.50,
    "反彈":     0.40,
    "強彈":     0.55,
    "上車":     0.50,
    "加碼":     0.55,
    "逢低買進": 0.50,
    "低接":     0.45,
    "獲利":     0.60,
    "獲利了結": 0.55,
    "止跌":     0.40,
    "好日子":   0.50,
    "穩":       0.40,

    # ── 中性偏多 (+0.1 ~ +0.39) ──
    "觀望":     0.10,
    "等待":     0.10,
    "研究":     0.15,
    "持有":     0.20,

    # ── 中性偏空 (-0.1 ~ -0.39) ──
    "注意":    -0.10,
    "小心":    -0.15,
    "謹慎":    -0.20,
    "風險":    -0.25,
    "壓力":    -0.20,
    "震盪":    -0.10,

    # ── 看空 (-0.4 ~ -0.79) ──
    "看空":    -0.60,
    "看跌":    -0.60,
    "空頭":    -0.65,
    "下殺":    -0.60,
    "破支撐":  -0.60,
    "套牢":    -0.65,
    "被套":    -0.60,
    "慘跌":    -0.65,
    "閃崩":    -0.70,
    "崩跌":    -0.70,
    "下跌":    -0.50,
    "大跌":    -0.65,
    "重挫":    -0.65,
    "摜壓":    -0.55,
    "逃跑":    -0.60,
    "停損":    -0.50,
    "認賠":    -0.55,
    "賠錢":    -0.60,
    "虧損":    -0.60,
    "出場":    -0.40,
    "跑了":    -0.50,

    # ── 極度看空/恐慌 (-0.8 ~ -1.0) ──
    "救命":    -0.90,
    "救命啊":  -0.95,
    "斷頭":    -0.95,
    "爆倉":    -0.90,
    "跌停":    -0.85,
    "崩了":    -0.90,
    "血崩":    -0.90,
    "暴跌":    -0.85,
    "割韭菜":  -0.85,
    "被割":    -0.80,
    "慘":      -0.70,
    "慘慘":    -0.80,
    "完了":    -0.85,
    "賠光":    -0.90,
    "虧死":    -0.90,
    "賠死":    -0.90,
    "跌不停":  -0.85,
    "恐慌":    -0.80,
    "崩潰":    -0.85,
    "沒救了":  -0.90,
    "洗盤":    -0.75,
    "大逃殺":  -0.90,
    "熔斷":    -0.85,
    "黑天鵝":  -0.80,
    "GG":      -0.70,
    "gg":      -0.70,

    # ── 特殊 PTT 用語 ──
    "噴噴":    0.80,   # PTT 語境通常指大漲
    "衝衝":    0.70,
    "衝啊":    0.75,
    "抱緊":    0.60,
    "抱好抱滿":0.70,
    "all in":  0.60,
    "ALL IN":  0.60,
    "嘎空":    0.75,
    "軋空":    0.75,
    "拉抬":    0.65,
    "護盤":    0.40,
}

# 加入到 jieba 自定義詞庫，避免被錯誤斷詞
for word in SENTIMENT_DICT:
    jieba.add_word(word)

# 否定詞，遇到後反轉後一個情緒詞的分數
NEGATION_WORDS = {"不", "沒", "非", "別", "莫", "未", "無"}

# 強化詞，乘上倍率
INTENSIFIER_WORDS = {
    "超": 1.3, "很": 1.2, "極": 1.4, "最": 1.3,
    "非常": 1.3, "真的": 1.1, "完全": 1.2, "根本": 1.2,
}


def analyze(text: str) -> float:
    """
    分析單筆文字的情緒分數。
    回傳 -1.0（極度恐慌）~ +1.0（極度貪婪）
    """
    if not text.strip():
        return 0.0

    tokens = list(jieba.cut(text, cut_all=False))
    scores: list[float] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        multiplier = 1.0

        # 往前看否定詞
        if i > 0 and tokens[i - 1] in NEGATION_WORDS:
            multiplier *= -1.0

        # 往前看強化詞
        if i > 0 and tokens[i - 1] in INTENSIFIER_WORDS:
            multiplier *= INTENSIFIER_WORDS[tokens[i - 1]]

        if token in SENTIMENT_DICT:
            scores.append(SENTIMENT_DICT[token] * multiplier)

        i += 1

    if not scores:
        return 0.0

    # 加權平均：極端分數權重更高
    weighted = sum(s * abs(s) for s in scores)
    total_weight = sum(abs(s) for s in scores)
    raw = weighted / total_weight if total_weight > 0 else 0.0
    return round(max(-1.0, min(1.0, raw)), 4)


def batch_analyze(texts: list[str]) -> float:
    """分析多筆文字，回傳平均情緒分數"""
    if not texts:
        return 0.0
    scores = [analyze(t) for t in texts]
    # 過濾純 0（無情緒詞）的項目，避免稀釋
    active = [s for s in scores if s != 0.0]
    if not active:
        return 0.0
    return round(sum(active) / len(active), 4)


def classify_score(score: float) -> str:
    """將數值分數轉成文字標籤"""
    if score >= 0.6:
        return "極度貪婪"
    if score >= 0.3:
        return "樂觀"
    if score >= 0.1:
        return "偏多"
    if score > -0.1:
        return "中性"
    if score > -0.3:
        return "偏空"
    if score > -0.6:
        return "悲觀"
    return "極度恐慌"
