// Volume Stabilizer Web UI Frontend Logic
let currentPath = "";
let currentAnalyzeJobId = null;
let currentTracks = [];
let ws = null;

// DOM Elements
const currentDirDisplay = document.getElementById("current-dir-display");
const folderList = document.getElementById("folder-list");
const folderAudioCount = document.getElementById("folder-audio-count");
const btnRefreshTree = document.getElementById("btn-refresh-tree");
const btnAnalyze = document.getElementById("btn-analyze");
const btnConvert = document.getElementById("btn-convert");
const btnExportCsv = document.getElementById("btn-export-csv");
const checkForceMode = document.getElementById("check-force-mode");
const selectAllCheckbox = document.getElementById("select-all-checkbox");
const headerSelectAll = document.getElementById("header-select-all");
const tracksTableBody = document.getElementById("tracks-table-body");
const tableTrackCount = document.getElementById("table-track-count");
const progressContainer = document.getElementById("progress-container");
const progressTrackName = document.getElementById("progress-track-name");
const progressPercentage = document.getElementById("progress-percentage");
const progressBarFill = document.getElementById("progress-bar-fill");
const jobStatusTag = document.getElementById("job-status-tag");
const step1Badge = document.getElementById("step-1-badge");
const step2Badge = document.getElementById("step-2-badge");
const progressCount = document.getElementById("progress-count");
const progressTimer = document.getElementById("progress-timer");
const progressHeartbeatWarning = document.getElementById("progress-heartbeat-warning");
const progressErrorCount = document.getElementById("progress-error-count");
const btnProgressClose = document.getElementById("btn-progress-close");
const errorPanel = document.getElementById("error-panel");
const errorPanelSummary = document.getElementById("error-panel-summary");
const errorList = document.getElementById("error-list");
let progressHideTimer = null;
let jobStartTime = null;
let timerInterval = null;
let lastWsMessageTime = null;
let heartbeatInterval = null;

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  initWebSocket();
  loadSystemStatus();
  loadDirectoryTree("");

  btnRefreshTree.addEventListener("click", () => loadDirectoryTree(currentPath));
  btnAnalyze.addEventListener("click", handleAnalyze);
  btnConvert.addEventListener("click", handleConvert);
  btnExportCsv.addEventListener("click", () => {
    window.location.href = "/api/v1/reports/export";
  });

  btnProgressClose.addEventListener("click", hideProgress);
  headerSelectAll.addEventListener("change", (e) => toggleSelectAll(e.target.checked));
  selectAllCheckbox.addEventListener("change", (e) => toggleSelectAll(e.target.checked));
});

// Load System Status
async function loadSystemStatus() {
  try {
    const res = await fetch("/api/v1/system/status");
    const data = await res.json();
    document.getElementById("stat-target").textContent = `${data.target_lufs.toFixed(1)} LUFS`;
    document.getElementById("stat-ceiling").textContent = `${data.peak_ceiling_dbtp.toFixed(1)} dBTP`;
    document.getElementById("stat-workers").textContent = data.workers;
    document.getElementById("stat-stabilized").textContent = `${data.stabilized_tracks} tracks`;
  } catch (err) {
    console.error("Failed to load status:", err);
  }
}

// Directory Browser
async function loadDirectoryTree(subpath) {
  currentPath = subpath;
  currentDirDisplay.textContent = `/${subpath}`;
  folderList.innerHTML = '<div class="loader-spinner">Loading folders...</div>';

  try {
    const res = await fetch(`/api/v1/fs/tree?path=${encodeURIComponent(subpath)}`);
    if (!res.ok) throw new Error("Directory load failed");
    const data = await res.json();

    folderAudioCount.textContent = `${data.audio_count} audio files in current folder`;
    folderList.innerHTML = "";

    // Up directory if not at root
    if (subpath !== "") {
      const upDiv = document.createElement("div");
      upDiv.className = "folder-item";
      upDiv.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 18l-6-6 6-6"/></svg>
        <span>.. [Parent Directory]</span>
      `;
      upDiv.addEventListener("click", () => {
        const parts = subpath.split("/").filter(Boolean);
        parts.pop();
        loadDirectoryTree(parts.join("/"));
      });
      folderList.appendChild(upDiv);
    }

    if (data.subdirs.length === 0 && subpath === "") {
      folderList.innerHTML = '<div style="padding:1rem;color:var(--text-dim);font-size:0.8rem;">No subdirectories found in /music</div>';
      return;
    }

    data.subdirs.forEach(dir => {
      const item = document.createElement("div");
      item.className = "folder-item";
      item.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>
        <span>${dir}</span>
      `;
      item.addEventListener("click", () => {
        const next = subpath ? `${subpath}/${dir}` : dir;
        loadDirectoryTree(next);
      });
      folderList.appendChild(item);
    });

    // Auto-sync tracks for the navigated directory
    loadTracksForCurrentPath();

  } catch (err) {
    folderList.innerHTML = `<div style="padding:1rem;color:var(--accent-red);font-size:0.8rem;">Error: ${err.message}</div>`;
  }
}

// WebSocket connection for real-time progress
function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${window.location.host}/ws/progress`);

  ws.onopen = () => console.log("WebSocket connected");
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleWsEvent(msg);
    } catch (e) {
      console.error("WS Parse error", e);
    }
  };
  ws.onclose = () => {
    console.log("WebSocket closed, retrying in 3s...");
    setTimeout(initWebSocket, 3000);
  };
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}


function formatDuration(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function startJobTimer() {
  stopJobTimer();
  jobStartTime = Date.now();
  lastWsMessageTime = Date.now();
  if (progressTimer) progressTimer.textContent = "00:00";
  if (progressHeartbeatWarning) progressHeartbeatWarning.hidden = true;

  timerInterval = setInterval(() => {
    if (!jobStartTime) return;
    const elapsedSec = (Date.now() - jobStartTime) / 1000;
    if (progressTimer) progressTimer.textContent = formatDuration(elapsedSec);
  }, 1000);

  heartbeatInterval = setInterval(() => {
    if (!lastWsMessageTime || !progressHeartbeatWarning) return;
    const quietSec = (Date.now() - lastWsMessageTime) / 1000;
    if (quietSec >= 10) {
      progressHeartbeatWarning.hidden = false;
      progressHeartbeatWarning.textContent = `⚠ I/O wait (${Math.floor(quietSec)}s ago)`;
    } else {
      progressHeartbeatWarning.hidden = true;
    }
  }, 1000);
}

function stopJobTimer() {
  if (timerInterval) clearInterval(timerInterval);
  if (heartbeatInterval) clearInterval(heartbeatInterval);
  timerInterval = null;
  heartbeatInterval = null;
  if (progressHeartbeatWarning) progressHeartbeatWarning.hidden = true;
}

function recordWsActivity() {
  lastWsMessageTime = Date.now();
  if (progressHeartbeatWarning) progressHeartbeatWarning.hidden = true;
}

function hideProgress() {
  stopJobTimer();
  if (progressHideTimer) clearTimeout(progressHideTimer);
  progressHideTimer = null;
  progressContainer.style.display = "none";
}

function resetProgress(type, total) {
  if (progressHideTimer) clearTimeout(progressHideTimer);
  progressHideTimer = null;
  progressContainer.style.display = "block";
  progressContainer.classList.remove("has-errors");
  progressBarFill.classList.remove("indeterminate");
  jobStatusTag.textContent = type;
  progressPercentage.textContent = "0%";
  progressBarFill.style.width = "0%";
  progressTrackName.textContent = "Starting...";
  progressCount.textContent = `0 / ${total ?? 0}`;
  progressErrorCount.hidden = true;
  progressErrorCount.textContent = "0 errors";
  btnProgressClose.hidden = true;
  errorPanel.hidden = true;
  errorPanel.open = false;
  errorList.innerHTML = "";
  startJobTimer();
}

function setErrorCount(n) {
  if (!n) return;
  progressErrorCount.hidden = false;
  progressErrorCount.textContent = `${n} error${n === 1 ? "" : "s"}`;
  progressContainer.classList.add("has-errors");
}

function appendError(err) {
  if (!err) return;
  errorPanel.hidden = false;
  const li = document.createElement("li");
  li.innerHTML = `
    <span class="err-track" title="${escapeHtml(err.track)}">&lrm;${escapeHtml(err.track)}&lrm;</span>
    <span class="err-msg">${escapeHtml(err.message)}</span>
  `;
  errorList.appendChild(li);
  errorPanelSummary.textContent = `Failed tracks (${errorList.children.length})`;
}

function handleWsEvent(msg) {
  recordWsActivity();

  if (msg.event === "JOB_SCANNING") {
    const d = msg.data;
    if (!timerInterval) startJobTimer();
    progressContainer.style.display = "block";
    jobStatusTag.textContent = "SCANNING";
    progressBarFill.classList.add("indeterminate");
    progressPercentage.textContent = d.folders_scanned ? `${d.folders_scanned} dirs` : "";
    progressTrackName.textContent = `Scanning: ${d.folders_scanned} folders, ${d.audio_found} audio files found...`;
    progressCount.textContent = `${d.audio_found} tracks`;
  } else if (msg.event === "JOB_STARTED") {
    progressBarFill.classList.remove("indeterminate");
    resetProgress(msg.data.type, msg.data.total);
    progressTrackName.textContent = msg.data.total ? `Analyzing ${msg.data.total} tracks...` : "Preparing analysis...";
  } else if (msg.event === "JOB_PROGRESS") {
    const d = msg.data;
    progressBarFill.classList.remove("indeterminate");
    progressPercentage.textContent = `${d.percent}%`;
    progressBarFill.style.width = `${d.percent}%`;

    // Smart path display: shorten if within currentPath (Proposal 2-C)
    let trackDisplay = d.track || "Processing...";
    if (currentPath && trackDisplay.startsWith(currentPath)) {
      trackDisplay = trackDisplay.substring(currentPath.length).replace(/^\/+/, "");
    }
    progressTrackName.textContent = trackDisplay;
    progressTrackName.title = d.track || "";

    progressCount.textContent = `${d.processed} / ${d.total}`;
    setErrorCount(d.errors);
    if (d.status === "error") appendError(d.error);
  } else if (msg.event === "JOB_COMPLETED") {
    stopJobTimer();
    progressBarFill.classList.remove("indeterminate");
    const d = msg.data;
    const errors = d.errors || 0;
    progressPercentage.textContent = "100%";
    progressBarFill.style.width = "100%";
    loadSystemStatus();

    // Rebuild the error list from the authoritative final report
    if (Array.isArray(d.error_list) && d.error_list.length) {
      errorList.innerHTML = "";
      d.error_list.forEach(appendError);
      if (errors > d.error_list.length) {
        errorPanelSummary.textContent =
          `Failed tracks (showing ${d.error_list.length} of ${errors}, see server log for the rest)`;
      }
    }

    const targetJobId = d.job_id || currentAnalyzeJobId;
    if (d.type === "ANALYZE") {
      const ok = d.succeeded ?? (d.total - errors);
      progressTrackName.textContent = errors
        ? `Completed with errors: ${ok} analyzed, ${errors} failed`
        : `Completed: ${ok} tracks analyzed`;
      if (targetJobId) fetchJobTracks(targetJobId);
      loadTracksForCurrentPath();
      step1Badge.classList.remove("active");
      step2Badge.classList.add("active");
      btnConvert.disabled = false;
    } else if (d.type === "CONVERT") {
      const parts = [];
      if (d.converted) parts.push(`${d.converted} converted`);
      if (d.bypassed) parts.push(`${d.bypassed} bypassed`);
      if (d.skipped) parts.push(`${d.skipped} skipped`);
      if (errors) parts.push(`${errors} failed`);

      if (d.converted === 0 && d.bypassed === 0 && d.skipped > 0 && errors === 0) {
        progressTrackName.textContent = `All ${d.skipped} tracks already stabilized (skipped). Enable "Force Reprocess" to re-encode.`;
      } else {
        progressTrackName.textContent =
          `${errors ? "Completed with errors" : "Completed"}: ${parts.join(", ") || "No tracks processed"}`;
      }
      if (targetJobId) fetchJobTracks(targetJobId);
      loadTracksForCurrentPath();
    }

    btnAnalyze.disabled = false;
    btnConvert.disabled = false;

    if (errors) {
      // Keep the card visible so failures are not missed
      setErrorCount(errors);
      jobStatusTag.textContent = `${d.type} ⚠`;
      btnProgressClose.hidden = false;
      errorPanel.open = true;
    } else {
      progressHideTimer = setTimeout(hideProgress, 4000);
    }
  }
}


// Load existing tracks for the current selected folder from DB
async function loadTracksForCurrentPath() {
  try {
    const res = await fetch(`/api/v1/tracks?path=${encodeURIComponent(currentPath)}`);
    if (!res.ok) return;
    const data = await res.json();
    currentTracks = data.tracks || [];
    renderTable(currentTracks);

    if (currentTracks.length > 0) {
      step1Badge.classList.remove("active");
      step2Badge.classList.add("active");
      btnConvert.disabled = false;
    } else {
      step1Badge.classList.add("active");
      step2Badge.classList.remove("active");
      btnConvert.disabled = true;
    }
  } catch (err) {
    console.error("Failed to load tracks for path:", err);
  }
}

// Stage 1: Analyze
async function handleAnalyze() {
  const force = checkForceMode.checked;
  if (progressHideTimer) {
    clearTimeout(progressHideTimer);
    progressHideTimer = null;
  }
  btnAnalyze.disabled = true;
  btnConvert.disabled = true;

  // Immediate visual feedback (Proposal 1-C)
  resetProgress("PREPARING", 0);
  progressTrackName.textContent = "Connecting & initiating directory scan...";
  progressBarFill.classList.add("indeterminate");

  try {
    const res = await fetch("/api/v1/jobs/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subpath: currentPath, force: force })
    });
    const data = await res.json();
    currentAnalyzeJobId = data.job_id;
  } catch (err) {
    alert(`Analyze failed: ${err.message}`);
    btnAnalyze.disabled = false;
    btnConvert.disabled = false;
    hideProgress();
  }
}

// Fetch tracks for table preview
async function fetchJobTracks(jobId) {
  if (!jobId) return;
  try {
    const res = await fetch(`/api/v1/jobs/${jobId}/tracks`);
    const data = await res.json();
    currentTracks = data.tracks || [];
    renderTable(currentTracks);
  } catch (err) {
    console.error("Failed to fetch tracks:", err);
  }
}

// Render Tracks Table
function renderTable(tracks) {
  const stabilizedCount = tracks.filter(t => t.status === "converted" || t.status === "bypassed").length;
  const readyCount = tracks.length - stabilizedCount;

  if (tracks.length > 0) {
    tableTrackCount.innerHTML = `${tracks.length} tracks <span style="font-size:0.75rem;color:var(--text-muted);font-weight:400;">(${readyCount} ready, <strong style="color:var(--accent-green);">${stabilizedCount} stabilized</strong>)</span>`;
  } else {
    tableTrackCount.textContent = "0 tracks";
  }

  tracksTableBody.innerHTML = "";

  if (tracks.length === 0) {
    tracksTableBody.innerHTML = `
      <tr class="empty-row">
        <td colspan="9">No tracks analyzed in this folder yet. Click <strong>Analyze Folder</strong> to preview loudness.</td>
      </tr>
    `;
    return;
  }

  tracks.forEach((t) => {
    const tr = document.createElement("tr");

    const isStabilized = t.status === "converted";
    const isBypassed = t.status === "bypassed";
    const isProcessed = isStabilized || isBypassed;

    if (isProcessed) {
      tr.className = "row-stabilized";
    } else if (t.status === "error") {
      tr.className = "row-error";
    }

    // Formats
    const lufs = t.integrated_lufs != null ? `${t.integrated_lufs.toFixed(1)} LUFS` : "-";
    const tp = t.true_peak_dbtp != null ? `${t.true_peak_dbtp.toFixed(1)} dBTP` : "-";
    const gain = t.target_gain_db != null ? `${t.target_gain_db >= 0 ? '+' : ''}${t.target_gain_db.toFixed(1)} dB` : "-";

    // Limiter badge
    let limiterBadge = '<span class="badge-limiter-no">No</span>';
    if (t.limiter_required) {
      limiterBadge = `<span class="badge-pill badge-limiter-yes">Yes (-${(t.limiter_reduction_db || 0).toFixed(1)}dB)</span>`;
    }

    // Status badge: clear distinction
    let statusBadge = '<span class="badge-pill badge-ready">Ready</span>';
    if (t.status === "error") {
      statusBadge = '<span class="badge-pill badge-error" title="Last conversion failed (see progress panel / server log)">✕ Error</span>';
    } else if (isStabilized) {
      statusBadge = '<span class="badge-pill badge-converted" title="Stabilization completed">✓ Stabilized</span>';
    } else if (isBypassed) {
      statusBadge = '<span class="badge-pill badge-bypass" title="Bypassed (bit-perfect stream copy)">⚡ Bypassed</span>';
    } else if (t.bypass_eligible) {
      statusBadge = '<span class="badge-pill badge-bypass" title="Eligible for bit-perfect bypass">Bypass Eligible</span>';
    } else if (t.warning_code === "LOUDNESS_UNDER_TARGET") {
      statusBadge = '<span class="badge-pill badge-warning" title="Limiter reduction capped at 3dB">Cap 3dB</span>';
    }

    // Split path into primary filename and subfolder relative to current view (Proposal 2-B, 2-C)
    const fullPath = t.relative_path || "";
    let filename = fullPath;
    let subfolder = "";
    const lastSlashIdx = fullPath.lastIndexOf("/");
    if (lastSlashIdx !== -1) {
      filename = fullPath.substring(lastSlashIdx + 1);
      subfolder = fullPath.substring(0, lastSlashIdx);
      // Shorten subfolder if it starts with current selected path
      if (currentPath && subfolder.startsWith(currentPath)) {
        subfolder = subfolder.substring(currentPath.length).replace(/^\/+/, "");
      }
    }

    tr.innerHTML = `
      <td><input type="checkbox" class="track-select" data-id="${t.id}" ${isProcessed ? "" : "checked"}></td>
      <td>
        <div class="track-path-cell" title="${escapeHtml(fullPath)}">
          <span class="track-filename">${escapeHtml(filename)}</span>
          ${subfolder ? `<span class="track-subfolder">${escapeHtml(subfolder)}</span>` : ""}
        </div>
      </td>
      <td><span class="badge-pill">${t.input_format.toUpperCase()} &rarr; ${t.output_format.toUpperCase()}</span></td>
      <td class="num">${lufs}</td>
      <td class="num">${tp}</td>
      <td class="num" style="color:var(--accent-cyan);font-weight:600;">${gain}</td>
      <td class="center">${limiterBadge}</td>
      <td>${statusBadge}</td>
      <td class="center">
        <button class="btn-mini btn-reprocess" data-id="${t.id}" title="Reprocess track">Re</button>
      </td>
    `;
    tracksTableBody.appendChild(tr);
  });

  // Sync header select-all with whether any/all tracks are checked
  const allBoxes = document.querySelectorAll(".track-select");
  const checkedBoxes = document.querySelectorAll(".track-select:checked");
  const allChecked = allBoxes.length > 0 && allBoxes.length === checkedBoxes.length;
  if (headerSelectAll) headerSelectAll.checked = allChecked;
  if (selectAllCheckbox) selectAllCheckbox.checked = allChecked;

  // Attach per-track reprocess listener
  document.querySelectorAll(".btn-reprocess").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      const trackId = e.target.getAttribute("data-id");
      try {
        await fetch(`/api/v1/tracks/${trackId}/reprocess`, { method: "POST" });
      } catch (err) {
        alert("Reprocess request failed");
      }
    });
  });
}

function toggleSelectAll(checked) {
  document.querySelectorAll(".track-select").forEach(cb => {
    cb.checked = checked;
  });
  headerSelectAll.checked = checked;
  selectAllCheckbox.checked = checked;
}

// Stage 2: Convert
async function handleConvert() {
  let selectedCheckboxes = document.querySelectorAll(".track-select:checked");
  let trackIds = Array.from(selectedCheckboxes).map(cb => cb.getAttribute("data-id"));

  // If no track is checked, auto-select ready (unprocessed) tracks
  if (trackIds.length === 0) {
    const readyBoxes = document.querySelectorAll("tr:not(.row-stabilized) .track-select");
    if (readyBoxes.length > 0) {
      readyBoxes.forEach(cb => { cb.checked = true; });
      selectedCheckboxes = document.querySelectorAll(".track-select:checked");
      trackIds = Array.from(selectedCheckboxes).map(cb => cb.getAttribute("data-id"));
    }
  }

  if (trackIds.length === 0) {
    alert("All tracks in this folder are already stabilized.\nTo reprocess them, check 'Select All' or enable 'Force Reprocess'.");
    return;
  }

  const force = checkForceMode.checked;

  if (progressHideTimer) {
    clearTimeout(progressHideTimer);
    progressHideTimer = null;
  }
  btnConvert.disabled = true;
  btnAnalyze.disabled = true;

  // Immediate visual feedback for convert job
  resetProgress("CONVERT", trackIds.length);
  progressTrackName.textContent = `Preparing stabilization for ${trackIds.length} tracks...`;
  progressBarFill.style.width = "0%";

  try {
    const res = await fetch("/api/v1/jobs/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        track_ids: trackIds,
        force: force
      })
    });
    if (!res.ok) throw new Error("Conversion failed to start");
  } catch (err) {
    alert(`Convert failed: ${err.message}`);
    btnConvert.disabled = false;
    btnAnalyze.disabled = false;
    hideProgress();
  }
}
