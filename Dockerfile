FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install LibreOffice and fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    fonts-dejavu-core \
    fonts-noto \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    fonts-noto-color-emoji \
    fonts-wqy-microhei \
    fonts-wqy-zenhei \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app/app

# Directories for data and logs
RUN mkdir -p /tmp/o2pdata /tmp/o2plog

# Default environment variables
ENV APIKEY=changeme \
    CONVERT_TIMEOUT=600 \
    MAX_CONCURRENCY=2 \
    CLEANUP_AFTER_SECONDS=3600 \
    LOG_DIR=/tmp/o2plog \
    DATA_DIR=/tmp/o2pdata

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]