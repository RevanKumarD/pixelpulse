/**
 * PixelPulse — Agent Office Dashboard
 * "Mission Control" — Canvas 2D pixel-art office visualization
 */

import { loadConfig } from "./modules/state.js";
import { loadCharacterSprites } from "./modules/sprites.js";
import { init as initRenderer, fitView, zoomIn, zoomOut, resetView, togglePanMode, screenshot } from "./modules/renderer.js";
import { connect } from "./modules/ws-client.js";
import * as demo from "./modules/demo.js";
import { getEvents } from "./modules/state.js";
import * as Settings from "./modules/settings.js";
import * as Theme from "./modules/theme.js";
import * as SettingsPanel from "./modules/settings-panel.js";
import * as Keyboard from "./modules/keyboard.js";
import * as Toasts from "./modules/toasts.js";
import * as AgentDetail from "./modules/agent-detail.js";
import * as RunHistory from "./modules/run-history.js";
import * as Replay from "./modules/replay.js";
import * as VideoExport from "./modules/video-export.js";

document.addEventListener("DOMContentLoaded", async () => {
  // 0. Apply CSS theme before first render
  Theme.init();

  // 1. Load dynamic config (teams, agents, pipeline stages) from server
  await loadConfig();

  // 2. Load character PNG sprite sheets (async)
  await loadCharacterSprites();

  // 3. Build renderer and subscribe to state
  initRenderer();

  // 4. Bind settings drawer UI
  SettingsPanel.init();

  // 5. Register keyboard shortcuts
  Keyboard.init();

  // 6. Ready toast notifications
  Toasts.init();

  // 7. Ready agent detail panel for clicks
  AgentDetail.init();

  // 8. Initialize replay engine
  Replay.init({
    onRecord: () => {
      const canvas = document.getElementById("office-canvas");
      if (canvas) VideoExport.toggleRecording(canvas);
    },
    onExit: () => {
      RunHistory.loadRuns(); // Refresh list after exiting replay
    },
  });

  // 9. Initialize video export
  VideoExport.init();

  // 10. Initialize run history sidebar
  RunHistory.init((runId) => {
    Replay.startReplay(runId);
  });

  // 11. Connect WebSocket last (may trigger toasts)
  connect();

  // Theme toggle switch (dark / light)
  const themeCheckbox = document.getElementById("theme-checkbox");
  function syncThemeToggle() {
    const t = Settings.get("theme") || "dark";
    if (themeCheckbox) themeCheckbox.checked = t === "light";
  }
  if (themeCheckbox) {
    themeCheckbox.addEventListener("change", () => {
      Settings.set("theme", themeCheckbox.checked ? "light" : "dark");
    });
    syncThemeToggle();
    Settings.onChange("theme", syncThemeToggle);
  }

  // Gear / settings button
  const settingsBtn = document.getElementById("settings-btn");
  if (settingsBtn) settingsBtn.addEventListener("click", SettingsPanel.toggle);

  // Demo button
  const demoBtn = document.getElementById("demo-btn");
  if (demoBtn) {
    demoBtn.addEventListener("click", () => {
      if (demo.isRunning()) {
        demo.stop();
        demoBtn.textContent = "\u25b6 Demo";
        demoBtn.classList.remove("btn--active");
      } else {
        demo.start();
        demoBtn.textContent = "\u25a0 Stop";
        demoBtn.classList.add("btn--active");
      }
    });
  }

  // Speed control
  const speedSelect = document.getElementById("speed-select");
  if (speedSelect) {
    speedSelect.addEventListener("change", () => {
      demo.setSpeed(parseInt(speedSelect.value, 10));
    });
  }

  // Sidebar toggle -- collapse/expand on desktop, slide on mobile
  const toggle = document.getElementById("sidebar-toggle");
  const sidebar = document.getElementById("sidebar");
  const dashboard = document.querySelector(".dashboard");
  if (toggle && sidebar && dashboard) {
    toggle.addEventListener("click", () => {
      const isMobile = window.innerWidth < 1280;
      if (isMobile) {
        // Mobile: slide overlay
        const isOpen = sidebar.classList.toggle("sidebar--open");
        toggle.classList.toggle("btn--active", isOpen);
        toggle.textContent = isOpen ? "\u2715 Close" : "\u25e7 Panel";
      } else {
        // Desktop: collapse grid column
        const collapsed = dashboard.classList.toggle("dashboard--sidebar-collapsed");
        toggle.classList.toggle("btn--active", !collapsed);
        toggle.textContent = collapsed ? "\u25e7 Panel" : "\u2715 Panel";
      }
      setTimeout(() => window.dispatchEvent(new Event("resize")), 350);
    });
  }

  // Canvas view controls
  const ctrlFit = document.getElementById("ctrl-fit");
  const ctrlZoomIn = document.getElementById("ctrl-zoom-in");
  const ctrlZoomOut = document.getElementById("ctrl-zoom-out");
  const ctrlReset = document.getElementById("ctrl-reset");
  const ctrlPan = document.getElementById("ctrl-pan");
  if (ctrlFit) ctrlFit.addEventListener("click", fitView);
  if (ctrlZoomIn) ctrlZoomIn.addEventListener("click", zoomIn);
  if (ctrlZoomOut) ctrlZoomOut.addEventListener("click", zoomOut);
  if (ctrlReset) ctrlReset.addEventListener("click", resetView);
  if (ctrlPan) ctrlPan.addEventListener("click", togglePanMode);

  // Bottom bar collapse toggle -- button lives outside bottom-bar, always visible
  const bottomCollapse = document.getElementById("bottom-collapse");
  if (bottomCollapse && dashboard) {
    bottomCollapse.addEventListener("click", () => {
      const collapsed = dashboard.classList.toggle("dashboard--bottom-collapsed");
      bottomCollapse.textContent = collapsed ? "\u25b2 Show Logs" : "\u25bc Logs";
      setTimeout(() => window.dispatchEvent(new Event("resize")), 250);
    });
  }

  // Sidebar drag-resize (width)
  const sidebarResize = document.getElementById("sidebar-resize");
  if (sidebarResize && sidebar && dashboard) {
    let sResizing = false;
    let sStartX = 0;
    let sStartW = 0;

    sidebarResize.addEventListener("mousedown", (e) => {
      sResizing = true;
      sStartX = e.clientX;
      sStartW = sidebar.offsetWidth;
      e.preventDefault();
    });

    window.addEventListener("mousemove", (e) => {
      if (!sResizing) return;
      const delta = sStartX - e.clientX;
      const newW = Math.max(200, Math.min(sStartW + delta, window.innerWidth * 0.4));
      dashboard.style.setProperty("--sidebar-w", newW + "px");
    });

    window.addEventListener("mouseup", () => {
      if (sResizing) {
        sResizing = false;
        window.dispatchEvent(new Event("resize"));
      }
    });
  }

  // Bottom bar drag-resize
  const bottomResize = document.getElementById("bottom-resize");
  if (bottomResize && dashboard) {
    let resizing = false;
    let startY = 0;
    let startH = 0;

    bottomResize.addEventListener("mousedown", (e) => {
      resizing = true;
      startY = e.clientY;
      startH = parseInt(getComputedStyle(dashboard).getPropertyValue("--bottom-h"), 10) || 220;
      e.preventDefault();
    });

    window.addEventListener("mousemove", (e) => {
      if (!resizing) return;
      const delta = startY - e.clientY;
      const newH = Math.max(80, Math.min(startH + delta, window.innerHeight * 0.6));
      // Write through Settings -- onChange subscriber sets --bottom-h
      Settings.set("bottomBarHeight", newH);
    });

    window.addEventListener("mouseup", () => {
      if (resizing) {
        resizing = false;
        window.dispatchEvent(new Event("resize"));
      }
    });
  }

  // Settings subscribers for layout

  // Sidebar visibility
  Settings.onChange("sidebarVisible", (visible) => {
    const dashboardEl = document.querySelector(".dashboard");
    if (dashboardEl) {
      dashboardEl.classList.toggle("dashboard--sidebar-collapsed", !visible);
      setTimeout(() => window.dispatchEvent(new Event("resize")), 350);
    }
  });

  // Bottom bar height
  Settings.onChange("bottomBarHeight", (h) => {
    const dashboardEl = document.querySelector(".dashboard");
    if (dashboardEl) dashboardEl.style.setProperty("--bottom-h", h + "px");
  });

  // Scanlines
  Settings.onChange("scanlinesEnabled", (enabled) => {
    const scanlines = document.querySelector(".scanlines");
    if (scanlines) scanlines.style.display = enabled ? "" : "none";
  });

  // Apply initial values from settings
  const dashboardEl = document.querySelector(".dashboard");
  if (dashboardEl) {
    dashboardEl.style.setProperty("--bottom-h", Settings.get("bottomBarHeight") + "px");
  }
  const scanlinesEl = document.querySelector(".scanlines");
  if (scanlinesEl && !Settings.get("scanlinesEnabled")) scanlinesEl.style.display = "none";

  // Screenshot export
  const screenshotBtn = document.getElementById("ctrl-screenshot");
  if (screenshotBtn) {
    screenshotBtn.addEventListener("click", async () => {
      const blob = await screenshot();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `pixelpulse-${Date.now()}.png`;
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  // Export events JSON
  const exportBtn = document.getElementById("export-events");
  if (exportBtn) {
    exportBtn.addEventListener("click", () => {
      const data = JSON.stringify(getEvents(), null, 2);
      const blob = new Blob([data], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `pixelpulse-events-${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
    });
  }
});
