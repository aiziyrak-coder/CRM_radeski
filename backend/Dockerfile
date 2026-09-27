FROM python:3.12-slim

# ffmpeg: call recordings (two mono WAVs from Asterisk -> one stereo MP3)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    TZ=Asia/Tashkent

WORKDIR /app

# Install dependencies only; the project itself runs from /app via PYTHONPATH
COPY pyproject.toml ./
RUN pip install --upgrade "pip>=26.2" \
    && mkdir app && touch app/__init__.py \
    && pip install ".[dev]" \
    && pip uninstall -y radeski-crm \
    && rm -rf app build ./*.egg-info

COPY . .

RUN useradd --create-home --uid 10001 crm && chown -R crm /app
USER crm

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
