/**
 * Video Export — Record the canvas to a shareable WebM/MP4 video.
 *
 * Uses the browser-native MediaRecorder API with canvas.captureStream().
 * No server-side processing or FFmpeg required.
 */

let recording = false;
let mediaRecorder = null;
let chunks = [];
let recordBtn = null;
let startTime = 0;
let durationInterval = null;

export function init() {
  recordBtn = document.getElementById("replay-record");
}

/**
 * Check if MediaRecorder is available in this browser.
 */
export function isSupported() {
  return typeof MediaRecorder !== "undefined" && typeof HTMLCanvasElement.prototype.captureStream === "function";
}

/**
 * Start recording the canvas.
 * @param {HTMLCanvasElement} canvas - The canvas element to record
 * @param {object} [opts] - Recording options
 * @param {number} [opts.fps=30] - Frames per second
 * @param {number} [opts.videoBitsPerSecond=5000000] - Video bitrate (5Mbps default)
 */
export function startRecording(canvas, opts = {}) {
  if (recording) return;
  if (!isSupported()) {
    console.warn("[VideoExport] MediaRecorder not supported in this browser");
    return;
  }

  const fps = opts.fps || 30;
  const stream = canvas.captureStream(fps);

  // Try preferred codecs in order
  const codecs = [
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
  ];

  let mimeType = "";
  for (const codec of codecs) {
    if (MediaRecorder.isTypeSupported(codec)) {
      mimeType = codec;
      break;
    }
  }

  if (!mimeType) {
    console.error("[VideoExport] No supported video codec found");
    return;
  }

  chunks = [];
  mediaRecorder = new MediaRecorder(stream, {
    mimeType,
    videoBitsPerSecond: opts.videoBitsPerSecond || 5_000_000,
  });

  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) chunks.push(e.data);
  };

  mediaRecorder.onstop = () => {
    _finalize();
  };

  mediaRecorder.onerror = (e) => {
    console.error("[VideoExport] Recording error:", e.error);
    stopRecording();
  };

  mediaRecorder.start(100); // Collect data every 100ms
  recording = true;
  startTime = Date.now();

  // Update UI
  if (recordBtn) {
    recordBtn.classList.add("replay-btn--recording");
    recordBtn.innerHTML = "&#x23F9; STOP";
  }

  // Duration counter
  durationInterval = setInterval(_updateDuration, 1000);

  console.log(`[VideoExport] Recording started (${mimeType}, ${fps}fps)`);
}

/**
 * Stop recording and trigger download.
 */
export function stopRecording() {
  if (!recording || !mediaRecorder) return;

  mediaRecorder.stop();
  recording = false;

  if (durationInterval) {
    clearInterval(durationInterval);
    durationInterval = null;
  }

  // Reset UI
  if (recordBtn) {
    recordBtn.classList.remove("replay-btn--recording");
    recordBtn.innerHTML = "&#x23FA; REC";
  }
}

/**
 * Toggle recording on/off.
 * @param {HTMLCanvasElement} canvas
 */
export function toggleRecording(canvas) {
  if (recording) {
    stopRecording();
  } else {
    startRecording(canvas);
  }
}

export function isRecording() {
  return recording;
}

// ---- Internal ----

function _finalize() {
  if (!chunks.length) {
    console.warn("[VideoExport] No data recorded");
    return;
  }

  const blob = new Blob(chunks, { type: mediaRecorder.mimeType || "video/webm" });
  const url = URL.createObjectURL(blob);

  // Trigger download
  const a = document.createElement("a");
  a.href = url;
  a.download = `pixelpulse-replay-${Date.now()}.webm`;
  a.click();

  // Cleanup after a delay
  setTimeout(() => URL.revokeObjectURL(url), 60_000);

  const sizeMB = (blob.size / (1024 * 1024)).toFixed(1);
  const durationSec = ((Date.now() - startTime) / 1000).toFixed(1);
  console.log(`[VideoExport] Saved ${sizeMB}MB video (${durationSec}s)`);

  chunks = [];
  mediaRecorder = null;
}

function _updateDuration() {
  if (!recording || !recordBtn) return;
  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  const min = Math.floor(elapsed / 60);
  const sec = elapsed % 60;
  recordBtn.innerHTML = `&#x23F9; ${min}:${sec.toString().padStart(2, "0")}`;
}
