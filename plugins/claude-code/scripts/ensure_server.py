#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Ensure a PixelPulse server is running.

Checks health, starts one if needed, waits for readiness.
Called by hook_handler.py on SessionStart events.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
import webbrowser

import httpx


def check_server_running(port: int) -> bool:
    """Return True if PixelPulse is responding on the given port."""
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(f"http://localhost:{port}/api/health")
            return resp.status_code == 200
    except Exception:
        return False


def build_serve_command(port: int) -> list[str]:
    """Build the command to start PixelPulse in serve mode."""
    pixelpulse_bin = shutil.which("pixelpulse")
    if pixelpulse_bin:
        return [pixelpulse_bin, "serve", "--port", str(port), "--no-browser"]
    # Fallback: run as python module
    return [sys.executable, "-m", "pixelpulse.cli", "serve", "--port", str(port), "--no-browser"]


def start_server(port: int) -> subprocess.Popen | None:
    """Start PixelPulse as a background process."""
    cmd = build_serve_command(port)
    try:
        kwargs = {}
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
        return proc
    except Exception:
        return None


def wait_for_server(port: int, max_wait: int = 10) -> bool:
    """Poll health endpoint until server is ready or timeout."""
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        if check_server_running(port):
            return True
        time.sleep(0.5)
    return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ensure PixelPulse is running")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)

    if check_server_running(args.port):
        return  # Already running

    start_server(args.port)
    ready = wait_for_server(args.port)

    if ready and args.open_browser:
        webbrowser.open(f"http://localhost:{args.port}")


if __name__ == "__main__":
    main()
