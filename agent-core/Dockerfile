FROM python:3.12-slim

WORKDIR /app

# システム依存（Playwright Chromium 用）
RUN apt-get update && apt-get install -y \
    curl wget gnupg ca-certificates \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxcb1 libxkbcommon0 libx11-6 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
    libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Python 依存（キャッシュ効率のため src コピー前に依存のみ先インストール）
COPY pyproject.toml .
# src ディレクトリがないと editable install が失敗するためダミーを作成
RUN mkdir -p src && pip install --no-cache-dir -e ".[dev]"

# ※ Chromium は別コンテナ（browser サービス）で起動し CDP 経由で接続するためここにはインストール不要

# アプリケーションコピー（上書き）
COPY src/ ./src/

# 設定・データディレクトリはボリュームでマウント
VOLUME ["/app/config", "/app/data"]

CMD ["python", "src/main.py"]
