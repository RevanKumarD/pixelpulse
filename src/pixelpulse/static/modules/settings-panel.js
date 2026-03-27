/**
 * Settings Panel Controller
 *
 * Opens/closes the settings <dialog>, binds all [data-setting] inputs to
 * settings.js via a generic loop, and keeps controls in sync when settings
 * change externally (keyboard shortcuts, drag-resize).
 */
import * as Settings from "./settings.js";

let dialog;

export function init() {
  dialog = document.getElementById("settings-drawer");
  if (!dialog) return;

  dialog.querySelector(".settings-drawer__close")
    .addEventListener("click", close);

  // Backdrop click to close
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) close();
  });

  document.getElementById("settings-reset")
    .addEventListener("click", () => {
      Settings.resetAll();
      _syncAllControls();
    });

  _bindControls();
  _syncAllControls();

  // Sync drawer when settings change externally (keyboard, drag-resize)
  Settings.onChange("*", () => {
    if (dialog.open) _syncAllControls();
  });
}

export function open() {
  _syncAllControls();
  dialog.showModal();
}

export function close() {
  dialog.close();
}

export function toggle() {
  dialog.open ? close() : open();
}

function _bindControls() {
  const inputs = dialog.querySelectorAll("[data-setting]");
  for (const input of inputs) {
    const key = input.dataset.setting;
    const invert = input.dataset.invert === "true";
    const eventType = input.type === "checkbox" || input.tagName === "SELECT"
      ? "change" : "input";

    input.addEventListener(eventType, () => {
      let value;
      if (input.type === "checkbox") {
        value = invert ? !input.checked : input.checked;
      } else if (input.type === "range") {
        value = parseFloat(input.value);
      } else {
        value = input.value;
      }
      Settings.set(key, value);
      _updateOutput(key, value);
    });
  }
}

function _syncAllControls() {
  const inputs = dialog.querySelectorAll("[data-setting]");
  for (const input of inputs) {
    const key = input.dataset.setting;
    const invert = input.dataset.invert === "true";
    const value = Settings.get(key);
    if (input.type === "checkbox") {
      input.checked = invert ? !value : value;
    } else {
      input.value = value;
    }
    _updateOutput(key, value);
  }
}

function _updateOutput(key, value) {
  const output = dialog.querySelector(`[data-output="${key}"]`);
  if (!output) return;
  const fmt = {
    fontScale: (v) => v.toFixed(2),
    animationSpeed: (v) => v === 0 ? "Paused" : `${v.toFixed(2)}x`,
    bottomBarHeight: (v) => `${v}px`,
    zoomLevel: (v) => `${v.toFixed(2)}x`,
  };
  output.textContent = (fmt[key] || String)(value);
}
