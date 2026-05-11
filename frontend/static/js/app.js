/* =====================================================================
   JottaBackup GUI – Frontend JavaScript
   ===================================================================== */

const API = "";  // Samme opprinnelse

// ---------------------------------------------------------------------------
// Hjelpefunksjoner
// ---------------------------------------------------------------------------

async function apiFetch(path, opts = {}) {
  const res = await fetch(API + path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (res.status === 401) {
    showLogin();
    return null;
  }
  return res;
}

function fmtDate(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString("no-NO", { dateStyle: "short", timeStyle: "short" });
}

function fmtRelative(iso) {
  if (!iso) return "–";
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return "Akkurat nå";
  if (min < 60) return `${min} min siden`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} t siden`;
  const d = Math.floor(hr / 24);
  return `${d} dag${d > 1 ? "er" : ""} siden`;
}

function statusBadge(status) {
  const map = {
    success: { cls: "badge-success", icon: "ti-check", label: "Ferdig" },
    running: { cls: "badge-warn",    icon: "ti-loader", label: "Kjører" },
    error:   { cls: "badge-error",   icon: "ti-x",      label: "Feil" },
    idle:    { cls: "badge-gray",    icon: "ti-minus",  label: "Venter" },
  };
  const s = map[status] || map.idle;
  return `<span class="badge ${s.cls}"><i class="ti ${s.icon}"></i>${s.label}</span>`;
}

function progressBar(job) {
  const pct = job.progress || 0;
  const barCls = job.status === "error" ? "progress-bar progress-bar--error" : "progress-bar";
  return `<div class="progress-wrap"><div class="${barCls}" style="width:${pct}%"></div></div>`;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Innlogging
// ---------------------------------------------------------------------------

function showLogin() {
  document.getElementById("login-screen").classList.remove("hidden");
  document.getElementById("app").classList.add("hidden");
}

function showApp() {
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  loadDashboard();
  checkJottaStatus();
  startPolling();
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const pw = document.getElementById("password").value;
  const errEl = document.getElementById("login-error");
  errEl.classList.add("hidden");

  const res = await fetch("/api/login", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: pw }),
  });

  if (res.ok) {
    showApp();
  } else {
    errEl.classList.remove("hidden");
    document.getElementById("password").value = "";
  }
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  await apiFetch("/api/logout", { method: "POST" });
  showLogin();
});

// ---------------------------------------------------------------------------
// Sidenavigasjon
// ---------------------------------------------------------------------------

function showPage(pageId) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
  const page = document.getElementById(`page-${pageId}`);
  if (page) page.classList.add("active");
  document.querySelectorAll(`[data-page="${pageId}"]`).forEach(el => el.classList.add("active"));

  if (pageId === "dashboard") loadDashboard();
  if (pageId === "jobs")      loadFullJobsTable();
  if (pageId === "logs")      loadLogs();
  if (pageId === "settings")  checkJottaStatus();
}

document.querySelectorAll("[data-page]").forEach(el => {
  el.addEventListener("click", e => {
    e.preventDefault();
    showPage(el.dataset.page);
  });
});

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

async function loadDashboard() {
  await Promise.all([loadStats(), loadJobsTable(), loadRecentLogs()]);
}

async function loadStats() {
  const res = await apiFetch("/api/stats");
  if (!res) return;
  const s = await res.json();

  document.getElementById("stat-total-jobs").textContent = s.total_jobs;
  document.getElementById("stat-running").textContent = `${s.running} kjører nå`;
  document.getElementById("stat-successful").textContent = s.successful;
  document.getElementById("stat-errors-sub").textContent = `${s.errors} feil`;
  document.getElementById("stat-last-backup").textContent = fmtRelative(s.last_success);
  document.getElementById("stat-last-backup-sub").textContent = s.last_success ? fmtDate(s.last_success) : "Ingen data";

  const statusEl = document.getElementById("stat-status");
  if (s.errors > 0) { statusEl.textContent = "⚠ Feil"; statusEl.style.color = "var(--color-danger)"; }
  else if (s.running > 0) { statusEl.textContent = "↻ Aktiv"; statusEl.style.color = "var(--color-warn)"; }
  else if (s.successful > 0) { statusEl.textContent = "✓ OK"; statusEl.style.color = "var(--color-primary)"; }
  else { statusEl.textContent = "–"; statusEl.style.color = ""; }

  document.getElementById("job-count-badge").textContent = `${s.total_jobs} jobb${s.total_jobs === 1 ? "" : "er"}`;
}

async function loadJobsTable() {
  const res = await apiFetch("/api/jobs");
  if (!res) return;
  const jobs = await res.json();
  const tbody = document.getElementById("jobs-tbody");

  if (!jobs.length) {
    tbody.innerHTML = `<tr id="jobs-empty-row"><td colspan="7" class="empty-state">
      <i class="ti ti-database-off"></i><span>Ingen backup-jobber enda. Klikk «Ny backup-jobb».</span></td></tr>`;
    return;
  }

  tbody.innerHTML = jobs.map(job => `
    <tr data-id="${job.id}">
      <td><span class="job-name">${escHtml(job.name)}</span></td>
      <td><span class="path-code" title="${escHtml(job.source_path)}">${escHtml(job.source_path)}</span></td>
      <td><code style="font-size:12px">${escHtml(job.schedule)}</code></td>
      <td>${statusBadge(job.status)}</td>
      <td>${progressBar(job)}</td>
      <td style="font-size:12px; color:var(--color-text-muted)">${fmtRelative(job.last_run)}</td>
      <td>
        <div class="td-actions">
          ${job.status === "running"
            ? `<button class="icon-btn" onclick="stopJob('${job.id}')" title="Stopp"><i class="ti ti-player-pause"></i></button>`
            : `<button class="icon-btn" onclick="runJob('${job.id}')" title="Kjør nå"><i class="ti ti-player-play"></i></button>`}
          <button class="icon-btn" onclick="editJob('${job.id}')" title="Rediger"><i class="ti ti-edit"></i></button>
          <button class="icon-btn btn-danger-ghost" onclick="confirmDelete('${job.id}', '${escHtml(job.name)}')" title="Slett"><i class="ti ti-trash"></i></button>
        </div>
      </td>
    </tr>
  `).join("");
}

// ---------------------------------------------------------------------------
// Full jobb-tabell (Backup-jobber-siden)
// ---------------------------------------------------------------------------

async function loadFullJobsTable() {
  const res = await apiFetch("/api/jobs");
  if (!res) return;
  const jobs = await res.json();
  const tbody = document.getElementById("jobs-full-tbody");

  if (!jobs.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-state"><i class="ti ti-database-off"></i><span>Ingen jobber</span></td></tr>`;
    return;
  }

  tbody.innerHTML = jobs.map(job => `
    <tr>
      <td><span class="job-name">${escHtml(job.name)}</span></td>
      <td><span class="path-code" title="${escHtml(job.source_path)}">${escHtml(job.source_path)}</span></td>
      <td><span class="path-code" title="${escHtml(job.dest_path)}">${escHtml(job.dest_path || "–")}</span></td>
      <td><code style="font-size:12px">${escHtml(job.schedule)}</code></td>
      <td>${statusBadge(job.status)}</td>
      <td style="font-size:12px; color:var(--color-text-muted)">${fmtDate(job.last_run)}</td>
      <td><span class="badge ${job.enabled ? "badge-success" : "badge-gray"}">${job.enabled ? "Ja" : "Nei"}</span></td>
      <td>
        <div class="td-actions">
          ${job.status === "running"
            ? `<button class="icon-btn" onclick="stopJob('${job.id}')" title="Stopp"><i class="ti ti-player-pause"></i></button>`
            : `<button class="icon-btn" onclick="runJob('${job.id}')" title="Kjør nå"><i class="ti ti-player-play"></i></button>`}
          <button class="icon-btn" onclick="editJob('${job.id}')" title="Rediger"><i class="ti ti-edit"></i></button>
          <button class="icon-btn btn-danger-ghost" onclick="confirmDelete('${job.id}', '${escHtml(job.name)}')" title="Slett"><i class="ti ti-trash"></i></button>
        </div>
      </td>
    </tr>
  `).join("");
}

// ---------------------------------------------------------------------------
// Logger
// ---------------------------------------------------------------------------

async function loadRecentLogs() {
  const res = await apiFetch("/api/logs?limit=5");
  if (!res) return;
  const logs = await res.json();
  const el = document.getElementById("recent-logs-body");
  el.innerHTML = logs.length ? logs.map(renderLogEntry).join("") : `<div class="log-empty">Ingen hendelser</div>`;
}

async function loadLogs() {
  const level = document.getElementById("log-filter").value;
  const url = `/api/logs?limit=200${level ? `&level=${level}` : ""}`;
  const res = await apiFetch(url);
  if (!res) return;
  let logs = await res.json();
  if (level) logs = logs.filter(l => l.level === level);
  const el = document.getElementById("logs-body");
  el.innerHTML = logs.length ? logs.map(renderLogEntry).join("") : `<div class="log-empty">Ingen logger funnet</div>`;
}

function renderLogEntry(entry) {
  const icons = {
    info:    { cls: "log-icon--info",    icon: "ti-info-circle" },
    success: { cls: "log-icon--success", icon: "ti-circle-check" },
    warning: { cls: "log-icon--warning", icon: "ti-alert-triangle" },
    error:   { cls: "log-icon--error",   icon: "ti-circle-x" },
  };
  const s = icons[entry.level] || icons.info;
  const ts = fmtDate(entry.timestamp);
  return `<div class="log-entry">
    <i class="ti ${s.icon} log-icon ${s.cls}"></i>
    <span class="log-time">${ts}</span>
    <span class="log-msg">${escHtml(entry.message)}</span>
  </div>`;
}

document.getElementById("log-filter").addEventListener("change", loadLogs);
document.getElementById("refresh-logs-btn").addEventListener("click", loadLogs);

// ---------------------------------------------------------------------------
// Jobb-handlinger
// ---------------------------------------------------------------------------

async function runJob(jobId) {
  const res = await apiFetch(`/api/jobs/${jobId}/run`, { method: "POST" });
  if (res && res.ok) { loadDashboard(); }
  else if (res) { const d = await res.json(); alert(d.error || "Kunne ikke starte jobb"); }
}

async function stopJob(jobId) {
  await apiFetch(`/api/jobs/${jobId}/stop`, { method: "POST" });
  loadDashboard();
}

// ---------------------------------------------------------------------------
// Modal: Ny / rediger jobb
// ---------------------------------------------------------------------------

function openModal(job = null) {
  document.getElementById("modal-title").textContent = job ? "Rediger jobb" : "Ny backup-jobb";
  document.getElementById("job-id").value = job ? job.id : "";
  document.getElementById("job-name").value = job ? job.name : "";
  document.getElementById("job-source").value = job ? job.source_path : "";
  document.getElementById("job-dest").value = job ? (job.dest_path || "") : "";
  document.getElementById("job-schedule").value = job ? job.schedule : "0 3 * * *";
  document.getElementById("job-enabled").checked = job ? job.enabled : true;
  document.getElementById("job-form-error").classList.add("hidden");
  document.getElementById("job-modal").classList.remove("hidden");
  document.getElementById("job-name").focus();
}

function closeModal() {
  document.getElementById("job-modal").classList.add("hidden");
}

async function editJob(jobId) {
  const res = await apiFetch("/api/jobs");
  if (!res) return;
  const jobs = await res.json();
  const job = jobs.find(j => j.id === jobId);
  if (job) openModal(job);
}

document.getElementById("new-job-btn").addEventListener("click", () => openModal());
document.getElementById("new-job-btn2").addEventListener("click", () => openModal());
document.getElementById("modal-close").addEventListener("click", closeModal);
document.getElementById("modal-cancel").addEventListener("click", closeModal);
document.getElementById("job-modal").addEventListener("click", (e) => {
  if (e.target === document.getElementById("job-modal")) closeModal();
});

document.getElementById("modal-save").addEventListener("click", async () => {
  const jobId = document.getElementById("job-id").value;
  const errEl = document.getElementById("job-form-error");
  errEl.classList.add("hidden");

  const payload = {
    name:        document.getElementById("job-name").value.trim(),
    source_path: document.getElementById("job-source").value.trim(),
    dest_path:   document.getElementById("job-dest").value.trim(),
    schedule:    document.getElementById("job-schedule").value.trim(),
    enabled:     document.getElementById("job-enabled").checked,
  };

  if (!payload.name || !payload.source_path || !payload.schedule) {
    errEl.textContent = "Fyll ut alle obligatoriske felt.";
    errEl.classList.remove("hidden");
    return;
  }

  const url    = jobId ? `/api/jobs/${jobId}` : "/api/jobs";
  const method = jobId ? "PUT" : "POST";
  const res = await apiFetch(url, { method, body: JSON.stringify(payload) });

  if (res && (res.ok || res.status === 201)) {
    closeModal();
    loadDashboard();
    loadFullJobsTable();
  } else if (res) {
    const d = await res.json();
    errEl.textContent = d.error || "Kunne ikke lagre.";
    errEl.classList.remove("hidden");
  }
});

// ---------------------------------------------------------------------------
// Modal: Bekreft sletting
// ---------------------------------------------------------------------------

let _deleteJobId = null;

function confirmDelete(jobId, jobName) {
  _deleteJobId = jobId;
  document.getElementById("confirm-message").textContent =
    `Er du sikker på at du vil slette jobben «${jobName}»?`;
  document.getElementById("confirm-modal").classList.remove("hidden");
}

function closeConfirm() {
  document.getElementById("confirm-modal").classList.add("hidden");
  _deleteJobId = null;
}

document.getElementById("confirm-close").addEventListener("click", closeConfirm);
document.getElementById("confirm-cancel").addEventListener("click", closeConfirm);
document.getElementById("confirm-modal").addEventListener("click", (e) => {
  if (e.target === document.getElementById("confirm-modal")) closeConfirm();
});

document.getElementById("confirm-ok").addEventListener("click", async () => {
  if (!_deleteJobId) return;
  const res = await apiFetch(`/api/jobs/${_deleteJobId}`, { method: "DELETE" });
  if (res && res.ok) {
    closeConfirm();
    loadDashboard();
    loadFullJobsTable();
  }
});

// ---------------------------------------------------------------------------
// Jotta CLI-status
// ---------------------------------------------------------------------------

async function checkJottaStatus() {
  const dotEl  = document.getElementById("jotta-dot");
  const textEl = document.getElementById("jotta-status-text");
  const cliEl  = document.getElementById("jotta-cli-status");

  dotEl.className = "status-dot status-dot--gray status-dot--pulse";
  textEl.textContent = "Sjekker...";

  const res = await apiFetch("/api/jotta/status");
  if (!res) return;
  const d = await res.json();

  if (d.connected) {
    dotEl.className = "status-dot status-dot--green";
    textEl.textContent = "Tilkoblet Jotta";
    if (cliEl) cliEl.innerHTML = `<span class="badge badge-success"><i class="ti ti-check"></i> Tilkoblet</span><pre style="margin-top:8px;font-size:11px;color:var(--color-text-muted);white-space:pre-wrap">${escHtml(d.output)}</pre>`;
  } else {
    dotEl.className = "status-dot status-dot--red";
    textEl.textContent = "Ikke tilkoblet";
    if (cliEl) cliEl.innerHTML = `<span class="badge badge-error"><i class="ti ti-x"></i> Ikke tilkoblet</span><pre style="margin-top:8px;font-size:11px;color:var(--color-danger);white-space:pre-wrap">${escHtml(d.output)}</pre>`;
  }
}

document.getElementById("check-jotta-btn").addEventListener("click", checkJottaStatus);

// ---------------------------------------------------------------------------
// Auto-polling (oppdater hvert 15. sekund)
// ---------------------------------------------------------------------------

let pollingTimer = null;

function startPolling() {
  if (pollingTimer) clearInterval(pollingTimer);
  pollingTimer = setInterval(() => {
    const activePage = document.querySelector(".page.active");
    if (activePage && activePage.id === "page-dashboard") loadDashboard();
    if (activePage && activePage.id === "page-jobs")      loadFullJobsTable();
  }, 15000);
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

(async () => {
  const res = await fetch("/api/auth/status", { credentials: "include" });
  const d = await res.json();
  if (d.authenticated) {
    showApp();
  } else {
    showLogin();
  }
})();
