/**
 * theme.js — Maps theme names to CSS custom property sets and applies them to the document.
 *
 * Exports:
 *   init()          — Apply current theme from settings and subscribe to future changes
 *   getCanvasColors() — Return a frozen canvas color object for the active theme
 */

import { get, onChange } from "./settings.js";

// ---------------------------------------------------------------------------
// Theme definitions
// ---------------------------------------------------------------------------

const THEMES = {
  dark: {
    "--bg": "#080c14",
    "--surface": "#0f1520",
    "--surface-alt": "#161e2e",
    "--border": "#1e293b",
    "--border-glow": "#2d3f5a",
    "--text": "#e2e8f0",
    "--text-dim": "#94a3b8",
    "--text-muted": "#64748b",
    "--research": "#00d4ff",
    "--design": "#ff6ec7",
    "--commerce": "#39ff14",
    "--learning": "#ffae00",
    "--active": "#00d4ff",
    "--idle": "#64748b",
    "--waiting": "#ffae00",
    "--error": "#f85149",
    "--success": "#39ff14",
    "--scanline-opacity": "0.03",
    "--glow-opacity": "0.6",
  },

  light: {
    "--bg": "#f0f2f5",
    "--surface": "#ffffff",
    "--surface-alt": "#e8eaf0",
    "--border": "#d0d4dc",
    "--border-glow": "#b0b8c8",
    "--text": "#1a1e2e",
    "--text-dim": "#5a6478",
    "--text-muted": "#8090a8",
    "--research": "#0288d1",
    "--design": "#9c27b0",
    "--commerce": "#2e7d32",
    "--learning": "#f57c00",
    "--active": "#0288d1",
    "--idle": "#8090a8",
    "--waiting": "#f57c00",
    "--error": "#c62828",
    "--success": "#2e7d32",
    "--scanline-opacity": "0.01",
    "--glow-opacity": "0.3",
  },

  "high-contrast": {
    "--bg": "#000000",
    "--surface": "#0a0a0a",
    "--surface-alt": "#1a1a1a",
    "--border": "#ffffff",
    "--border-glow": "#ffffff",
    "--text": "#ffffff",
    "--text-dim": "#cccccc",
    "--text-muted": "#999999",
    "--research": "#00ffff",
    "--design": "#ff00ff",
    "--commerce": "#00ff00",
    "--learning": "#ffaa00",
    "--active": "#00ffff",
    "--idle": "#999999",
    "--waiting": "#ffaa00",
    "--error": "#ff0000",
    "--success": "#00ff00",
    "--scanline-opacity": "0",
    "--glow-opacity": "1.0",
  },
};

// Default base font size in px that corresponds to fontScale = 1
const BASE_FONT_SIZE_PX = 14;

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Resolve a theme name to its variable map, falling back to dark if unknown.
 * @param {string} name
 * @returns {Record<string, string>}
 */
function resolveTheme(name) {
  return THEMES[name] ?? THEMES["dark"];
}

/**
 * Apply a theme variable map to document.documentElement and set data-theme.
 * @param {string} name
 */
function applyTheme(name) {
  const vars = resolveTheme(name);
  const root = document.documentElement;

  root.setAttribute("data-theme", name);

  for (const [prop, value] of Object.entries(vars)) {
    root.style.setProperty(prop, value);
  }
}

/**
 * Compute font size in px from a fontScale value and apply --font-size.
 * @param {number} scale
 */
function applyFontScale(scale) {
  const px = Math.round(BASE_FONT_SIZE_PX * scale);
  document.documentElement.style.setProperty("--font-size", `${px}px`);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Initialise the theme system.
 * Reads the current theme and fontScale from Settings, applies them immediately,
 * then subscribes to future changes.
 */
export function init() {
  // Apply theme immediately from stored settings
  const currentTheme = get("theme") ?? "dark";
  applyTheme(currentTheme);

  // Apply font scale immediately
  const currentScale = get("fontScale") ?? 1;
  applyFontScale(currentScale);

  // Subscribe to theme changes
  onChange("theme", (newTheme) => {
    applyTheme(newTheme ?? "dark");
  });

  // Subscribe to font scale changes
  onChange("fontScale", (newScale) => {
    applyFontScale(newScale ?? 1);
  });
}

/**
 * Return a frozen canvas color object reflecting the currently active theme.
 * `warning` maps to the `--waiting` CSS variable value.
 * @returns {Readonly<{
 *   bg: string, surface: string, border: string,
 *   text: string, textDim: string,
 *   research: string, design: string, commerce: string, learning: string,
 *   active: string, error: string, success: string, warning: string
 * }>}
 */
export function getCanvasColors() {
  const themeName = get("theme") ?? "dark";
  const vars = resolveTheme(themeName);

  return Object.freeze({
    bg: vars["--bg"],
    surface: vars["--surface"],
    border: vars["--border"],
    text: vars["--text"],
    textDim: vars["--text-dim"],
    research: vars["--research"],
    design: vars["--design"],
    commerce: vars["--commerce"],
    learning: vars["--learning"],
    active: vars["--active"],
    error: vars["--error"],
    success: vars["--success"],
    warning: vars["--waiting"],
  });
}
