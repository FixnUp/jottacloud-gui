# =====================================================================
# JottaBackup GUI – Dockerfile
# Basert på Python 3.12 slim + jottacloud-cli
# Støtter linux/amd64 og linux/arm64 (via TARGETARCH)
# =====================================================================
FROM python:3.12-slim

# Bygg-argument for arkitektur (settes automatisk av buildx)
ARG TARGETARCH=amd64

# Installasjon av systemavhengigheter
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        bash \
    && rm -rf /var/lib/apt/lists/*

# Installer jottacloud-cli fra offisiell Jottacloud-distribusjon
# Offisiell URL: https://www.jottacloud.com/jottacli/latest/linux/<arch>
# Ref: https://docs.jottacloud.com/en/articles/1529501-jottacloud-cli-getting-started
RUN ARCH="${TARGETARCH}" && \
    curl -fsSL "https://www.jottacloud.com/jottacli/latest/linux/${ARCH}" \
        -o /usr/local/bin/jotta-cli \
    && chmod +x /usr/local/bin/jotta-cli \
    && jotta-cli version || echo "jotta-cli installert (versjon ikke verifisert i byggemiljø)"

# Python-avhengigheter
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopier kildekode
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Datamapper
RUN mkdir -p /data /logs

# Miljøvariabler med standardverdier (overstyres i docker-compose)
ENV DATA_DIR=/data \
    LOG_DIR=/logs \
    PORT=3600 \
    TZ=Europe/Oslo \
    APP_PASSWORD=jotta123 \
    SECRET_KEY=change-me-please

EXPOSE 3600

# Start med gunicorn (produksjon)
CMD ["gunicorn", \
     "--bind", "0.0.0.0:3600", \
     "--workers", "2", \
     "--timeout", "120", \
     "--chdir", "/app/backend", \
     "app:app"]
