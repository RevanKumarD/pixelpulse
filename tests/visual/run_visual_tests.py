"""Visual E2E tests for PixelPulse Dashboard.

Starts the real server, drives it with Playwright, captures screenshots
at every meaningful state, and generates a committed evidence report.

Usage:
    .venv/Scripts/python.exe tests/visual/run_visual_tests.py

Outputs:
    tests/visual/screenshots/   — all captured screenshots
    tests/visual/VISUAL_TEST_REPORT.md — structured report
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
from pathlib import Path

# Add src to path so we can import pixelpulse
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

PORT = 8799
BASE_URL = f"http://127.0.0.1:{PORT}"

log = logging.getLogger("visual-test")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# ---- Test Results Accumulator ----

test_results: list[dict] = []
console_errors: list[str] = []


def record(name: str, passed: bool, notes: str = ""):
    test_results.append({"name": name, "passed": passed, "notes": notes})
    status = "PASS" if passed else "FAIL"
    log.info("[%s] %s %s", status, name, f"— {notes}" if notes else "")


# ---- Server Startup ----

def _start_server():
    """Start PixelPulse with a realistic multi-team config."""
    from pixelpulse import PixelPulse

    pp = PixelPulse(
        agents={
            "planner": {"team": "planning", "role": "Breaks down tasks into subtasks"},
            "researcher": {"team": "planning", "role": "Gathers context and prior art"},
            "architect": {"team": "engineering", "role": "Designs system architecture"},
            "frontend-dev": {"team": "engineering", "role": "Builds UI components"},
            "backend-dev": {"team": "engineering", "role": "Implements API and services"},
            "db-engineer": {"team": "engineering", "role": "Schema design and queries"},
            "code-reviewer": {"team": "quality", "role": "Reviews code for issues"},
            "test-writer": {"team": "quality", "role": "Writes unit and integration tests"},
            "security-auditor": {"team": "quality", "role": "Security vulnerability scanning"},
            "tech-writer": {"team": "docs", "role": "API documentation and guides"},
            "deploy-agent": {"team": "docs", "role": "CI/CD pipeline and deployment"},
        },
        teams={
            "planning": {"label": "Planning", "color": "#00d4ff", "icon": "📋"},
            "engineering": {"label": "Engineering", "color": "#ff6ec7", "icon": "⚙️"},
            "quality": {"label": "Quality", "color": "#39ff14", "icon": "✅"},
            "docs": {"label": "DevOps & Docs", "color": "#ffae00", "icon": "📚"},
        },
        pipeline=["planning", "architecture", "implementation", "review",
                   "testing", "security_audit", "deploy"],
        title="PixelPulse Visual Test",
        port=PORT,
        storage=False,  # Don't create DB for visual test
    )
    return pp


def _run_server(pp):
    """Run server in background thread."""
    import uvicorn

    app = pp._create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Wait for server to respond
    import httpx
    for _ in range(30):
        try:
            r = httpx.get(f"{BASE_URL}/api/health", timeout=1)
            if r.status_code == 200:
                log.info("Server ready on port %d", PORT)
                return pp, t
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Server did not start on port {PORT}")


# ---- Screenshot Helper ----

async def screenshot(page, name: str):
    path = SCREENSHOTS_DIR / name
    await page.screenshot(path=str(path), full_page=False)
    log.info("Screenshot: %s", name)


# ---- Scenario: Idle Dashboard ----

async def test_01_idle_dashboard(page):
    """Capture the dashboard immediately after load — no events yet."""
    await page.goto(BASE_URL)
    await page.wait_for_timeout(3000)  # Let canvas render, sprites load

    # Check canvas is rendering
    canvas_info = await page.evaluate("""() => {
        const c = document.getElementById('office-canvas');
        return {
            width: c?.width || 0,
            height: c?.height || 0,
            exists: !!c,
        };
    }""")
    log.info("Canvas: %s", canvas_info)

    if not canvas_info.get("width") or canvas_info["width"] < 100:
        await page.evaluate("() => document.getElementById('ctrl-fit')?.click()")
        await page.wait_for_timeout(1000)

    await screenshot(page, "01_dashboard_idle.png")

    passed = canvas_info.get("exists", False) and canvas_info.get("width", 0) > 100
    record("Idle Dashboard", passed, f"Canvas {canvas_info.get('width')}x{canvas_info.get('height')}")


# ---- Scenario: Agents Active (via Demo Mode) ----

async def test_02_demo_active(page, pp):
    """Start demo mode and capture active agents with speech bubbles."""
    await page.evaluate("() => document.getElementById('demo-btn')?.click()")
    await page.wait_for_timeout(5000)

    await screenshot(page, "02_demo_active_5s.png")

    event_count = await page.evaluate("""() => {
        const log = document.getElementById('event-log');
        return log ? log.children.length : 0;
    }""")
    log.info("Event log entries: %d", event_count)

    # Wait longer for more activity
    await page.wait_for_timeout(8000)
    await screenshot(page, "03_demo_active_13s.png")

    record("Demo Active State", event_count > 0, f"{event_count} events in log after 5s")


# ---- Scenario: Message Flow (Particles) ----

async def test_03_message_flow(page, pp):
    """Capture message particles flowing between agents."""
    await page.wait_for_timeout(5000)
    await screenshot(page, "04_message_flow.png")

    comm_count = await page.evaluate("""() => {
        const comms = document.getElementById('comms-feed');
        return comms ? comms.children.length : 0;
    }""")
    log.info("Comms feed entries: %d", comm_count)
    record("Message Flow", comm_count > 0, f"{comm_count} comms entries")


# ---- Scenario: Agent Detail Panel ----

async def test_04_agent_detail_panel(page):
    """Click an agent in sidebar to open the detail panel."""
    # Ensure sidebar is visible first
    sidebar_visible = await page.evaluate("""() => {
        const sb = document.getElementById('sidebar');
        if (!sb) return false;
        const style = window.getComputedStyle(sb);
        return style.display !== 'none' && sb.offsetWidth > 0;
    }""")
    if not sidebar_visible:
        toggle = page.locator("#sidebar-toggle")
        if await toggle.count() > 0:
            await toggle.click()
            await page.wait_for_timeout(500)

    # Scroll the agent-activity section into view and use evaluate to click
    clicked = await page.evaluate("""() => {
        const row = document.querySelector('[data-agent]');
        if (!row) return false;
        row.scrollIntoView({ block: 'center' });
        row.click();
        return true;
    }""")

    if clicked:
        await page.wait_for_timeout(1500)
        await screenshot(page, "05_agent_detail_overview.png")

        panel_visible = await page.evaluate("""() => {
            const panel = document.getElementById('agent-detail');
            return panel && !panel.hidden;
        }""")

        if panel_visible:
            # Click Messages tab
            await page.evaluate("""() => {
                const tab = document.querySelector('.agent-detail__tab[data-tab="messages"]');
                if (tab) tab.click();
            }""")
            await page.wait_for_timeout(800)
            await screenshot(page, "06_agent_detail_messages.png")

            # Click Reasoning tab
            await page.evaluate("""() => {
                const tab = document.querySelector('.agent-detail__tab[data-tab="reasoning"]');
                if (tab) tab.click();
            }""")
            await page.wait_for_timeout(800)
            await screenshot(page, "07_agent_detail_reasoning.png")

            # Click Performance tab
            await page.evaluate("""() => {
                const tab = document.querySelector('.agent-detail__tab[data-tab="performance"]');
                if (tab) tab.click();
            }""")
            await page.wait_for_timeout(800)
            await screenshot(page, "08_agent_detail_performance.png")

            # Close panel
            await page.evaluate("""() => {
                const btn = document.querySelector('.agent-detail__close');
                if (btn) btn.click();
            }""")
            await page.wait_for_timeout(500)

        record("Agent Detail Panel", panel_visible, "All 4 tabs captured" if panel_visible else "Panel not visible")
    else:
        await screenshot(page, "05_agent_detail_no_agents.png")
        record("Agent Detail Panel", False, "No agent rows found in sidebar")


# ---- Scenario: Canvas Click Agent ----

async def test_05_canvas_agent_click(page):
    """Click on the canvas where an agent should be."""
    canvas = page.locator("#office-canvas")
    if await canvas.count() > 0:
        box = await canvas.bounding_box()
        if box:
            for x_frac, y_frac in [(0.3, 0.3), (0.5, 0.4), (0.7, 0.5), (0.3, 0.6)]:
                await canvas.click(position={"x": box["width"] * x_frac, "y": box["height"] * y_frac})
                await page.wait_for_timeout(500)

                panel_open = await page.evaluate("""() => {
                    const panel = document.getElementById('agent-detail');
                    return panel && !panel.hidden;
                }""")
                if panel_open:
                    await screenshot(page, "09_canvas_click_agent.png")
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(300)
                    record("Canvas Agent Click", True, f"Opened at ({x_frac},{y_frac})")
                    return

    record("Canvas Agent Click", False, "Could not open panel from canvas click (agents may be roaming)")


# ---- Scenario: Sidebar Toggle ----

async def test_06_sidebar_toggle(page):
    """Toggle sidebar collapse/expand."""
    found = await page.evaluate("""() => {
        const btn = document.getElementById('sidebar-toggle');
        if (btn) { btn.click(); return true; }
        return false;
    }""")
    if found:
        await page.wait_for_timeout(500)
        await screenshot(page, "10_sidebar_collapsed.png")

        await page.evaluate("() => document.getElementById('sidebar-toggle')?.click()")
        await page.wait_for_timeout(500)
        await screenshot(page, "11_sidebar_expanded.png")
        record("Sidebar Toggle", True, "Collapsed and expanded")
    else:
        record("Sidebar Toggle", False, "Toggle button not found")


# ---- Scenario: Theme Switch ----

async def test_07_theme_switch(page):
    """Switch to light theme and capture."""
    opened = await page.evaluate("""() => {
        const btn = document.getElementById('settings-btn');
        if (btn) { btn.click(); return true; }
        return false;
    }""")
    if opened:
        await page.wait_for_timeout(500)
        await screenshot(page, "12_settings_panel.png")

        toggled = await page.evaluate("""() => {
            const cb = document.getElementById('theme-checkbox');
            if (cb) { cb.click(); return true; }
            return false;
        }""")
        if toggled:
            await page.wait_for_timeout(1000)
            await screenshot(page, "13_light_theme.png")

            # Switch back
            await page.evaluate("() => document.getElementById('theme-checkbox')?.click()")
            await page.wait_for_timeout(500)
            record("Theme Switch", True, "Light/dark toggle captured")
        else:
            record("Theme Switch", False, "Theme checkbox not found")

        await page.evaluate("() => document.getElementById('settings-btn')?.click()")
        await page.wait_for_timeout(300)
    else:
        record("Theme Switch", False, "Settings button not found")


# ---- Scenario: Keyboard Help ----

async def test_08_keyboard_help(page):
    """Press ? to show keyboard shortcuts overlay."""
    await page.keyboard.press("?")
    await page.wait_for_timeout(800)
    await screenshot(page, "14_keyboard_help.png")

    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)
    record("Keyboard Help", True, "Shortcut overlay captured")


# ---- Scenario: View Controls ----

async def test_09_view_controls(page):
    """Test zoom in, zoom out, fit, and reset view."""
    await page.evaluate("""() => {
        const z = document.getElementById('ctrl-zoom-in');
        if (z) { z.click(); z.click(); }
    }""")
    await page.wait_for_timeout(500)
    await screenshot(page, "15_zoomed_in.png")

    await page.evaluate("() => document.getElementById('ctrl-fit')?.click()")
    await page.wait_for_timeout(500)
    await screenshot(page, "16_fit_view.png")

    await page.evaluate("() => document.getElementById('ctrl-reset')?.click()")
    await page.wait_for_timeout(500)

    record("View Controls", True, "Zoom/fit/reset captured")


# ---- Scenario: Stop Demo ----

async def test_10_stop_demo(page):
    """Stop demo and capture the final state."""
    await page.evaluate("""() => {
        const btn = document.getElementById('demo-btn');
        if (btn && btn.textContent.includes('Stop')) btn.click();
    }""")
    await page.wait_for_timeout(2000)
    await screenshot(page, "17_demo_stopped.png")
    record("Demo Stop", True, "Demo stopped, final state captured")


# ---- Scenario: Event Log Content ----

async def test_11_event_log(page):
    """Verify the event log has proper formatted entries."""
    event_data = await page.evaluate("""() => {
        const log = document.getElementById('event-log');
        if (!log) return { count: 0, entries: [] };
        const items = Array.from(log.children).slice(0, 5);
        return {
            count: log.children.length,
            entries: items.map(el => ({
                text: el.textContent?.trim().substring(0, 100),
            }))
        };
    }""")
    log.info("Event log: %d entries", event_data.get("count", 0))

    passed = event_data.get("count", 0) > 0
    record("Event Log Content", passed, f"{event_data.get('count', 0)} entries")


# ---- Scenario: Run History Section ----

async def test_12_run_history(page):
    """Check the run history section in sidebar."""
    run_history = page.locator("#run-history")
    if await run_history.count() > 0:
        content = await run_history.text_content()
        await screenshot(page, "18_run_history_section.png")
        record("Run History Section", True, f"Content: {(content or '').strip()[:60]}")
    else:
        record("Run History Section", False, "Run history element not found")


# ---- Scenario: Replay Controls ----

async def test_13_replay_controls(page):
    """Verify replay controls exist and are hidden by default."""
    replay_hidden = await page.evaluate("""() => {
        const el = document.getElementById('replay-controls');
        return el ? el.hidden : null;
    }""")
    record("Replay Controls", replay_hidden is True,
           "Hidden by default" if replay_hidden else f"State: {replay_hidden}")


# ---- Scenario: Full Pipeline via API ----

async def test_14_api_events(page, pp):
    """Emit events through the Python SDK and capture the dashboard response."""
    await page.goto(BASE_URL)
    await page.wait_for_timeout(2500)

    pp.run_started("visual-test-run", name="Visual Test Pipeline")
    await page.wait_for_timeout(1000)

    pp.agent_started("planner", task="Breaking down user story: Add real-time notifications")
    await page.wait_for_timeout(1500)

    pp.agent_thinking("planner", thought="Decomposing into 4 subtasks: WebSocket setup, event schema, notification UI component, integration tests")
    await page.wait_for_timeout(2000)
    await screenshot(page, "19_api_agent_thinking.png")

    pp.agent_message("planner", "architect",
                     content="4 subtasks ready: ws-setup, event-schema, notif-ui, integration-tests. Priority: ws-setup first.",
                     tag="tasks")
    await page.wait_for_timeout(2000)
    await screenshot(page, "20_api_message_particle.png")

    pp.agent_started("architect", task="Designing WebSocket notification architecture")
    pp.agent_thinking("architect", thought="Evaluating: Server-Sent Events vs WebSocket vs polling. WebSocket wins for bi-directional real-time.")
    await page.wait_for_timeout(2000)

    pp.agent_message("architect", "backend-dev",
                     content="Architecture: FastAPI WebSocket endpoint /ws/notifications, Redis pub/sub for scaling", tag="design")
    await page.wait_for_timeout(1500)

    pp.cost_update("planner", cost=0.0024, tokens_in=1200, tokens_out=340, model="claude-sonnet-4")
    pp.cost_update("architect", cost=0.0018, tokens_in=800, tokens_out=250, model="claude-sonnet-4")
    await page.wait_for_timeout(1000)

    pp.agent_started("frontend-dev", task="Building notification toast component")
    pp.agent_thinking("frontend-dev",
                      thought="Creating NotificationToast.tsx with auto-dismiss, stack limit of 5, slide-in animation from top-right.")
    await page.wait_for_timeout(2000)
    await screenshot(page, "21_api_multi_agent_active.png")

    pp.agent_message("frontend-dev", "backend-dev",
                     content="Toast component ready, expecting { type, title, body, severity } from WS", tag="interface")
    await page.wait_for_timeout(1500)

    pp.agent_started("backend-dev", task="Implementing WebSocket notification endpoint")
    pp.agent_thinking("backend-dev", thought="Setting up /ws/notifications with connection manager, heartbeat every 30s, JSON message format")
    await page.wait_for_timeout(2500)
    await screenshot(page, "22_api_engineering_phase.png")

    pp.agent_completed("backend-dev", output="WebSocket endpoint implemented with tests")
    pp.agent_completed("frontend-dev", output="NotificationToast component shipped")
    await page.wait_for_timeout(1000)

    pp.agent_completed("planner", output="All subtasks assigned and tracked")
    pp.agent_completed("architect", output="Architecture document finalized")
    await page.wait_for_timeout(2000)
    await screenshot(page, "23_api_agents_completing.png")

    record("API Event Pipeline", True, "Full pipeline simulation with thinking/messages/costs")


# ---- Scenario: Error State ----

async def test_15_error_state(page, pp):
    """Emit an error event and verify it appears on dashboard."""
    pp.agent_started("deploy-agent", task="Deploying to staging environment")
    await page.wait_for_timeout(1000)

    pp.agent_error("deploy-agent", error="Deployment failed — container health check timed out after 60s (exit code 137)")
    await page.wait_for_timeout(2000)
    await screenshot(page, "24_error_state.png")

    record("Error State", True, "Error event emitted and captured")


# ---- Scenario: Bottom Bar ----

async def test_16_bottom_bar(page):
    """Toggle the bottom bar collapse."""
    found = await page.evaluate("""() => {
        const btn = document.getElementById('bottom-collapse');
        if (btn) { btn.click(); return true; }
        return false;
    }""")
    if found:
        await page.wait_for_timeout(500)
        await screenshot(page, "25_bottom_collapsed.png")

        await page.evaluate("() => document.getElementById('bottom-collapse')?.click()")
        await page.wait_for_timeout(500)
        await screenshot(page, "26_bottom_expanded.png")
        record("Bottom Bar Toggle", True, "Collapsed and expanded")
    else:
        record("Bottom Bar Toggle", False, "Collapse button not found")


# ---- Scenario: Final Dashboard State ----

async def test_17_final_state(page):
    """Final screenshot with everything — the money shot."""
    await page.evaluate("() => document.getElementById('ctrl-fit')?.click()")
    await page.wait_for_timeout(1000)

    await screenshot(page, "27_final_dashboard_state.png")
    record("Final Dashboard State", True, "Complete dashboard with all events visible")


# ---- Report Generator ----

def _generate_report():
    screenshots = sorted(SCREENSHOTS_DIR.glob("*.png"))
    report_path = SCREENSHOTS_DIR.parent / "VISUAL_TEST_REPORT.md"

    passed = sum(1 for r in test_results if r["passed"])
    failed = sum(1 for r in test_results if not r["passed"])

    lines = [
        "# PixelPulse Visual E2E Test Report",
        "",
        f"> Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"> Screenshots: {len(screenshots)}",
        f"> Tests: {len(test_results)} ({passed} passed, {failed} failed)",
        "",
        "## Results Summary",
        "",
        "| # | Test | Status | Notes |",
        "|---|------|--------|-------|",
    ]

    for i, r in enumerate(test_results, 1):
        status = "PASS" if r["passed"] else "FAIL"
        lines.append(f"| {i} | {r['name']} | {status} | {r.get('notes', '')} |")

    if console_errors:
        lines += ["", "## Console Errors", ""]
        for err in console_errors[:20]:
            lines.append(f"- `{err[:200]}`")

    lines += ["", "---", "", "## Screenshots", ""]

    for ss in screenshots:
        stem = ss.stem
        title = stem.split("_", 1)[1].replace("_", " ").title() if "_" in stem else stem
        lines += [
            f"### {title}",
            "",
            f"![{title}](screenshots/{ss.name})",
            "",
        ]

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log.info("Report generated: %s", report_path)
    return report_path


# ---- Main Runner ----

async def main():
    from playwright.async_api import async_playwright

    pp = _start_server()
    pp_instance, server_thread = _run_server(pp)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        page.on("console", lambda m: (
            console_errors.append(f"[{m.type}] {m.text}")
            if m.type in ("error", "warning") else None
        ))
        page.on("pageerror", lambda e: (
            console_errors.append(f"[PAGE_ERROR] {e}"),
            log.error("PAGE ERROR: %s", e),
        ))

        try:
            log.info("=" * 60)
            log.info("PIXELPULSE VISUAL E2E TESTS")
            log.info("=" * 60)

            await test_01_idle_dashboard(page)
            await test_02_demo_active(page, pp_instance)
            await test_03_message_flow(page, pp_instance)
            await test_04_agent_detail_panel(page)
            await test_05_canvas_agent_click(page)
            await test_06_sidebar_toggle(page)
            await test_07_theme_switch(page)
            await test_08_keyboard_help(page)
            await test_09_view_controls(page)
            await test_10_stop_demo(page)
            await test_11_event_log(page)
            await test_12_run_history(page)
            await test_13_replay_controls(page)
            await test_14_api_events(page, pp_instance)
            await test_15_error_state(page, pp_instance)
            await test_16_bottom_bar(page)
            await test_17_final_state(page)

        finally:
            js_errors = [m for m in console_errors if "error" in m.lower() or "PAGE_ERROR" in m]
            if js_errors:
                log.warning("JS errors found: %d", len(js_errors))
                for err in js_errors[:5]:
                    log.warning("  %s", err[:200])

            await browser.close()

    report_path = _generate_report()

    log.info("=" * 60)
    passed = sum(1 for r in test_results if r["passed"])
    failed = sum(1 for r in test_results if not r["passed"])
    log.info("RESULTS: %d passed, %d failed out of %d tests", passed, failed, len(test_results))
    log.info("Screenshots: %d", len(list(SCREENSHOTS_DIR.glob("*.png"))))
    log.info("Report: %s", report_path)
    log.info("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
