# =====================================================================
# JottaBackup GUI – Dockerfile
# Basert på Python 3.12 slim + jottacloud-cli via offisiell apt-repo
# =====================================================================
FROM python:3.12-slim

# Installasjon av systemavhengigheter
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Legg til Jottacloud apt-repo og installer jotta-cli
RUN echo "deb [trusted=yes] https://repo.jotta.cloud/debian debian main" \
        > /etc/apt/sources.list.d/jottacloud.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends jotta-cli \
    && rm -rf /var/lib/apt/lists/*

# Python-avhengigheter
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopier kildekode
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Datamapper
RUN mkdir -p /data /logs

# Miljøvariabler med standardverdier (overstyres i docker-compose)
ENV DATA_DIR=/data \
    LOG_DIR=/logs \
    PORT=3600 \
    TZ=Europe/Oslo \
    APP_PASSWORD=jotta123 \
    SECRET_KEY=change-me-please \
    XDG_CONFIG_HOME=/data

EXPOSE 3600

# Start jottad + gunicorn via oppstartsskript
CMD ["/start.sh"]
