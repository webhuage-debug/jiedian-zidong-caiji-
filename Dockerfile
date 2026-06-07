FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    HUAGE_HOST=0.0.0.0 \
    HUAGE_PORT=8765 \
    HUAGE_ROOT=/app \
    HUAGE_DATABASE=/app/data/nodes.db \
    HUAGE_LOG_DIR=/app/data/logs \
    HUAGE_SUB_STORE_URL=http://sub-store:3001

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8765

CMD ["python", "web_app.py"]
