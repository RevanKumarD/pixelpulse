"""Tests for the PixelPulse server lifecycle manager."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "plugins" / "claude-code" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


class TestCheckServerRunning:
    @patch("ensure_server.httpx")
    def test_returns_true_when_healthy(self, mock_httpx):
        from ensure_server import check_server_running

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_httpx.Client.return_value = mock_client

        assert check_server_running(8765) is True

    @patch("ensure_server.httpx")
    def test_returns_false_when_unreachable(self, mock_httpx):
        from ensure_server import check_server_running

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("Connection refused")
        mock_httpx.Client.return_value = mock_client

        assert check_server_running(8765) is False


class TestBuildServeCommand:
    def test_default_command(self):
        from ensure_server import build_serve_command

        cmd = build_serve_command(port=8765)
        assert "serve" in cmd
        assert "--port" in cmd
        assert "8765" in cmd
        assert "--no-browser" in cmd

    def test_custom_port(self):
        from ensure_server import build_serve_command

        cmd = build_serve_command(port=9000)
        assert "9000" in cmd


class TestWaitForServer:
    @patch("ensure_server.check_server_running")
    def test_returns_true_when_healthy_immediately(self, mock_check):
        from ensure_server import wait_for_server

        mock_check.return_value = True
        assert wait_for_server(8765, max_wait=5) is True

    @patch("ensure_server.time.sleep")
    @patch("ensure_server.check_server_running")
    def test_returns_false_after_timeout(self, mock_check, mock_sleep):
        from ensure_server import wait_for_server

        mock_check.return_value = False
        assert wait_for_server(8765, max_wait=2) is False
