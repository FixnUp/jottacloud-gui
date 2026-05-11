"""
JottaCloud Backup GUI - Backend API
Flask-basert API for administrasjon av Jottacloud CLI-backups på TrueNAS Scale.
"""

import os
import json
import subprocess
import threading
import uuid
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
# Hjelpefunksjoner – jobber
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
def append_log(level: str, message: str, job_id: str = None):
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
# Backup-kjøring
# ---------------------------------------------------------------------------
running_jobs = {}

def run_backup(job_id: str):
    job = get_job(job_id)
    if not job:
        return

    started = datetime.now().isoformat(timespec="seconds")
    running_jobs[job_id] = {"progress": 0, "started": started}
    update_job_field(job_id, status="running", last_run=started, progress=0)
    append_log("info", f"Backup startet: {job['name']} ({job['source_path']})", job_id)

    env = os.environ.copy()

    dest = job.get("dest_path") or job["name"]
    cmd = [
        "jotta-cli", "archive",
        job["source_path"],
        f"--remote={dest}",
        "--nogui",
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
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
                             last_run=started, last_success=finished,
                             last_error=None)
            append_log("success", f"Backup fullført: {job['name']}", job_id)
        else:
            err = "\n".join(output_lines[-5:])
            update_job_field(job_id, status="error", progress=0,
                             last_run=started, last_error=err)
            append_log("error", f"Backup feilet: {job['name']} — {err}", job_id)

    except FileNotFoundError:
        msg = "jotta-cli ikke funnet. Sjekk installasjonen."
        update_job_field(job_id, status="error", progress=0, last_error=msg)
        append_log("error", f"{job['name']}: {msg}", job_id)
    except Exception as e:
        update_job_field(job_id, status="error", progress=0, last_error=str(e))
        append_log("error", f"Uventet feil for {job['name']}: {e}", job_id)
    finally:
        running_jobs.pop(job_id, None)


def run_backup_async(job_id: str):
    t = threading.Thread(target=run_backup, args=(job_id,), daemon=True)
    running_jobs.setdefault(job_id, {})["thread"] = t
    t.start()


def register_job_schedule(job: dict):
    sched_id = f"backup_{job['id']}"
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
    trigger = CronTrigger(
        minute=minute, hour=hour, day=dom,
        month=month, day_of_week=dow, timezone=TZ
    )
    scheduler.add_job(
        run_backup_async,
        trigger=trigger,
        args=[job["id"]],
        id=sched_id,
        replace_existing=True,
    )
    append_log("info", f"Planlagt: {job['name']} — {schedule}")

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
# API-endepunkter – Auth
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
# API-endepunkter – Jobber
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
            return jsonify({"error": f"Mangler felt: {field}"}), 400

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
    append_log("info", f"Jobb opprettet: {job['name']}")
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
    sched_id = f"backup_{job_id}"
    if scheduler.get_job(sched_id):
        scheduler.remove_job(sched_id)
    append_log("info", f"Jobb slettet: {job_id}")
    return jsonify({"ok": True})

@app.route("/api/jobs/<job_id>/run", methods=["POST"])
@login_required
def run_job_now(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Jobb ikke funnet"}), 404
    if job_id in running_jobs:
        return jsonify({"error": "Jobben kjører allerede"}), 409
    run_backup_async(job_id)
    return jsonify({"ok": True, "message": f"Backup startet: {job['name']}"})

@app.route("/api/jobs/<job_id>/stop", methods=["POST"])
@login_required
def stop_job(job_id):
    update_job_field(job_id, status="idle", progress=0)
    running_jobs.pop(job_id, None)
    append_log("warning", f"Jobb stoppet manuelt: {job_id}")
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# API-endepunkter – Status/dashboard
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
@app.route("/api/jotta/status")
@login_required
def jotta_status():
    try:
        result = subprocess.run(
            ["jotta-cli", "status"],
            capture_output=True, text=True, timeout=10
        )
        connected = result.returncode == 0
        output = result.stdout or result.stderr
    except FileNotFoundError:
        connected = False
        output = "jotta-cli ikke funnet i PATH"
    except Exception as e:
        connected = False
        output = str(e)
    return jsonify({"connected": connected, "output": output})

# ---------------------------------------------------------------------------
# Jotta-CLI innlogging via personlig token
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
        child = pexpect.spawn("jotta-cli login", encoding="utf-8", timeout=60)
        output_lines = []

        # Samle all output og svar på prompts
        while True:
            idx = child.expect([
                r"[Tt]oken[:\s]+",          # "Personal login token:" el. lign.
                r"[Dd]evice.{0,20}[:\s]+",  # "Device name:" el. lign.
                r"[Ll]ogged in",             # Suksessmelding
                r"[Ss]uccess",
                r"[Ee]rror",
                r"[Ff]ailed",
                pexpect.EOF,
                pexpect.TIMEOUT,
            ], timeout=60)

            output_lines.append(child.before or "")

            if idx == 0:  # Token-prompt
                child.sendline(token)
            elif idx == 1:  # Device name-prompt
                child.sendline(device_name)
            elif idx in (2, 3):  # Suksess
                output_lines.append(child.after or "")
                child.expect(pexpect.EOF, timeout=10)
                output_lines.append(child.before or "")
                full_output = "\n".join(output_lines).strip()
                append_log("success", "Logget inn på Jottacloud")
                return jsonify({"ok": True, "output": full_output})
            elif idx in (4, 5):  # Feil
                output_lines.append(child.after or "")
                child.expect(pexpect.EOF, timeout=10)
                full_output = "\n".join(output_lines).strip()
                append_log("error", f"Jottacloud innlogging feilet: {full_output}")
                return jsonify({"error": full_output or "Innlogging feilet"}), 400
            elif idx == 6:  # EOF – kommandoen er ferdig
                full_output = "\n".join(output_lines).strip()
                # Sjekk exit-kode
                child.close()
                if child.exitstatus == 0:
                    append_log("success", "Logget inn på Jottac