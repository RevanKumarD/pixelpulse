/**
 * Settings Store
 *
 * Single source of truth for all dashboard preferences. Persists to
 * localStorage and notifies subscribers on every change.
 *
 * API:
 *   Settings.get('sidebarSections.pipeline')  // dot-notation read
 *   Settings.set('fontScale', 1.25)            // dot-notation write
 *   Settings.onChange('theme', (next, prev) => …)  // subscribe; returns unsub fn
 *   Settings.onChange('*', (next, prev, key) => …) // wildcard — any change
 *   Settings.resetAll()                         // restore defaults
 *   Settings.getAll()                           // deep clone of current
 *   Settings.getDefaults()                      // deep clone of defaults
 */

const STORAGE_KEY = 'pixelpulse-settings';

// --- Default values ---

const DEFAULTS = Object.freeze({
  theme: 'dark',              // 'dark' | 'light' | 'high-contrast'
  fontScale: 1.0,             // 0.75 – 1.5, step 0.125
  animationSpeed: 1.0,        // 0 (paused) – 2.0, step 0.25
  scanlinesEnabled: true,     // boolean
  canvasSmoothing: false,     // false = pixel-perfect
  sidebarVisible: true,       // boolean
  bottomBarHeight: 220,       // 80 – 400px
  zoomLevel: 1.0,             // 0.5 – 3.0, step 0.25
  sidebarSections: Object.freeze({
    pipeline: true,
    agents: true,
    runs: true,
    cost: true,
  }),
});

// --- Internal state ---

// Flat map of subscribers: key → Set<callback>
// '*' is used for wildcard subscribers.
const subscribers = new Map();

let current = structuredClone(DEFAULTS);

// --- Helpers ---

/**
 * Resolve a dot-notation key into the value at that path within an object.
 * Returns `undefined` if any segment is missing.
 *
 * @param {object} obj
 * @param {string} key  e.g. 'sidebarSections.pipeline'
 * @returns {*}
 */
function _getPath(obj, key) {
  return key.split('.').reduce((node, segment) => {
    if (node === undefined || node === null) return undefined;
    return node[segment];
  }, obj);
}

/**
 * Immutably set a value at a dot-notation path within a plain object.
 * Returns a new object; the original is never mutated.
 *
 * @param {object} obj
 * @param {string} key
 * @param {*}      value
 * @returns {object}
 */
function _setPath(obj, key, value) {
  const segments = key.split('.');
  if (segments.length === 1) {
    return { ...obj, [key]: value };
  }
  const [head, ...tail] = segments;
  return {
    ...obj,
    [head]: _setPath(obj[head] ?? {}, tail.join('.'), value),
  };
}

/**
 * Return only the keys that exist in `defaults` (recursively), discarding
 * unknown keys from `saved` for forward compatibility.
 *
 * @param {object} defaults
 * @param {object} saved
 * @returns {object}
 */
function _mergeOverDefaults(defaults, saved) {
  const merged = structuredClone(defaults);
  for (const key of Object.keys(defaults)) {
    if (!(key in saved)) continue;
    const defaultVal = defaults[key];
    const savedVal = saved[key];
    if (
      defaultVal !== null &&
      typeof defaultVal === 'object' &&
      !Array.isArray(defaultVal) &&
      typeof savedVal === 'object' &&
      savedVal !== null
    ) {
      merged[key] = _mergeOverDefaults(defaultVal, savedVal);
    } else {
      merged[key] = savedVal;
    }
  }
  return merged;
}

/**
 * Fire all callbacks registered for `key` as well as any wildcard ('*')
 * callbacks.
 *
 * @param {string} key        Dot-notation key that changed
 * @param {*}      newValue
 * @param {*}      oldValue
 */
function _notify(key, newValue, oldValue) {
  const keyListeners = subscribers.get(key);
  if (keyListeners) {
    for (const cb of keyListeners) {
      try {
        cb(newValue, oldValue);
      } catch (err) {
        console.error('[Settings] subscriber error for key', key, err);
      }
    }
  }

  const wildcardListeners = subscribers.get('*');
  if (wildcardListeners) {
    for (const cb of wildcardListeners) {
      try {
        cb(newValue, oldValue, key);
      } catch (err) {
        console.error('[Settings] wildcard subscriber error:', err);
      }
    }
  }
}

// --- Persistence ---

function _save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
  } catch (err) {
    console.warn('[Settings] could not save to localStorage:', err);
  }
}

function _load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      current = _mergeOverDefaults(DEFAULTS, saved);
    } else {
      current = structuredClone(DEFAULTS);
    }
  } catch (err) {
    console.warn('[Settings] could not load from localStorage, using defaults:', err);
    current = structuredClone(DEFAULTS);
  }
}

// Load immediately at module evaluation time so settings are ready before
// any init() runs.
_load();

// --- Public API ---

/**
 * Read a setting value by dot-notation key.
 *
 * @param {string} key  e.g. 'sidebarSections.pipeline'
 * @returns {*}
 */
export function get(key) {
  const value = _getPath(current, key);
  // Return a deep clone for objects so callers cannot mutate internal state
  if (value !== null && typeof value === 'object') {
    return structuredClone(value);
  }
  return value;
}

/**
 * Write a setting value by dot-notation key. Persists immediately and
 * notifies subscribers.
 *
 * @param {string} key
 * @param {*}      value
 */
export function set(key, value) {
  const oldValue = _getPath(current, key);
  current = _setPath(current, key, value);
  _save();
  _notify(key, value, oldValue);
}

/**
 * Subscribe to changes for a specific key (or '*' for all changes).
 *
 * @param {string}   key       Dot-notation key, or '*' for wildcard
 * @param {Function} callback  Called as (newValue, oldValue) — or
 *                             (newValue, oldValue, changedKey) for '*'
 * @returns {Function}         Unsubscribe function
 */
export function onChange(key, callback) {
  if (!subscribers.has(key)) {
    subscribers.set(key, new Set());
  }
  subscribers.get(key).add(callback);
  return () => {
    const set_ = subscribers.get(key);
    if (set_) set_.delete(callback);
  };
}

/**
 * Restore all settings to their default values, persist, and notify every
 * subscriber (per-key callbacks fire for each changed key; wildcard fires
 * once per key).
 */
export function resetAll() {
  const old = current;
  current = structuredClone(DEFAULTS);
  _save();

  // Collect all leaf keys from DEFAULTS and notify each one that changed
  function _collectKeys(obj, prefix) {
    const keys = [];
    for (const k of Object.keys(obj)) {
      const fullKey = prefix ? `${prefix}.${k}` : k;
      const val = obj[k];
      if (val !== null && typeof val === 'object' && !Array.isArray(val)) {
        keys.push(..._collectKeys(val, fullKey));
      } else {
        keys.push(fullKey);
      }
    }
    return keys;
  }

  for (const leafKey of _collectKeys(DEFAULTS, '')) {
    const newVal = _getPath(current, leafKey);
    const oldVal = _getPath(old, leafKey);
    _notify(leafKey, newVal, oldVal);
  }
}

/**
 * Return a deep clone of the current settings object.
 *
 * @returns {object}
 */
export function getAll() {
  return structuredClone(current);
}

/**
 * Return a deep clone of the defaults object.
 *
 * @returns {object}
 */
export function getDefaults() {
  return structuredClone(DEFAULTS);
}
