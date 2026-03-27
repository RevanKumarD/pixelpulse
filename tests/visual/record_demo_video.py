"""Record demo videos of the PixelPulse dashboard with multiple scenarios.

Starts a real server for each scenario, runs demo mode, captures via
Playwright's built-in video recording, then concatenates clips into a
single video and converts to GIF.

Usage:
    python tests/visual/record_demo_video.py              # all scenarios
    python tests/visual/record_demo_video.py --scenario 0  # single scenario

Output:
    tests/visual/demo.gif    — optimized looping GIF for the README
    tests/visual/demo.webm   — combined video (all scenarios)
    tests/visual/clips/      — individual scenario clips

Requirements:
    pip install pixelpulse playwright httpx
    playwright install chromium
    ffmpeg must be on PATH (choco install ffmpeg on Windows)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

VISUAL_DIR = Path(__file__).parent
CLIPS_DIR = VISUAL_DIR / "clips"
OUTPUT_GIF = VISUAL_DIR / "demo.gif"
OUTPUT_WEBM = VISUAL_DIR / "demo.webm"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("video-recorder")

BASE_PORT = 8798

# ─── Demo Scenarios ──────────────────────────────────────────────
# Each scenario represents a different company/use-case to show
# PixelPulse works with ANY multi-agent setup.

SCENARIOS = [
    {
        "name": "Software Dev Team",
        "title": "DevFlow AI — Engineering Copilots",
        "agents": {
            "code-planner":     {"team": "planning",  "role": "Plans implementation"},
            "architect":        {"team": "planning",  "role": "Designs system architecture"},
            "backend-coder":    {"team": "engineering", "role": "Writes backend code"},
            "frontend-coder":   {"team": "engineering", "role": "Writes frontend UI"},
            "test-writer":      {"team": "engineering", "role": "Writes automated tests"},
            "code-reviewer":    {"team": "qa",         "role": "Reviews code quality"},
            "security-scanner": {"team": "qa",         "role": "Scans for vulnerabilities"},
            "deploy-agent":     {"team": "ops",        "role": "Manages deployments"},
            "monitor-agent":    {"team": "ops",        "role": "Watches production health"},
        },
        "teams": {
            "planning":    {"label": "Planning",    "role": "Architecture & task breakdown"},
            "engineering": {"label": "Engineering", "role": "Code generation & testing"},
            "qa":          {"label": "QA",          "role": "Review & security"},
            "ops":         {"label": "DevOps",      "role": "Deploy & monitor"},
        },
        "pipeline": ["planning", "engineering", "qa", "ops"],
        "duration": 35,
    },
    {
        "name": "Creative Agency",
        "title": "Prism Studio — Content Pipeline",
        "agents": {
            "trend-scout":     {"team": "research",   "role": "Discovers trending topics"},
            "audience-mapper":  {"team": "research",   "role": "Maps audience segments"},
            "script-writer":   {"team": "content",    "role": "Writes scripts & copy"},
            "visual-designer": {"team": "content",    "role": "Creates visual assets"},
            "video-editor":    {"team": "content",    "role": "Edits video content"},
            "brand-checker":   {"team": "review",     "role": "Ensures brand consistency"},
            "seo-optimizer":   {"team": "review",     "role": "Optimizes for search"},
            "scheduler":       {"team": "publishing", "role": "Schedules publications"},
            "analytics-bot":   {"team": "publishing", "role": "Tracks performance"},
        },
        "teams": {
            "research":   {"label": "Research",   "role": "Trends & audience insights"},
            "content":    {"label": "Content",    "role": "Scripts, visuals & video"},
            "review":     {"label": "Review",     "role": "Brand & SEO checks"},
            "publishing": {"label": "Publishing", "role": "Schedule & analytics"},
        },
        "pipeline": ["research", "content", "review", "publishing"],
        "duration": 35,
    },
    {
        "name": "Data Science Lab",
        "title": "DataPilot — ML Pipeline",
        "agents": {
            "data-scout":      {"team": "ingestion", "role": "Finds data sources"},
            "data-cleaner":    {"team": "ingestion", "role": "Cleans & validates data"},
            "feature-builder": {"team": "modeling",  "role": "Engineers features"},
            "model-trainer":   {"team": "modeling",  "role": "Trains ML models"},
            "evaluator":       {"team": "modeling",  "role": "Evaluates model performance"},
            "report-writer":   {"team": "delivery",  "role": "Writes analysis reports"},
            "dashboard-gen":   {"team": "delivery",  "role": "Generates dashboards"},
        },
        "teams": {
            "ingestion": {"label": "Ingestion", "role": "Data sourcing & cleaning"},
            "modeling":  {"label": "Modeling",  "role": "Feature engineering & training"},
            "delivery":  {"label": "Delivery",  "role": "Reports & dashboards"},
        },
        "pipeline": ["ingestion", "modeling", "delivery"],
        "duration": 30,
    },
]


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
            time.sleep(0.5)
    raise RuntimeError(f"Server failed to start on port {port}")


async def _record_scenario(port: int, duration: int, output_path: Path) -> Path:
    """Record a single scenario. Returns path to the .webm file."""
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

            # Click Demo button
            demo_btn = page.locator("button:has-text('Demo'), button[title*='Demo']")
            if await demo_btn.count() > 0:
                await demo_btn.first.click()
                log.info("Demo mode started")
            else:
                await page.keyboard.press("d")

            await page.wait_for_timeout(1500)

            log.info("Recording for %d seconds...", duration)
            await page.wait_for_timeout(duration * 1000)

            video_path_in_page = await page.video.path()
            await context.close()
            await browser.close()

            if console_errors:
                log.warning("Console errors: %s", console_errors[:5])

        src = Path(video_path_in_page)
        if src.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, output_path)
            log.info("Clip saved: %s (%.1f MB)", output_path, output_path.stat().st_size / 1_048_576)
            return output_path
        else:
            for f in Path(video_dir).glob("*.webm"):
                shutil.copy(f, output_path)
                return output_path
            raise FileNotFoundError("Playwright did not produce a video file")


def _concat_clips(clips: list[Path], output: Path) -> None:
    """Concatenate multiple WebM clips into a single video using ffmpeg."""
    if not shutil.which("ffmpeg"):
        log.error("ffmpeg not found — skipping concat")
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")
        list_file = f.name

    try:
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", str(output),
        ], check=True, capture_output=True)
        log.info("Combined video: %s (%.1f MB)", output, output.stat().st_size / 1_048_576)
    finally:
        Path(list_file).unlink(missing_ok=True)


def _webm_to_gif(webm: Path, gif: Path) -> None:
    """Convert WebM to optimized looping GIF using ffmpeg palette trick."""
    if not shutil.which("ffmpeg"):
        log.error("ffmpeg not found on PATH — skipping GIF conversion")
        return

    with tempfile.TemporaryDirectory() as tmp:
        palette = Path(tmp) / "palette.png"

        log.info("Generating palette...")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(webm),
            "-vf", "fps=8,scale=900:-1:flags=lanczos,palettegen=max_colors=96",
            str(palette),
        ], check=True, capture_output=True)

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
        log.warning("GIF is %.1f MB — over GitHub's 10 MB inline limit", size_mb)


async def main(scenario_idx: int | None = None) -> None:
    from pixelpulse import PixelPulse

    scenarios = [SCENARIOS[scenario_idx]] if scenario_idx is not None else SCENARIOS
    clips = []

    for i, scenario in enumerate(scenarios):
        log.info("=" * 60)
        log.info("Scenario %d: %s", i, scenario["name"])
        log.info("=" * 60)

        port = BASE_PORT + i
        pp = PixelPulse(
            agents=scenario["agents"],
            teams=scenario["teams"],
            pipeline=scenario["pipeline"],
            title=scenario["title"],
            port=port,
        )

        _start_server(pp, port)

        clip_path = CLIPS_DIR / f"clip_{i:02d}_{scenario['name'].lower().replace(' ', '_')}.webm"
        await _record_scenario(port, scenario["duration"], clip_path)
        clips.append(clip_path)

    if len(clips) > 1:
        _concat_clips(clips, OUTPUT_WEBM)
    elif len(clips) == 1:
        shutil.copy(clips[0], OUTPUT_WEBM)

    _webm_to_gif(OUTPUT_WEBM, OUTPUT_GIF)

    log.info("=" * 60)
    log.info("Done. Files:")
    log.info("  WebM: %s", OUTPUT_WEBM)
    if OUTPUT_GIF.exists():
        log.info("  GIF:  %s (%.1f MB)", OUTPUT_GIF, OUTPUT_GIF.stat().st_size / 1_048_576)
    log.info("  Clips: %s", [str(c) for c in clips])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record PixelPulse demo videos")
    parser.add_argument("--scenario", type=int, default=None, help="Record a single scenario (0-based index)")
    args = parser.parse_args()
    asyncio.run(main(args.scenario))
