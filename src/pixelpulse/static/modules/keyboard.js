/**
 * Keyboard Shortcuts
 *
 * Registers global keydown handlers. Ignores input when focus is in
 * form elements or when a <dialog> is open (except Esc).
 */
import * as Settings from "./settings.js";
import { fitView, zoomToRoom } from "./renderer.js";
import { TEAMS, getFocusedRoom, setFocusedRoom } from "./state.js";
import * as demo from "./demo.js";

let helpDialog;

// panToTeam is added to renderer.js — import dynamically to avoid
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
    case "Escape":
      // Exit focus mode if active (don't preventDefault so dialogs still close)
      if (getFocusedRoom()) {
        setFocusedRoom(null);
        fitView();
      }
      break;

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
      // F toggles flow connectors
      e.preventDefault();
      Settings.set("showConnectors", !Settings.get("showConnectors"));
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

    case "0": {
      // Return to overview
      e.preventDefault();
      setFocusedRoom(null);
      fitView();
      break;
    }

    case "1":
    case "2":
    case "3":
    case "4":
    case "5":
    case "6":
    case "7":
    case "8":
    case "9": {
      e.preventDefault();
      const idx = parseInt(e.key) - 1;
      const teamIds = Object.keys(TEAMS);
      if (idx < teamIds.length) {
        zoomToRoom(teamIds[idx]);
      }
      break;
    }

    case "?":
      e.preventDefault();
      if (helpDialog) helpDialog.showModal();
      break;
  }
}
