#!/bin/bash
# =====================================================================
# JottaBackup – Oppstartsskript
# Starter jottad daemon i bakgrunnen, deretter gunicorn
# =====================================================================

echo "Starter jottad daemon..."
jottad datadir /data/.jottad stdoutlog &

# Vent til jottad svarer (maks 30 sekunder)
for i in $(seq 1 30); do
    if jotta-cli status > /dev/null 2>&1; then
        echo "jottad er klar etter ${i} sekunder."
        break
    fi
    echo "Venter på jottad... ($i/30)"
    sleep 1
done

echo "Starter gunicorn på port ${PORT:-3600}..."
exec gunicorn \
    --bind "0.0.0.0:${PORT:-3600}" \
    --workers 2 \
    --timeout 120 \
    --chdir /app/backend \
    app:app
