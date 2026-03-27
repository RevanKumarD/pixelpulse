/**
 * Replay Engine — Scrub through recorded runs event-by-event.
 *
 * Loads events from /api/runs/{id}/events and feeds them through the
 * state machine at timed intervals, recreating the exact dashboard
 * visualization that occurred during the live run.
 */
import {
  addEvent, updateAgent, updateOrchestrator, updateCost,
  getAllAgents, subscribe,
} from "./state.js";

let controls = null;
let slider = null;
let timeDisplay = null;
let playBtn = null;
let markersEl = null;

// Replay state
let events = [];          // All events for the run, sorted by timestamp
let currentIndex = -1;    // Index of last-applied event
let playing = false;
let speed = 1;
let animFrameId = null;
let lastTickTime = 0;
let runMeta = null;       // { id, name, started_at, completed_at }

// Snapshot of agent state before replay (to restore on exit)
let preReplayState = null;

// Callbacks
let onRecordRequest = null;   // () => void — triggers video recording
let onExitCallback = null;    // () => void — called when replay exits

export function init(opts = {}) {
  controls = document.getElementById("replay-controls");
  slider = document.getElementById("replay-slider");
  timeDisplay = document.getElementById("replay-time");
  playBtn = document.getElementById("replay-play");
  markersEl = document.getElementById("replay-markers");
  onRecordRequest = opts.onRecord || null;
  onExitCallback = opts.onExit || null;

  if (!controls) return;

  // Play/Pause
  const play = document.getElementById("replay-play");
  if (play) play.addEventListener("click", togglePlay);

  // Step buttons
  const stepBack = document.getElementById("replay-step-back");
  const stepFwd = document.getElementById("replay-step-fwd");
  if (stepBack) stepBack.addEventListener("click", stepBackward);
  if (stepFwd) stepFwd.addEventListener("click", stepForward);

  // Slider scrub
  if (slider) {
    slider.addEventListener("input", () => {
      const idx = parseInt(slider.value, 10);
      seekTo(idx);
    });
  }

  // Speed buttons
  controls.querySelectorAll(".replay-speed-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      speed = parseFloat(btn.dataset.speed) || 1;
      controls.querySelectorAll(".replay-speed-btn").forEach(b =>
        b.classList.toggle("replay-speed-btn--active", b === btn)
      );
    });
  });

  // Record button
  const recordBtn = document.getElementById("replay-record");
  if (recordBtn) {
    recordBtn.addEventListener("click", () => {
      if (onRecordRequest) onRecordRequest();
    });
  }

  // Exit
  const exitBtn = document.getElementById("replay-exit");
  if (exitBtn) exitBtn.addEventListener("click", exitReplay);
}

/**
 * Start replay of a specific run.
 */
export async function startReplay(runId) {
  // Save current state
  preReplayState = _snapshotAgents();

  // Reset all agents to idle
  const agents = getAllAgents();
  for (const name of Object.keys(agents)) {
    updateAgent(name, { status: "idle", task: "", cost: 0 });
  }
  updateOrchestrator({ status: "idle", currentStage: "", message: "" });

  // Fetch run data and events
  try {
    const [runResp, eventsResp] = await Promise.all([
      fetch(`/api/runs/${encodeURIComponent(runId)}`),
      fetch(`/api/runs/${encodeURIComponent(runId)}/events?limit=10000`),
    ]);

    if (!runResp.ok || !eventsResp.ok) {
      console.error("[Replay] Failed to load run data");
      return;
    }

    runMeta = await runResp.json();
    const eventsData = await eventsResp.json();
    events = (eventsData.events || []).sort((a, b) =>
      (a.timestamp || "").localeCompare(b.timestamp || "")
    );
  } catch (err) {
    console.error("[Replay] Load error:", err);
    return;
  }

  if (!events.length) {
    console.warn("[Replay] No events to replay");
    return;
  }

  // Setup UI
  currentIndex = -1;
  playing = false;
  speed = 1;

  if (slider) {
    slider.max = events.length - 1;
    slider.value = 0;
  }

  _updateTimeDisplay();
  _buildMarkers();

  // Show controls
  if (controls) controls.hidden = false;
  if (playBtn) playBtn.innerHTML = "&#x25B6;";

  // Reset speed buttons
  if (controls) {
    controls.querySelectorAll(".replay-speed-btn").forEach(b =>
      b.classList.toggle("replay-speed-btn--active", b.dataset.speed === "1")
    );
  }

  console.log(`[Replay] Loaded ${events.length} events for run "${runMeta.name || runId}"`);
}

export function togglePlay() {
  if (!events.length) return;
  playing = !playing;
  if (playBtn) playBtn.innerHTML = playing ? "&#x23F8;" : "&#x25B6;";

  if (playing) {
    lastTickTime = performance.now();
    _tick();
  } else {
    if (animFrameId) cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }
}

export function stepForward() {
  if (currentIndex < events.length - 1) {
    _applyEvent(currentIndex + 1);
    currentIndex++;
    _syncSlider();
  }
}

export function stepBackward() {
  if (currentIndex <= 0) return;
  // Replay from start up to (currentIndex - 1)
  const target = currentIndex - 1;
  _replayFromStart(target);
}

export function seekTo(index) {
  const idx = Math.max(-1, Math.min(index, events.length - 1));
  if (idx < currentIndex) {
    _replayFromStart(idx);
  } else {
    // Fast-forward
    while (currentIndex < idx) {
      currentIndex++;
      _applyEvent(currentIndex);
    }
  }
  _syncSlider();
}

export function exitReplay() {
  playing = false;
  if (animFrameId) cancelAnimationFrame(animFrameId);
  animFrameId = null;

  // Hide controls
  if (controls) controls.hidden = true;

  // Restore pre-replay state
  if (preReplayState) {
    for (const [name, agentState] of Object.entries(preReplayState)) {
      updateAgent(name, agentState);
    }
    preReplayState = null;
  }

  events = [];
  currentIndex = -1;
  runMeta = null;

  if (onExitCallback) onExitCallback();
}

export function isActive() {
  return events.length > 0;
}

export function getRunMeta() {
  return runMeta;
}

// ---- Internal ----

function _tick() {
  if (!playing || currentIndex >= events.length - 1) {
    playing = false;
    if (playBtn) playBtn.innerHTML = "&#x25B6;";
    return;
  }

  const now = performance.now();
  const elapsed = now - lastTickTime;

  // Calculate time gap between current event and next
  const nextIdx = currentIndex + 1;
  const current = currentIndex >= 0 ? events[currentIndex] : null;
  const next = events[nextIdx];

  let gap = 500; // default 500ms between events
  if (current && next && current.timestamp && next.timestamp) {
    gap = new Date(next.timestamp) - new Date(current.timestamp);
    gap = Math.max(50, Math.min(gap, 5000)); // Clamp to [50ms, 5s]
  }

  // Apply speed multiplier
  const adjustedGap = gap / speed;

  if (elapsed >= adjustedGap) {
    currentIndex++;
    _applyEvent(currentIndex);
    _syncSlider();
    lastTickTime = now;
  }

  animFrameId = requestAnimationFrame(_tick);
}

function _applyEvent(index) {
  if (index < 0 || index >= events.length) return;

  const evt = events[index];
  const p = evt.payload || {};

  // Feed through the standard state machine
  addEvent({ type: evt.type, timestamp: evt.timestamp, payload: p });

  // Also apply direct agent updates
  if (evt.type === "agent_status" && p.agent_id) {
    updateAgent(p.agent_id, {
      status: p.status || "idle",
      task: p.thinking || p.task || "",
    });
  }

  if (evt.type === "cost_update" && p.agent_id) {
    updateCost(p.agent_id, p.cost || 0);
  }

  _updateTimeDisplay();
}

function _replayFromStart(targetIndex) {
  // Reset agents
  const agents = getAllAgents();
  for (const name of Object.keys(agents)) {
    updateAgent(name, { status: "idle", task: "", cost: 0 });
  }
  updateOrchestrator({ status: "idle", currentStage: "", message: "" });

  // Replay silently from 0 to targetIndex
  currentIndex = -1;
  for (let i = 0; i <= targetIndex; i++) {
    const evt = events[i];
    const p = evt.payload || {};

    // Apply state changes without triggering full addEvent (avoid flooding UI)
    if (evt.type === "agent_status" && p.agent_id) {
      updateAgent(p.agent_id, {
        status: p.status || "idle",
        task: p.thinking || p.task || "",
      });
    }
    if (evt.type === "cost_update" && p.agent_id) {
      updateCost(p.agent_id, p.cost || 0);
    }
    if (evt.type === "pipeline_progress") {
      updateOrchestrator({
        status: p.status === "waiting" ? "waiting" : "active",
        currentStage: p.stage || "",
        message: p.message || "",
      });
    }
  }

  currentIndex = targetIndex;
  _syncSlider();
  _updateTimeDisplay();
}

function _syncSlider() {
  if (slider) slider.value = Math.max(0, currentIndex);
}

function _updateTimeDisplay() {
  if (!timeDisplay) return;

  if (!events.length) {
    timeDisplay.textContent = "0:00 / 0:00";
    return;
  }

  const firstTime = events[0]?.timestamp ? new Date(events[0].timestamp) : null;
  const lastTime = events[events.length - 1]?.timestamp
    ? new Date(events[events.length - 1].timestamp) : null;
  const currentTime = currentIndex >= 0 && events[currentIndex]?.timestamp
    ? new Date(events[currentIndex].timestamp) : firstTime;

  if (!firstTime || !lastTime || !currentTime) {
    timeDisplay.textContent = `${currentIndex + 1} / ${events.length}`;
    return;
  }

  const elapsed = Math.max(0, currentTime - firstTime);
  const total = Math.max(0, lastTime - firstTime);

  timeDisplay.textContent = `${_fmtMs(elapsed)} / ${_fmtMs(total)}`;
}

function _buildMarkers() {
  if (!markersEl || !events.length) return;
  markersEl.innerHTML = "";

  // Place markers at pipeline_progress events (stage transitions)
  events.forEach((evt, i) => {
    if (evt.type === "pipeline_progress") {
      const pct = (i / (events.length - 1)) * 100;
      const marker = document.createElement("div");
      marker.className = "replay-marker";
      marker.style.left = `${pct}%`;
      marker.title = evt.payload?.stage || "stage";
      markersEl.appendChild(marker);
    }
  });
}

function _snapshotAgents() {
  const agents = getAllAgents();
  const snap = {};
  for (const [name, agent] of Object.entries(agents)) {
    snap[name] = { ...agent };
  }
  return snap;
}

function _fmtMs(ms) {
  const totalSec = Math.floor(ms / 1000);
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min}:${sec.toString().padStart(2, "0")}`;
}
