FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install LibreOffice 26.2.x (native Markdown support) from trixie-backports,
# plus fonts. trixie-backports ships LibreOffice 26.2.x for both amd64 and arm64,
# so the multi-arch build keeps working.
RUN echo "deb http://deb.debian.org/debian trixie-backports main" > /etc/apt/sources.list.d/backports.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends -t trixie-backports \
        libreoffice \
    && apt-get install -y --no-install-recommends \
        tini \
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

# Run under tini as PID 1 so orphaned soffice.bin children get reaped instead of
# piling up as <defunct> zombies (uvicorn as PID 1 only reaps its own children).
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
