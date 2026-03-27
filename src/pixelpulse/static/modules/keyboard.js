/**
 * Keyboard Shortcuts
 *
 * Registers global keydown handlers. Ignores input when focus is in
 * form elements or when a <dialog> is open (except Esc).
 */
import * as Settings from "./settings.js";
import { fitView } from "./renderer.js";
import * as demo from "./demo.js";

const TEAM_IDS = ["research", "design", "commerce", "learning"];
let helpDialog;

// panToTeam is added to renderer.js in Task 8 — import dynamically to avoid
// breaking if this module loads before the renderer export exists.
let _panToTeam = null;
import("./renderer.js").then((mod) => {
  if (typeof mod.panToTeam === "function") _panToTeam = mod.panToTeam;
});

export function init() {
  helpDialog = document.getElementById("keyboard-help");
  if (helpDialog) {
    helpDialog.querySelector(".keyboard-help__close")
      .addEventListener("click", () => helpDialog.close());
    helpDialog.addEventListener("click", (e) => {
      if (e.target === helpDialog) helpDialog.close();
    });
  }

  document.addEventListener("keydown", _onKeyDown);
}

function _onKeyDown(e) {
  // Skip if typing in an input field
  const tag = e.target.tagName;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;

  // Skip if any dialog is open (except Esc which dialogs handle natively)
  if (document.querySelector("dialog[open]") && e.key !== "Escape") return;

  switch (e.key) {
    case " ":
      e.preventDefault();
      if (demo.isRunning()) {
        demo.stop();
      } else {
        demo.start();
      }
      // Update demo button text
      {
        const btn = document.getElementById("demo-btn");
        if (btn) {
          btn.textContent = demo.isRunning() ? "■ Stop" : "▶ Demo";
          btn.classList.toggle("btn--active", demo.isRunning());
        }
      }
      break;

    case "f":
    case "F":
      e.preventDefault();
      fitView();
      break;

    case "+":
    case "=":
      e.preventDefault();
      Settings.set("zoomLevel", Math.min(Settings.get("zoomLevel") + 0.25, 3));
      break;

    case "-":
      e.preventDefault();
      Settings.set("zoomLevel", Math.max(Settings.get("zoomLevel") - 0.25, 0.5));
      break;

    case "1":
    case "2":
    case "3":
    case "4": {
      e.preventDefault();
      const idx = parseInt(e.key) - 1;
      if (_panToTeam) _panToTeam(TEAM_IDS[idx]);
      break;
    }

    case "?":
      e.preventDefault();
      if (helpDialog) helpDialog.showModal();
      break;
  }
}
