# ── Stage 1: Build ──────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# 安裝編譯依賴（lxml、asyncpg 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 2: Runtime ────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# 只複製 pip 安裝的套件，不帶編譯工具
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# 複製應用程式原始碼
COPY app/ ./app/

# 預下載 jieba 詞典（避免首次啟動延遲）
RUN python -c "import jieba; jieba.initialize()"

EXPOSE 8000

# Render 建議使用 0.0.0.0 並讀取 PORT 環境變數
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
