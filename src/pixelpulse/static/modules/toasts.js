/**
 * Toast Notifications
 *
 * Displays a queue of notification toasts in the top-right corner.
 * Auto-dismisses after duration (default 5s). Errors and warnings are
 * sticky (require manual dismiss). Maximum 5 visible toasts.
 */
const MAX_TOASTS = 5;
let container;
const queue = [];

export function init() {
  container = document.getElementById("toast-container");
}

/**
 * Show a toast notification.
 * @param {string} message - Text to display
 * @param {'success'|'warning'|'error'|'info'} type - Toast type
 * @param {number} duration - Auto-dismiss delay in ms (0 = no auto-dismiss)
 */
export function show(message, type = "info", duration = 5000) {
  if (!container) return;

  const el = document.createElement("div");
  el.className = `toast toast--${type}`;
  el.innerHTML = `
    <span class="toast__text">${_escapeHtml(message)}</span>
    <button class="toast__close" aria-label="Dismiss">&times;</button>
  `;

  el.querySelector(".toast__close").addEventListener("click", () => _dismiss(el));

  container.appendChild(el);
  queue.push(el);

  // Auto-dismiss (skip for sticky types)
  const sticky = type === "error" || type === "warning";
  if (!sticky && duration > 0) {
    setTimeout(() => _dismiss(el), duration);
  }

  // Enforce max
  while (queue.length > MAX_TOASTS) {
    _dismiss(queue[0]);
  }
}

function _dismiss(el) {
  const idx = queue.indexOf(el);
  if (idx !== -1) queue.splice(idx, 1);
  if (!el.parentNode) return;
  el.classList.add("toast--exiting");
  setTimeout(() => el.remove(), 300);
}

function _escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
