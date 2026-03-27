/**
 * Sprite System
 *
 * Loads 6 character PNG sprite sheets (16x32, 7 frames, 3 directions).
 * Defines inline furniture pixel data (desk, monitor, plant, bookshelf, chair).
 * Renders sprites to offscreen canvases, cached per zoom level.
 */

// ---- Constants ----
export const TILE_SIZE = 32;
const CHAR_FRAME_W = 16;
const CHAR_FRAME_H = 32;
const CHAR_FRAMES_PER_ROW = 7; // walk1,walk2,walk3,type1,type2,read1,read2
const CHAR_COUNT = 6;
const PNG_ALPHA_THRESHOLD = 128;

// ---- Sprite Cache (zoom-aware, like AgentRoom's spriteCache.ts) ----
const zoomCaches = new Map();

export function getCachedSprite(sprite, zoom) {
  let cache = zoomCaches.get(zoom);
  if (!cache) {
    cache = new WeakMap();
    zoomCaches.set(zoom, cache);
  }
  const cached = cache.get(sprite);
  if (cached) return cached;

  const rows = sprite.length;
  const cols = sprite[0].length;
  const canvas = document.createElement("canvas");
  canvas.width = cols * zoom;
  canvas.height = rows * zoom;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const color = sprite[r][c];
      if (!color) continue;
      ctx.fillStyle = color;
      ctx.fillRect(c * zoom, r * zoom, zoom, zoom);
    }
  }
  cache.set(sprite, canvas);
  return canvas;
}

// ---- Upscale (same as AgentRoom assetLoader.ts) ----
export function upscaleSprite(sprite, factor) {
  const result = [];
  for (const row of sprite) {
    const scaledRow = [];
    for (const pixel of row) {
      for (let i = 0; i < factor; i++) scaledRow.push(pixel);
    }
    for (let i = 0; i < factor; i++) result.push([...scaledRow]);
  }
  return result;
}

// ---- Character Sprite Loader (from PNG sheets) ----

// characterSprites[paletteIndex] = { down: [SpriteData x7], up: [x7], right: [x7] }
const characterSprites = [];
let charactersLoaded = false;

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Failed to load: ${src}`));
    img.src = src;
  });
}

function imageToPixelData(img) {
  const canvas = document.createElement("canvas");
  canvas.width = img.width;
  canvas.height = img.height;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(img, 0, 0);
  return ctx.getImageData(0, 0, img.width, img.height);
}

function extractSprite(data, x, y, w, h) {
  const sprite = [];
  for (let row = 0; row < h; row++) {
    const line = [];
    for (let col = 0; col < w; col++) {
      const idx = ((y + row) * data.width + (x + col)) * 4;
      const r = data.data[idx];
      const g = data.data[idx + 1];
      const b = data.data[idx + 2];
      const a = data.data[idx + 3];
      if (a < PNG_ALPHA_THRESHOLD) {
        line.push("");
      } else {
        line.push(
          "#" +
            r.toString(16).padStart(2, "0") +
            g.toString(16).padStart(2, "0") +
            b.toString(16).padStart(2, "0")
        );
      }
    }
    sprite.push(line);
  }
  return sprite;
}

/**
 * Load all 6 character sprite sheets from /static/assets/characters/
 * Each PNG is 112x96: 7 frames x 16px wide, 3 direction rows x 32px tall
 * Row 0 = down, Row 1 = up, Row 2 = right
 * 2x upscaled to 32x64 for display.
 */
export async function loadCharacterSprites() {
  const directions = ["down", "up", "right"];

  for (let ci = 0; ci < CHAR_COUNT; ci++) {
    try {
      const img = await loadImage(`/static/assets/characters/char_${ci}.png`);
      const pixels = imageToPixelData(img);
      const charData = { down: [], up: [], right: [] };

      for (let dirIdx = 0; dirIdx < directions.length; dirIdx++) {
        const dir = directions[dirIdx];
        const rowY = dirIdx * CHAR_FRAME_H;
        for (let f = 0; f < CHAR_FRAMES_PER_ROW; f++) {
          const raw = extractSprite(pixels, f * CHAR_FRAME_W, rowY, CHAR_FRAME_W, CHAR_FRAME_H);
          charData[dir].push(upscaleSprite(raw, 2));
        }
      }
      characterSprites.push(charData);
    } catch (err) {
      console.warn(`Failed to load char_${ci}.png:`, err);
    }
  }
  charactersLoaded = characterSprites.length > 0;
  console.log(`[Sprites] Loaded ${characterSprites.length} character sprite sheets`);
}

/**
 * Get character sprite for a given palette index and animation state.
 * Frame indices: 0-2 = walk, 3-4 = typing, 5-6 = reading
 *
 * All agents face DOWN (toward viewer) since they're seated at desks.
 * The chair backrest is at the top — agents sit facing the same direction.
 *
 * Visual distinctiveness:
 *   idle    — facing DOWN, very slow gentle sway (relaxed at desk, not working)
 *   active  — facing DOWN, fast typing animation (frames 3-4)
 *   waiting — facing DOWN, reading animation (frames 5-6), gentle pace
 *   error   — facing DOWN, static frame 0 (frozen) + red overlay in renderer
 */
export function getCharFrame(paletteIdx, state, tick) {
  if (!charactersLoaded) return null;
  const idx = paletteIdx % characterSprites.length;
  const char = characterSprites[idx];

  // All states face down — agents are always seated at their desk
  const frames = char.down;
  if (!frames || frames.length === 0) return null;

  switch (state) {
    case "active": {
      // Typing at desk: fast toggle between frames 3-4
      if (frames.length < 5) return frames[0];
      return frames[3 + (Math.floor(tick / 15) % 2)];
    }
    case "waiting": {
      // Reading/standing by: frames 5-6, slower toggle
      if (frames.length < 7) return frames[0];
      return frames[5 + (Math.floor(tick / 30) % 2)];
    }
    case "error": {
      // Frozen/stuck: static frame 0
      return frames[0];
    }
    case "idle":
    default: {
      // Idle at desk: very slow gentle breathing/sway using walk frames
      // Much slower than active — clearly relaxed, not working
      if (frames.length < 3) return frames[0];
      const seq = [0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 2, 2];
      return frames[seq[Math.floor(tick / 50) % seq.length]];
    }
  }
}

/**
 * Get a walking frame for a specific direction (for roaming agents).
 * direction: "down" | "up" | "right" | "left"
 * Walk frames are indices 0-2. "left" mirrors "right".
 */
export function getWalkFrame(paletteIdx, direction, tick, running = false) {
  if (!charactersLoaded) return null;
  const idx = paletteIdx % characterSprites.length;
  const char = characterSprites[idx];
  // "left" uses "right" frames (mirrored at draw time)
  const dir = direction === "left" ? "right" : direction;
  const frames = char[dir];
  if (!frames || frames.length < 3) return null;
  // Animate walk cycle: frame 0,1,2,1 — faster when running back to desk
  const walkSeq = [0, 1, 2, 1];
  const tickDivisor = running ? 5 : 12;
  return frames[walkSeq[Math.floor(tick / tickDivisor) % walkSeq.length]];
}

export function areSpritesLoaded() {
  return charactersLoaded;
}

// ---- Furniture Sprites (inline pixel data, ported from AgentRoom spriteData.ts) ----

const _ = "";

// Desk: 32x32 base, 2x upscaled to 64x64
// Desk: 28x16 base, 2x upscaled — wide office desk with front panel and legs
export const DESK_SPRITE = upscaleSprite(
  (() => {
    const W = "#8B6914", L = "#A07828", S = "#B8922E", D = "#6B4E0A", T = "#C4A43A";
    return [
      // Top edge
      [_, _, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, _, _],
      // Surface
      [_, _, W, T, T, T, T, T, T, T, T, T, T, T, T, T, T, T, T, T, T, T, T, T, T, W, _, _],
      [_, _, W, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, W, _, _],
      [_, _, W, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, W, _, _],
      [_, _, W, L, L, L, L, L, L, L, L, L, L, L, L, L, L, L, L, L, L, L, L, L, L, W, _, _],
      // Front panel
      [_, _, D, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, D, _, _],
      [_, _, D, W, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, W, D, _, _],
      [_, _, D, W, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, W, D, _, _],
      [_, _, D, W, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, S, W, D, _, _],
      [_, _, D, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, D, _, _],
      // Legs
      [_, _, _, D, D, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, D, D, _, _, _],
      [_, _, _, D, D, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, D, D, _, _, _],
      [_, _, _, D, D, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, D, D, _, _, _],
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
    ];
  })(),
  2
);

// Laptop: 16x12 base, 2x upscaled — bright screen with keyboard base
export const MONITOR_SPRITE = upscaleSprite(
  (() => {
    const F = "#444444", S = "#0a1628", H = "#2288cc", L = "#115588", B = "#333333", K = "#555555";
    return [
      [_, _, _, _, F, F, F, F, F, F, F, F, _, _, _, _],
      [_, _, _, F, S, H, H, H, H, H, H, S, F, _, _, _],
      [_, _, _, F, H, L, H, H, H, H, L, H, F, _, _, _],
      [_, _, _, F, H, H, H, H, H, H, H, H, F, _, _, _],
      [_, _, _, F, H, H, H, L, L, H, H, H, F, _, _, _],
      [_, _, _, F, S, S, S, S, S, S, S, S, F, _, _, _],
      [_, _, _, F, F, F, F, F, F, F, F, F, F, _, _, _],
      [_, _, B, B, K, K, K, K, K, K, K, K, B, B, _, _],
      [_, _, B, K, K, K, K, K, K, K, K, K, K, B, _, _],
      [_, _, B, B, B, B, B, B, B, B, B, B, B, B, _, _],
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
    ];
  })(),
  2
);

// Chair: 16x16 base, 2x upscaled
export const CHAIR_SPRITE = upscaleSprite(
  (() => {
    const W = "#8B6914", D = "#6B4E0A", S = "#555555", C = "#666666";
    return [
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
      [_, _, _, _, D, D, D, D, D, D, D, D, _, _, _, _],
      [_, _, _, _, D, S, S, S, S, S, S, D, _, _, _, _],
      [_, _, _, _, D, S, C, C, C, C, S, D, _, _, _, _],
      [_, _, _, _, D, S, C, C, C, C, S, D, _, _, _, _],
      [_, _, _, _, D, S, C, C, C, C, S, D, _, _, _, _],
      [_, _, _, _, D, S, C, C, C, C, S, D, _, _, _, _],
      [_, _, _, _, D, S, S, S, S, S, S, D, _, _, _, _],
      [_, _, _, _, D, D, D, D, D, D, D, D, _, _, _, _],
      [_, _, _, _, _, D, _, _, _, _, D, _, _, _, _, _],
      [_, _, _, _, _, D, _, _, _, _, D, _, _, _, _, _],
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
    ];
  })(),
  2
);

// Plant in pot: 16x24 base, 2x upscaled to 32x48
export const PLANT_SPRITE = upscaleSprite(
  [
    [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
    [_, _, _, _, _, _, "#3D8B37", "#3D8B37", _, _, _, _, _, _, _, _],
    [_, _, _, _, _, "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", _, _, _, _, _, _, _],
    [_, _, _, _, "#3D8B37", "#3D8B37", "#2D6B27", "#3D8B37", "#3D8B37", "#3D8B37", _, _, _, _, _, _],
    [_, _, _, "#3D8B37", "#3D8B37", "#2D6B27", "#3D8B37", "#3D8B37", "#2D6B27", "#3D8B37", "#3D8B37", _, _, _, _, _],
    [_, _, "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", _, _, _, _],
    [_, "#3D8B37", "#3D8B37", "#2D6B27", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#2D6B27", "#3D8B37", "#3D8B37", _, _, _],
    [_, "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#2D6B27", "#3D8B37", "#3D8B37", "#2D6B27", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", _, _, _],
    [_, _, "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", _, _, _, _],
    [_, _, _, "#3D8B37", "#3D8B37", "#3D8B37", "#2D6B27", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", _, _, _, _, _],
    [_, _, _, _, "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", _, _, _, _, _, _],
    [_, _, _, _, _, "#3D8B37", "#3D8B37", "#3D8B37", "#3D8B37", _, _, _, _, _, _, _],
    [_, _, _, _, _, _, "#6B4E0A", "#6B4E0A", _, _, _, _, _, _, _, _],
    [_, _, _, _, _, _, "#6B4E0A", "#6B4E0A", _, _, _, _, _, _, _, _],
    [_, _, _, _, _, _, "#6B4E0A", "#6B4E0A", _, _, _, _, _, _, _, _],
    [_, _, _, _, _, "#8B4422", "#8B4422", "#8B4422", "#8B4422", "#8B4422", _, _, _, _, _, _],
    [_, _, _, _, "#8B4422", "#B85C3A", "#B85C3A", "#B85C3A", "#B85C3A", "#B85C3A", "#8B4422", _, _, _, _, _],
    [_, _, _, _, "#8B4422", "#B85C3A", "#B85C3A", "#B85C3A", "#B85C3A", "#B85C3A", "#8B4422", _, _, _, _, _],
    [_, _, _, _, "#8B4422", "#B85C3A", "#B85C3A", "#B85C3A", "#B85C3A", "#B85C3A", "#8B4422", _, _, _, _, _],
    [_, _, _, _, "#8B4422", "#B85C3A", "#B85C3A", "#B85C3A", "#B85C3A", "#B85C3A", "#8B4422", _, _, _, _, _],
    [_, _, _, _, "#8B4422", "#B85C3A", "#B85C3A", "#B85C3A", "#B85C3A", "#B85C3A", "#8B4422", _, _, _, _, _],
    [_, _, _, _, "#8B4422", "#B85C3A", "#B85C3A", "#B85C3A", "#B85C3A", "#B85C3A", "#8B4422", _, _, _, _, _],
    [_, _, _, _, _, "#8B4422", "#B85C3A", "#B85C3A", "#B85C3A", "#8B4422", _, _, _, _, _, _],
    [_, _, _, _, _, _, "#8B4422", "#8B4422", "#8B4422", _, _, _, _, _, _, _],
  ],
  2
);

// Bookshelf: 16x32 base, 2x upscaled
export const BOOKSHELF_SPRITE = upscaleSprite(
  (() => {
    const W = "#8B6914", D = "#6B4E0A";
    const R = "#CC4444", B = "#4477AA", G = "#44AA66", Y = "#CCAA33", P = "#9955AA";
    return [
      [_, W, W, W, W, W, W, W, W, W, W, W, W, W, W, _],
      [W, D, D, D, D, D, D, D, D, D, D, D, D, D, D, W],
      [W, D, R, R, B, B, G, G, Y, Y, R, R, B, B, D, W],
      [W, D, R, R, B, B, G, G, Y, Y, R, R, B, B, D, W],
      [W, D, R, R, B, B, G, G, Y, Y, R, R, B, B, D, W],
      [W, D, R, R, B, B, G, G, Y, Y, R, R, B, B, D, W],
      [W, D, R, R, B, B, G, G, Y, Y, R, R, B, B, D, W],
      [W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W],
      [W, D, D, D, D, D, D, D, D, D, D, D, D, D, D, W],
      [W, D, P, P, Y, Y, B, B, G, G, P, P, R, R, D, W],
      [W, D, P, P, Y, Y, B, B, G, G, P, P, R, R, D, W],
      [W, D, P, P, Y, Y, B, B, G, G, P, P, R, R, D, W],
      [W, D, P, P, Y, Y, B, B, G, G, P, P, R, R, D, W],
      [W, D, P, P, Y, Y, B, B, G, G, P, P, R, R, D, W],
      [W, D, P, P, Y, Y, B, B, G, G, P, P, R, R, D, W],
      [W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W],
      [W, D, D, D, D, D, D, D, D, D, D, D, D, D, D, W],
      [W, D, G, G, R, R, P, P, B, B, Y, Y, G, G, D, W],
      [W, D, G, G, R, R, P, P, B, B, Y, Y, G, G, D, W],
      [W, D, G, G, R, R, P, P, B, B, Y, Y, G, G, D, W],
      [W, D, G, G, R, R, P, P, B, B, Y, Y, G, G, D, W],
      [W, D, G, G, R, R, P, P, B, B, Y, Y, G, G, D, W],
      [W, D, G, G, R, R, P, P, B, B, Y, Y, G, G, D, W],
      [W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W],
      [W, D, D, D, D, D, D, D, D, D, D, D, D, D, D, W],
      [W, D, D, D, D, D, D, D, D, D, D, D, D, D, D, W],
      [W, D, D, D, D, D, D, D, D, D, D, D, D, D, D, W],
      [W, D, D, D, D, D, D, D, D, D, D, D, D, D, D, W],
      [W, D, D, D, D, D, D, D, D, D, D, D, D, D, D, W],
      [W, D, D, D, D, D, D, D, D, D, D, D, D, D, D, W],
      [W, W, W, W, W, W, W, W, W, W, W, W, W, W, W, W],
      [_, W, W, W, W, W, W, W, W, W, W, W, W, W, W, _],
    ];
  })(),
  2
);

// ---- HSL Color Shift (for team-coloring furniture) ----

function hexToHsl(hex) {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / d + 2) / 6;
    else h = ((r - g) / d + 4) / 6;
  }
  return [h * 360, s * 100, l * 100];
}

function hslToHex(h, s, l) {
  h /= 360; s /= 100; l /= 100;
  let r, g, b;
  if (s === 0) { r = g = b = l; }
  else {
    const hue2rgb = (p, q, t) => {
      if (t < 0) t += 1; if (t > 1) t -= 1;
      if (t < 1/6) return p + (q - p) * 6 * t;
      if (t < 1/2) return q;
      if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
      return p;
    };
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1/3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1/3);
  }
  const toHex = (v) => Math.round(v * 255).toString(16).padStart(2, "0");
  return "#" + toHex(r) + toHex(g) + toHex(b);
}

/**
 * Shift hue of all pixels in a sprite by `degrees`.
 * Used to team-colorize furniture (like AgentRoom's adjustSprite).
 */
export function hueShiftSprite(sprite, degrees) {
  return sprite.map((row) =>
    row.map((px) => {
      if (!px) return px;
      const [h, s, l] = hexToHsl(px);
      return hslToHex((h + degrees) % 360, s, l);
    })
  );
}

// ---- Department-specific decoration sprites ----

// Whiteboard (Research) — 16x16 base, 2x
export const WHITEBOARD_SPRITE = upscaleSprite(
  (() => {
    const F = "#c0c0c0", B = "#888888", W = "#f0f0f0", M = "#333333";
    return [
      [_, M, M, M, M, M, M, M, M, M, M, M, M, M, M, _],
      [M, F, F, F, F, F, F, F, F, F, F, F, F, F, F, M],
      [M, F, W, W, W, W, W, W, W, W, W, W, W, W, F, M],
      [M, F, W, W, W, W, W, W, W, W, W, W, W, W, F, M],
      [M, F, W, W, "#00aaff", W, W, W, W, W, W, W, W, W, F, M],
      [M, F, W, W, "#00aaff", "#00aaff", W, W, W, "#ff4444", "#ff4444", W, W, W, F, M],
      [M, F, W, W, "#00aaff", W, "#00aaff", W, "#ff4444", W, W, "#ff4444", W, W, F, M],
      [M, F, W, W, W, W, W, W, W, W, W, W, W, W, F, M],
      [M, F, W, W, W, "#44cc44", "#44cc44", "#44cc44", "#44cc44", W, W, W, W, W, F, M],
      [M, F, W, W, W, W, W, W, W, W, W, W, W, W, F, M],
      [M, F, F, F, F, F, F, F, F, F, F, F, F, F, F, M],
      [_, M, M, M, M, M, M, M, M, M, M, M, M, M, M, _],
      [_, _, _, _, _, _, M, _, _, M, _, _, _, _, _, _],
      [_, _, _, _, _, _, M, _, _, M, _, _, _, _, _, _],
      [_, _, _, _, _, _, M, _, _, M, _, _, _, _, _, _],
      [_, _, _, _, _, M, M, M, M, M, M, _, _, _, _, _],
    ];
  })(),
  2
);

// Easel/Canvas (Design) — 16x20 base, 2x
export const EASEL_SPRITE = upscaleSprite(
  (() => {
    const W = "#8B6914", F = "#ddd", P = "#ff6ec7", L = "#9955cc", B = "#333";
    return [
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
      [_, _, _, B, B, B, B, B, B, B, B, B, B, _, _, _],
      [_, _, _, B, F, F, F, F, F, F, F, F, B, _, _, _],
      [_, _, _, B, F, F, P, P, F, F, F, F, B, _, _, _],
      [_, _, _, B, F, P, P, P, P, F, F, F, B, _, _, _],
      [_, _, _, B, F, P, P, L, P, P, F, F, B, _, _, _],
      [_, _, _, B, F, F, L, L, L, P, P, F, B, _, _, _],
      [_, _, _, B, F, F, F, L, L, L, F, F, B, _, _, _],
      [_, _, _, B, F, F, F, F, L, F, F, F, B, _, _, _],
      [_, _, _, B, F, F, F, F, F, F, F, F, B, _, _, _],
      [_, _, _, B, B, B, B, B, B, B, B, B, B, _, _, _],
      [_, _, _, _, _, _, B, _, B, _, _, _, _, _, _, _],
      [_, _, _, _, _, B, _, _, _, B, _, _, _, _, _, _],
      [_, _, _, _, B, _, _, _, _, _, B, _, _, _, _, _],
      [_, _, _, B, _, _, _, _, _, _, _, B, _, _, _, _],
      [_, _, B, _, _, _, _, _, _, _, _, _, B, _, _, _],
    ];
  })(),
  2
);

// Shipping Box (Commerce) — 16x14 base, 2x
export const BOX_SPRITE = upscaleSprite(
  (() => {
    const C = "#b87333", D = "#8B5A2B", T = "#d4a574", S = "#e8c8a0";
    return [
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
      [_, _, _, _, C, C, C, C, C, C, C, C, _, _, _, _],
      [_, _, _, C, C, C, C, C, C, C, C, C, C, _, _, _],
      [_, _, C, T, T, T, T, T, T, T, T, T, T, C, _, _],
      [_, _, C, T, S, S, S, T, T, S, S, S, T, C, _, _],
      [_, _, C, T, S, D, S, T, T, S, D, S, T, C, _, _],
      [_, _, C, T, S, S, S, T, T, S, S, S, T, C, _, _],
      [_, _, C, T, T, T, T, T, T, T, T, T, T, C, _, _],
      [_, _, C, T, T, T, T, T, T, T, T, T, T, C, _, _],
      [_, _, C, T, T, T, "#39ff14", "#39ff14", "#39ff14", T, T, T, T, C, _, _],
      [_, _, C, T, T, T, T, T, T, T, T, T, T, C, _, _],
      [_, _, C, C, C, C, C, C, C, C, C, C, C, C, _, _],
      [_, _, _, D, D, D, D, D, D, D, D, D, D, _, _, _],
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
    ];
  })(),
  2
);

// Trophy (Learning) — 16x18 base, 2x
export const TROPHY_SPRITE = upscaleSprite(
  (() => {
    const G = "#ffd700", D = "#b8960f", S = "#c0c0c0", B = "#8B6914";
    return [
      [_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _],
      [_, _, _, _, G, G, G, G, G, G, G, G, _, _, _, _],
      [_, _, _, G, G, D, D, D, D, D, D, G, G, _, _, _],
      [_, _, G, G, D, D, D, D, D, D, D, D, G, G, _, _],
      [_, _, G, G, D, D, D, D, D, D, D, D, G, G, _, _],
      [_, G, G, D, D, D, D, D, D, D, D, D, D, G, G, _],
      [_, G, G, D, D, D, D, D, D, D, D, D, D, G, G, _],
      [_, _, G, G, D, D, D, D, D, D, D, D, G, G, _, _],
      [_, _, G, G, D, D, D, D, D, D, D, D, G, G, _, _],
      [_, _, _, G, G, D, D, D, D, D, D, G, G, _, _, _],
      [_, _, _, _, G, G, G, G, G, G, G, G, _, _, _, _],
      [_, _, _, _, _, _, G, G, G, G, _, _, _, _, _, _],
      [_, _, _, _, _, _, G, D, D, G, _, _, _, _, _, _],
      [_, _, _, _, _, _, G, D, D, G, _, _, _, _, _, _],
      [_, _, _, _, _, S, S, S, S, S, S, _, _, _, _, _],
      [_, _, _, _, S, B, B, B, B, B, B, S, _, _, _, _],
      [_, _, _, S, B, B, B, B, B, B, B, B, S, _, _, _],
      [_, _, _, S, S, S, S, S, S, S, S, S, S, _, _, _],
    ];
  })(),
  2
);
