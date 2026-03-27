"""Tests for the PixelPulse CLI subcommands."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pixelpulse.cli import build_parser, main


class TestBuildParser:
    def test_serve_subcommand_exists(self):
        parser = build_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"

    def test_serve_default_port(self):
        parser = build_parser()
        args = parser.parse_args(["serve"])
        assert args.port == 8765

    def test_serve_custom_port(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "--port", "9000"])
        assert args.port == 9000

    def test_serve_no_browser_flag(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "--no-browser"])
        assert args.no_browser is True

    def test_demo_subcommand_exists(self):
        parser = build_parser()
        args = parser.parse_args(["demo"])
        assert args.command == "demo"

    def test_demo_has_theme(self):
        parser = build_parser()
        args = parser.parse_args(["demo", "--theme", "light"])
        assert args.theme == "light"

    def test_no_subcommand_defaults_to_demo(self):
        # argparse returns None when no subcommand given; main() normalizes via `or "demo"`
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None


class TestMainServe:
    @patch("pixelpulse.PixelPulse")
    def test_serve_creates_empty_pixelpulse(self, mock_pp_cls):
        mock_pp = MagicMock()
        mock_pp_cls.return_value = mock_pp
        main(["serve", "--port", "9000", "--no-browser"])
        mock_pp_cls.assert_called_once()
        _, kwargs = mock_pp_cls.call_args
        assert kwargs["port"] == 9000
        mock_pp.serve.assert_called_once_with(port=9000, open_browser=False)
