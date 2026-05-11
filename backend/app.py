"""
JottaCloud Backup GUI - Backend API
Flask-basert API for administrasjon av Jottacloud CLI-backups pa TrueNAS Scale.
"""

import os
import json
import subprocess
import threading
import uuid
import time
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# ---------------------------------------------------------------------------
# Konfigurasjon
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
LOG_DIR = Path(os.environ.get("LOG_DIR", "/logs"))
JOBS_FILE = DATA_DIR / "jobs.json"
LOG_FILE = LOG_DIR / "backup.log"
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "jotta123")
TZ = os.environ.get("TZ", "Europe/Oslo")

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Flask-app
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="../frontend", static_url_path="")
app.secret_key = SECRET_KEY
CORS(app, supports_credentials=True)

scheduler = BackgroundScheduler(timezone=TZ)
scheduler.start()

# ---------------------------------------------------------------------------
# Hjelpefunksjoner - jobber
# ---------------------------------------------------------------------------
def load_jobs():
    if JOBS_FILE.exists():
        with open(JOBS_FILE) as f:
            return json.load(f)
    return []

def save_jobs(jobs):
    with open(JOBS_FILE, "w") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

def get_job(job_id):
    return next((j for j in load_jobs() if j["id"] == job_id), None)

def update_job_field(job_id, **kwargs):
    jobs = load_jobs()
    for j in jobs:
        if j["id"] == job_id:
            j.update(kwargs)
    save_jobs(jobs)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def append_log(level, message, job_id=None):
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "level": level,
        "message": message,
        "job_id": job_id,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def read_logs(limit=200):
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text().strip().splitlines()
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    return list(reversed(entries[-limit:]))

# ---------------------------------------------------------------------------
# Backup-kjoring
# ---------------------------------------------------------------------------
running_jobs = {}

def run_backup(job_id):
    job = get_job(job_id)
    if not job:
        return

    started = datetime.now().isoformat(timespec="seconds")
    running_jobs[job_id] = {"progress": 0, "started": started}
    update_job_field(job_id, status="running", last_run=started, progress=0)
    append_log("info", "Backup startet: " + job["name"] + " (" + job["source_path"] + ")", job_id)

    env = os.environ.copy()
    dest = job.get("dest_path") or job["name"]
    cmd = ["jotta-cli", "archive", job["source_path"], "--remote=" + dest, "--nogui"]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        output_lines = []
        for line in proc.stdout:
            line = line.rstrip()
            output_lines.append(line)
            if "%" in line:
                try:
                    pct = int(line.split("%")[0].strip().split()[-1])
                    running_jobs[job_id]["progress"] = min(pct, 99)
                    update_job_field(job_id, progress=min(pct, 99))
                except Exception:
                    pass

        proc.wait()
        finished = datetime.now().isoformat(timespec="seconds")

        if proc.returncode == 0:
            update_job_field(job_id, status="success", progress=100,
                             last_run=started, last_success=finished, last_error=None)
            append_log("success", "Backup fullfort: " + job["name"], job_id)
        else:
            err = "\n".join(output_lines[-5:])
            update_job_field(job_id, status="error", progress=0, last_run=started, last_error=err)
            append_log("error", "Backup feilet: " + job["name"] + " - " + err, job_id)

    except FileNotFoundError:
        msg = "jotta-cli ikke funnet. Sjekk installasjonen."
        update_job_field(job_id, status="error", progress=0, last_error=msg)
        append_log("error", job["name"] + ": " + msg, job_id)
    except Exception as e:
        update_job_field(job_id, status="error", progress=0, last_error=str(e))
        append_log("error", "Uventet feil for " + job["name"] + ": " + str(e), job_id)
    finally:
        running_jobs.pop(job_id, None)


def run_backup_async(job_id):
    t = threading.Thread(target=run_backup, args=(job_id,), daemon=True)
    running_jobs.setdefault(job_id, {})["thread"] = t
    t.start()


def register_job_schedule(job):
    sched_id = "backup_" + job["id"]
    if scheduler.get_job(sched_id):
        scheduler.remove_job(sched_id)
    if not job.get("enabled", True):
        return
    schedule = job.get("schedule", "")
    if not schedule:
        return
    parts = schedule.strip().split()
    if len(parts) != 5:
        return
    minute, hour, dom, month, dow = parts
    trigger = CronTrigger(minute=minute, hour=hour, day=dom,
                          month=month, day_of_week=dow, timezone=TZ)
    scheduler.add_job(run_backup_async, trigger=trigger, args=[job["id"]],
                      id=sched_id, replace_existing=True)
    append_log("info", "Planlagt: " + job["name"] + " - " + schedule)

def bootstrap_schedules():
    for job in load_jobs():
        register_job_schedule(job)

bootstrap_schedules()

# ---------------------------------------------------------------------------
# Auth-dekorator
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "Ikke innlogget"}), 401
        return f(*args, **kwargs)
    return decorated

# ---------------------------------------------------------------------------
# API-endepunkter - Auth
# ---------------------------------------------------------------------------
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    if data.get("password") == APP_PASSWORD:
        session["authenticated"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "Feil passord"}), 401

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/auth/status")
def auth_status():
    return jsonify({"authenticated": bool(session.get("authenticated"))})

# ---------------------------------------------------------------------------
# API-endepunkter - Jobber
# ---------------------------------------------------------------------------
@app.route("/api/jobs", methods=["GET"])
@login_required
def list_jobs():
    jobs = load_jobs()
    for j in jobs:
        if j["id"] in running_jobs:
            j["progress"] = running_jobs[j["id"]].get("progress", 0)
            j["status"] = "running"
    return jsonify(jobs)

@app.route("/api/jobs", methods=["POST"])
@login_required
def create_job():
    data = request.get_json(force=True)
    required = ["name", "source_path", "schedule"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": "Mangler felt: " + field}), 400

    job = {
        "id": str(uuid.uuid4()),
        "name": data["name"],
        "source_path": data["source_path"],
        "dest_path": data.get("dest_path", data["name"]),
        "schedule": data["schedule"],
        "enabled": data.get("enabled", True),
        "status": "idle",
        "progress": 0,
        "last_run": None,
        "last_success": None,
        "last_error": None,
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    jobs = load_jobs()
    jobs.append(job)
    save_jobs(jobs)
    register_job_schedule(job)
    append_log("info", "Jobb opprettet: " + job["name"])
    return jsonify(job), 201

@app.route("/api/jobs/<job_id>", methods=["PUT"])
@login_required
def update_job(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Jobb ikke funnet"}), 404
    data = request.get_json(force=True)
    allowed = ["name", "source_path", "dest_path", "schedule", "enabled"]
    for key in allowed:
        if key in data:
            job[key] = data[key]
    jobs = load_jobs()
    for i, j in enumerate(jobs):
        if j["id"] == job_id:
            jobs[i] = job
    save_jobs(jobs)
    register_job_schedule(job)
    return jsonify(job)

@app.route("/api/jobs/<job_id>", methods=["DELETE"])
@login_required
def delete_job(job_id):
    jobs = load_jobs()
    jobs = [j for j in jobs if j["id"] != job_id]
    save_jobs(jobs)
    sched_id = "backup_" + job_id
    if scheduler.get_job(sched_id):
        scheduler.remove_job(sched_id)
    append_log("info", "Jobb slettet: " + job_id)
    return jsonify({"ok": True})

@app.route("/api/jobs/<job_id>/run", methods=["POST"])
@login_required
def run_job_now(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Jobb ikke funnet"}), 404
    if job_id in running_jobs:
        return jsonify({"error": "Jobben kjorer allerede"}), 409
    run_backup_async(job_id)
    return jsonify({"ok": True, "message": "Backup startet: " + job["name"]})

@app.route("/api/jobs/<job_id>/stop", methods=["POST"])
@login_required
def stop_job(job_id):
    update_job_field(job_id, status="idle", progress=0)
    running_jobs.pop(job_id, None)
    append_log("warning", "Jobb stoppet manuelt: " + job_id)
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# API-endepunkter - Status/dashboard
# ---------------------------------------------------------------------------
@app.route("/api/stats")
@login_required
def stats():
    jobs = load_jobs()
    total = len(jobs)
    successful = sum(1 for j in jobs if j.get("status") == "success")
    running = sum(1 for j in jobs if j.get("id") in running_jobs)
    errors = sum(1 for j in jobs if j.get("status") == "error")

    last_success = None
    for j in sorted(jobs, key=lambda x: x.get("last_success") or "", reverse=True):
        if j.get("last_success"):
            last_success = j["last_success"]
            break

    return jsonify({
        "total_jobs": total,
        "successful": successful,
        "running": running,
        "errors": errors,
        "last_success": last_success,
    })

@app.route("/api/logs")
@login_required
def get_logs():
    limit = int(request.args.get("limit", 100))
    job_id = request.args.get("job_id")
    entries = read_logs(limit * 2)
    if job_id:
        entries = [e for e in entries if e.get("job_id") == job_id]
    return jsonify(entries[:limit])

# ---------------------------------------------------------------------------
# Jotta-CLI status
# ---------------------------------------------------------------------------
_jotta_status_cache = {"result": None, "ts": 0}
_JOTTA_STATUS_TTL = 30  # sekunder

@app.route("/api/jotta/status")
@login_required
def jotta_status():
    now = time.time()
    cached = _jotta_status_cache
    if cached["result"] is not None and (now - cached["ts"]) < _JOTTA_STATUS_TTL:
        return jsonify(cached["result"])
    try:
        result = subprocess.run(["jotta-cli", "status"],
                                capture_output=True, text=True, timeout=10)
        connected = result.returncode == 0
        output = result.stdout or result.stderr
    except FileNotFoundError:
        connected = False
        output = "jotta-cli ikke funnet i PATH"
    except Exception as e:
        connected = False
        output = str(e)
    payload = {"connected": connected, "output": output}
    _jotta_status_cache["result"] = payload
    _jotta_status_cache["ts"] = now
    return jsonify(payload)

# ---------------------------------------------------------------------------
# Jotta-CLI innlogging via pexpect (PTY-basert)
# Prompts fra jotta-cli login:
#   1. "accept license (yes/no):" -> svar "yes"
#   2. "Personal login token:" (eller lignende) -> svar med token
#   3. "Device name:" (eller lignende) -> svar med device_name
# ---------------------------------------------------------------------------
@app.route("/api/jotta/login", methods=["POST"])
@login_required
def jotta_login():
    data = request.get_json(force=True)
    token = data.get("token", "").strip()
    device_name = data.get("device_name", "JottaBackup-TrueNAS").strip()

    if not token:
        return jsonify({"error": "Token mangler"}), 400

    try:
        import pexpect
    except ImportError:
        return jsonify({"error": "pexpect ikke installert - bygg nytt Docker-image"}), 500

    try:
        debug_log = open(str(LOG_DIR / "jotta_login_debug.log"), "a")
        child = pexpect.spawn("jotta-cli login", encoding="utf-8", timeout=20)
        child.logfile_read = debug_log
        output_lines = []

        while True:
            idx = child.expect([
                r"accept license \(yes/no\):",   # 0 - lisensavtale
                r"[Tt]oken[:\s]+",               # 1 - token-prompt
                r"[Dd]evice.{0,20}[:\s]+",       # 2 - enhetsnavn-prompt
                r"[Ll]ogged in",                 # 3 - suksess
                r"[Ss]uccess",                   # 4 - suksess
                r"[Ee]rror",                     # 5 - feil
                r"[Ff]ailed",                    # 6 - feil
                pexpect.EOF,                     # 7 - ferdig
                pexpect.TIMEOUT,                 # 8 - timeout
            ], timeout=20)

            output_lines.append(child.before or "")

            if idx == 0:
                child.sendline("yes")
            elif idx == 1:
                child.sendline(token)
            elif idx == 2:
                child.sendline(device_name)
            elif idx in (3, 4):
                output_lines.append(child.after or "")
                child.expect(pexpect.EOF, timeout=10)
                output_lines.append(child.before or "")
                full_output = "\n".join(output_lines).strip()
                append_log("success", "Logget inn pa Jottacloud")
                _jotta_status_cache["result"] = None  # tøm cache etter login
                return jsonify({"ok": True, "output": full_output})
            elif idx in (5, 6):
                output_lines.append(child.after or "")
                child.expect(pexpect.EOF, timeout=10)
                full_output = "\n".join(output_lines).strip()
                append_log("error", "Jottacloud innlogging feilet: " + full_output)
                return jsonify({"error": full_output or "Innlogging feilet"}), 400
            elif idx == 7:
                full_output = "\n".join(output_lines).strip()
                child.close()
                if child.exitstatus == 0:
                    append_log("success", "Logget inn pa Jottacloud")
                    _jotta_status_cache["result"] = None  # tøm cache etter login
                    return jsonify({"ok": True, "output": full_output})
                else:
                    append_log("error", "Jottacloud innlogging feilet: " + full_output)
                    return jsonify({"error": full_output or "Innlogging feilet"}), 400
            else:
                collected = "\n".join(output_lines).strip()
                child.close(force=True)
                append_log("error", "jotta-cli login timeout. Output: " + repr(collected))
                return jsonify({
                    "error": "Tidsavbrudd",
                    "debug": collected or "(ingen output fra jotta-cli)"
                }), 504

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/jotta/logout", methods=["POST"])
@login_required
def jotta_logout():
    try:
        result = subprocess.run(["jotta-cli", "logout"],
                                capture_output=True, text=True, timeout=10)
        output = result.stdout + result.stderr
        append_log("info", "Logget ut av Jottacloud")
        _jotta_status_cache["result"] = None  # tøm cache etter logout
        return jsonify({"ok": True, "output": output})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# Frontend-serving
# ---------------------------------------------------------------------------
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    frontend = Path(app.static_folder)
    target = frontend / path
    if path and target.exists():
        return send_from_directory(str(frontend), path)
    return send_from_directory(str(frontend), "index.html")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3600))
    app.run(host="0.0.0.0", port=port, debug=False)
