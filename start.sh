#!/bin/bash
# =====================================================================
# JottaBackup – Oppstartsskript
# Starter jottad daemon i bakgrunnen, deretter gunicorn
# =====================================================================

echo "Starter jottad daemon..."
jottad &
JOTTAD_PID=$!

# Vent til jottad er klar (maks 10 sekunder)
for i in $(seq 1 10); do
    if jotta-cli status > /dev/null 2>&1; then
        echo "jottad er klar."
        break
    fi
    echo "Venter på jottad... ($i/10)"
    sleep 1
done

echo "Starter gunicorn på port ${PORT:-3600}..."
exec gunicorn \
    --bind "0.0.0.0:${PORT:-3600}" \
    --workers 2 \
    --timeout 120 \
    --chdir /app/backend \
    app:app
