const uploadForm = document.getElementById("upload-form");
const submitBtn = document.getElementById("submit-btn");
const formError = document.getElementById("form-error");
const resultsCard = document.getElementById("results-card");
const tabsEl = document.getElementById("tournament-tabs");
const resultsTitle = document.getElementById("results-title");
const resultsBody = document.getElementById("results-body");
const copyTsvBtn = document.getElementById("copy-tsv-btn");
const downloadCsvLink = document.getElementById("download-csv-link");
const copyFeedback = document.getElementById("copy-feedback");
const runStatus = document.getElementById("run-status");
const progressFill = document.getElementById("progress-fill");
const progressLabel = document.getElementById("progress-label");

let tournaments = new Map(); // id -> summary
let activeTournamentId = null;
let activeSocket = null;

const TERMINAL_STATUSES = new Set(["done", "error", "skipped_cached"]);

function statusLabel(status) {
  return status.replace(/_/g, " ");
}

function resetRunStatus() {
  runStatus.hidden = false;
  for (const row of runStatus.querySelectorAll(".stage-row")) {
    row.dataset.status = "";
    row.removeAttribute("title");
  }
  progressFill.style.width = "0%";
  progressLabel.textContent = "";
}

function setStage(stageName, status, detail) {
  const row = runStatus.querySelector(`.stage-row[data-stage="${stageName}"]`);
  if (!row) return;
  row.dataset.status = status;
  if (detail) row.title = detail;
  else row.removeAttribute("title");
}

function recomputeProgress() {
  const rows = resultsBody.querySelectorAll("tr");
  const total = rows.length;
  let finished = 0;
  for (const row of rows) {
    const badge = row.querySelector(".badge");
    if (badge && TERMINAL_STATUSES.has(badge.dataset.status)) finished += 1;
  }
  const pct = total ? Math.round((finished / total) * 100) : 0;
  progressFill.style.width = `${pct}%`;
  progressLabel.textContent = total ? `${finished} / ${total} scouted` : "";
}

function renderTabs() {
  tabsEl.innerHTML = "";
  for (const t of tournaments.values()) {
    const btn = document.createElement("button");
    btn.textContent = t.name;
    btn.className = t.id === activeTournamentId ? "active" : "";
    btn.addEventListener("click", () => selectTournament(t.id));
    tabsEl.appendChild(btn);
  }
}

function renderTable(summary) {
  resultsTitle.textContent = `${summary.name} — ${summary.section}`;
  downloadCsvLink.href = `/api/tournaments/${summary.id}/export.csv`;
  resultsBody.innerHTML = "";

  for (const team of summary.teams) {
    const row = document.createElement("tr");

    const opponent = team.opponent_school
      ? `${team.opponent_school} ${team.opponent_team_code || ""}`.trim()
      : "—";

    const confidenceBits = [];
    if (team.aff_type_confidence != null) confidenceBits.push(`${Math.round(team.aff_type_confidence * 100)}%`);
    const affCell = team.aff_type
      ? `${team.aff_type}${confidenceBits.length ? ` <small>(${confidenceBits[0]})</small>` : ""}`
      : "—";

    const countryConfidence = team.country_confidence != null ? ` <small>(${Math.round(team.country_confidence * 100)}%)</small>` : "";
    const countryCell = team.country ? `${team.country}${countryConfidence}` : "—";

    const sourceCell = team.source_url
      ? `<a class="source-link" href="${team.source_url}" target="_blank" rel="noopener">${team.source_title || "view"}</a>`
      : "—";

    const statusTitle = team.error_message ? ` title="${team.error_message.replace(/"/g, "&quot;")}"` : "";

    row.innerHTML = `
      <td>${team.school_name}</td>
      <td>${team.team_code}</td>
      <td>${team.debaters || "—"}</td>
      <td>${opponent}</td>
      <td>${team.round_label || "—"}</td>
      <td><span class="badge status-${team.status}" data-status="${team.status}"${statusTitle}>${statusLabel(team.status)}</span></td>
      <td>${affCell}</td>
      <td>${countryCell}</td>
      <td>${sourceCell}</td>
    `;
    row.dataset.teamId = team.team_id;
    resultsBody.appendChild(row);
  }
  recomputeProgress();
}

function updateRowStatus(event) {
  const row = resultsBody.querySelector(`tr[data-team-id="${event.team_id}"]`);
  if (!row) return;
  const badge = row.querySelector(".badge");
  badge.className = `badge status-${event.status}`;
  badge.dataset.status = event.status;
  badge.textContent = statusLabel(event.status);
  if (event.detail) badge.title = event.detail;
  recomputeProgress();
}

function connectSocket(tournamentId) {
  if (activeSocket) {
    activeSocket.close();
  }
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/${tournamentId}`);
  socket.onmessage = (msg) => {
    const payload = JSON.parse(msg.data);
    if (payload.type === "snapshot") {
      tournaments.set(payload.data.id, payload.data);
      if (payload.data.id === activeTournamentId) {
        renderTable(payload.data);
        // Reconnecting to a tournament with teams already past "queued"
        // means a run already got through these checks -- reflect that
        // instead of showing a fresh "pending" connectivity indicator for
        // one that isn't actually running right now.
        const startedStatuses = new Set(["scraping", "parsing", "classifying", "done", "error"]);
        const started = payload.data.teams.some((t) => startedStatuses.has(t.status));
        if (started) {
          setStage("jev_check", "success");
          setStage("opencaselist_login", "success");
        }
      }
    } else if (payload.type === "stage" && payload.tournament_id === activeTournamentId) {
      setStage(payload.stage, payload.status, payload.detail);
    } else if (payload.type === "team" && payload.tournament_id === activeTournamentId) {
      updateRowStatus(payload);
    }
  };
  activeSocket = socket;
}

function selectTournament(id) {
  activeTournamentId = id;
  resultsCard.hidden = false;
  resetRunStatus();
  renderTabs();
  connectSocket(id);
}

async function refreshTournamentList() {
  const res = await fetch("/api/tournaments");
  const list = await res.json();
  for (const t of list) tournaments.set(t.id, t);
  renderTabs();
}

copyTsvBtn.addEventListener("click", async () => {
  if (!activeTournamentId) return;
  const res = await fetch(`/api/tournaments/${activeTournamentId}/export.tsv`);
  const text = await res.text();
  try {
    await navigator.clipboard.writeText(text);
    copyFeedback.textContent = "Copied! Paste straight into Google Sheets or Excel.";
  } catch {
    copyFeedback.textContent = "Couldn't access the clipboard — use Download CSV instead.";
  }
  setTimeout(() => (copyFeedback.textContent = ""), 4000);
});

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  formError.textContent = "";
  submitBtn.disabled = true;
  submitBtn.textContent = "Starting…";

  try {
    const formData = new FormData(uploadForm);
    const res = await fetch("/api/tournaments/upload", { method: "POST", body: formData });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Upload failed (${res.status})`);
    }
    const { tournament_id } = await res.json();
    await refreshTournamentList();
    selectTournament(tournament_id);
    uploadForm.reset();
  } catch (err) {
    formError.textContent = err.message;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Start scouting";
  }
});

refreshTournamentList().then(() => {
  if (tournaments.size > 0 && activeTournamentId === null) {
    const first = tournaments.values().next().value;
    selectTournament(first.id);
  }
});
