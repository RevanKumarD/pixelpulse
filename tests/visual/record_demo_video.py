"""Record a demo-mode video of the PixelPulse dashboard.

Starts a real server, runs demo mode for 40 seconds, captures via
Playwright's built-in video recording, then converts WebM → GIF.

Usage:
    python tests/visual/record_demo_video.py

Output:
    tests/visual/demo.gif    — optimized looping GIF for the README
    tests/visual/demo.webm   — raw Playwright recording (kept for reference)

Requirements:
    pip install pixelpulse playwright
    playwright install chromium
    ffmpeg must be on PATH (choco install ffmpeg on Windows)
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import httpx
import uvicorn

VISUAL_DIR = Path(__file__).parent
OUTPUT_GIF = VISUAL_DIR / "demo.gif"
OUTPUT_WEBM = VISUAL_DIR / "demo.webm"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("video-recorder")

PORT = 8798  # separate port from screenshot tests


def _start_server(pp, port: int) -> threading.Thread:
    app = pp._create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    for _ in range(30):
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1)
            if r.status_code == 200:
                log.info("Server ready on port %d", port)
                return t
        except Exception:
            import time
            time.sleep(0.5)
    raise RuntimeError(f"Server failed to start on port {port}")


async def _record(port: int) -> Path:
    """Record the dashboard in demo mode. Returns path to the .webm file."""
    from playwright.async_api import async_playwright

    with tempfile.TemporaryDirectory() as video_dir:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1400, "height": 900},
                record_video_dir=video_dir,
                record_video_size={"width": 1400, "height": 900},
            )
            page = await context.new_page()

            console_errors = []
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: log.error("PAGE ERROR: %s", e))

            log.info("Loading dashboard...")
            await page.goto(f"http://127.0.0.1:{port}")
            await page.wait_for_timeout(2000)

            # Click Demo button to start demo mode
            demo_btn = page.locator("button:has-text('Demo'), button[title*='Demo'], button[title*='demo']")
            if await demo_btn.count() > 0:
                await demo_btn.first.click()
                log.info("Demo mode started")
            else:
                # Demo might auto-start or have a different label — try keyboard shortcut
                await page.keyboard.press("d")
                log.info("Sent 'd' to start demo")

            await page.wait_for_timeout(1500)

            # Record for 38 seconds — enough for 1–2 full pipeline cycles at 3500ms/tick
            log.info("Recording demo mode for 38 seconds...")
            await page.wait_for_timeout(38000)

            # Close context to flush the video file
            video_path_in_page = await page.video.path()
            await context.close()
            await browser.close()

            if console_errors:
                log.warning("Console errors during recording: %s", console_errors[:5])

        # Copy out of temp dir before it's deleted
        src = Path(video_path_in_page)
        if src.exists():
            OUTPUT_WEBM.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, OUTPUT_WEBM)
            log.info("WebM saved to %s (%.1f MB)", OUTPUT_WEBM, OUTPUT_WEBM.stat().st_size / 1_048_576)
            return OUTPUT_WEBM
        else:
            log.error("Video file not found at %s", src)
            # Try finding any webm in temp dir
            for f in Path(video_dir).glob("*.webm"):
                shutil.copy(f, OUTPUT_WEBM)
                log.info("Found video at %s → %s", f, OUTPUT_WEBM)
                return OUTPUT_WEBM
            raise FileNotFoundError("Playwright did not produce a video file")


def _webm_to_gif(webm: Path, gif: Path) -> None:
    """Convert WebM to optimized looping GIF using ffmpeg palette trick."""
    if not shutil.which("ffmpeg"):
        log.error("ffmpeg not found on PATH — skipping GIF conversion")
        log.error("Install with: choco install ffmpeg  (Windows)")
        return

    with tempfile.TemporaryDirectory() as tmp:
        palette = Path(tmp) / "palette.png"

        # Pass 1: generate optimal palette (much sharper than direct conversion)
        # fps=8, scale=900 keeps file under GitHub's 10 MB inline-display limit
        log.info("Generating palette...")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(webm),
            "-vf", "fps=8,scale=900:-1:flags=lanczos,palettegen=max_colors=96",
            str(palette),
        ], check=True, capture_output=True)

        # Pass 2: render GIF using palette
        log.info("Rendering GIF...")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(webm),
            "-i", str(palette),
            "-filter_complex", "fps=8,scale=900:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer",
            str(gif),
        ], check=True, capture_output=True)

    size_mb = gif.stat().st_size / 1_048_576
    log.info("GIF saved to %s (%.1f MB)", gif, size_mb)
    if size_mb > 10:
        log.warning("GIF is %.1f MB — over GitHub's 10 MB inline limit, reduce fps or scale", size_mb)


async def main() -> None:
    from pixelpulse import PixelPulse

    pp = PixelPulse(
        agents={
            "data-collector":   {"team": "research",  "role": "Collects raw data"},
            "data-analyzer":    {"team": "research",  "role": "Analyzes data patterns"},
            "insight-builder":  {"team": "research",  "role": "Builds insights from data"},
            "brief-expander":   {"team": "design",    "role": "Expands concept briefs"},
            "image-generator":  {"team": "design",    "role": "Generates product images"},
            "design-reviewer":  {"team": "design",    "role": "Reviews design quality"},
            "listing-writer":   {"team": "commerce",  "role": "Writes product listings"},
            "market-localizer": {"team": "commerce",  "role": "Localizes for markets"},
            "feedback-analyst": {"team": "learning",  "role": "Reviews and learns"},
        },
        teams={
            "research": {"label": "Research Lab",    "role": "Signal discovery & analysis"},
            "design":   {"label": "Design Studio",   "role": "Visual asset creation"},
            "commerce": {"label": "Commerce Hub",    "role": "Listing & localization"},
            "learning": {"label": "Learning Center", "role": "Feedback & improvement"},
        },
        pipeline=["research", "design", "commerce", "learning"],
        title="PixelPulse — Agent Dashboard",
        port=PORT,
    )

    _start_server(pp, PORT)

    webm = await _record(PORT)
    _webm_to_gif(webm, OUTPUT_GIF)

    log.info("=" * 60)
    log.info("Done. Files:")
    log.info("  WebM: %s", webm)
    if OUTPUT_GIF.exists():
        log.info("  GIF:  %s (%.1f MB)", OUTPUT_GIF, OUTPUT_GIF.stat().st_size / 1_048_576)


if __name__ == "__main__":
    asyncio.run(main())
