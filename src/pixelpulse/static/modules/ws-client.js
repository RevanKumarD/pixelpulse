/**
 * WebSocket Client
 *
 * Connects to /ws/events, handles reconnection, and dispatches
 * incoming events to the state store.
 */

import {
  updateAgent,
  updatePipeline,
  updateCost,
  addEvent,
  setConnection,
} from "./state.js";
import { show as showToast } from "./toasts.js";

let ws = null;
let reconnectTimer = null;
let messageFlowCallback = null;
let reconnectBtn;
let hasShownDisconnect = false;  // only show disconnect toast once per session
let wasEverConnected = false;    // don't show disconnect if never connected

/**
 * Register a callback for message_flow events (used by renderer for particles).
 */
export function onMessageFlow(fn) {
  messageFlowCallback = fn;
}

/**
 * Connect to the WebSocket endpoint.
 */
export function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${location.host}/ws/events`;

  setConnection("connecting");

  reconnectBtn = reconnectBtn || document.getElementById("reconnect-btn");
  if (reconnectBtn) {
    reconnectBtn.onclick = () => connect();
  }

  try {
    ws = new WebSocket(url);
  } catch {
    setConnection("disconnected");
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    setConnection("connected");
    clearReconnect();
    wasEverConnected = true;
    hasShownDisconnect = false;  // reset so we can show disconnect again if it drops
    showToast("Connected to server", "success", 3000);
    if (reconnectBtn) reconnectBtn.style.display = "none";
  };

  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      const batch = Array.isArray(data) ? data : [data];
      for (const event of batch) {
        handleEvent(event);
      }
    } catch (err) {
      console.error("WS parse error:", err);
    }
  };

  ws.onclose = () => {
    setConnection("disconnected");
    scheduleReconnect();
    // Only show disconnect toast once (not on every retry), and only if we were ever connected
    if (wasEverConnected && !hasShownDisconnect) {
      showToast("Disconnected from server — retrying...", "warning");
      hasShownDisconnect = true;
    }
    if (reconnectBtn) reconnectBtn.style.display = "";
  };

  ws.onerror = () => {
    ws.close();
  };
}

function scheduleReconnect() {
  clearReconnect();
  reconnectTimer = setTimeout(connect, 3000);
}

function clearReconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function handleEvent(event) {
  if (!event || !event.type) return;

  switch (event.type) {
    case "state_snapshot":
      if (event.payload?.runs) {
        updatePipeline({ runs: event.payload.runs });
      }
      break;

    case "agent_status":
      if (event.payload) {
        updateAgent(event.payload.agent_id, {
          status: event.payload.status || "idle",
          task: event.payload.current_task || event.payload.task || "",
        });
      }
      break;

    case "message_flow":
      if (event.payload && messageFlowCallback) {
        messageFlowCallback(event.payload.from, event.payload.to);
      }
      break;

    case "pipeline_progress":
      if (event.payload) {
        updatePipeline({ stage: event.payload.stage });
      }
      break;

    case "cost_update":
      if (event.payload) {
        updateCost(
          event.payload.agent_id,
          event.payload.cost || 0,
          event.payload.total,
        );
      }
      break;

    case "error":
      if (event.payload?.agent_id) {
        updateAgent(event.payload.agent_id, { status: "error" });
      }
      break;
  }

  addEvent(event);
}
