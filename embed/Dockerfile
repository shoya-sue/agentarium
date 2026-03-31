FROM python:3.12-slim

WORKDIR /app

# 依存関係インストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコピー
COPY server.py .

# モデルキャッシュ用ディレクトリ
VOLUME ["/root/.cache/huggingface"]

EXPOSE 8001

CMD ["python", "server.py"]
