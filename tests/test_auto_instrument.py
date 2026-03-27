"""Tests for PixelPulse.auto_instrument()."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from pixelpulse import PixelPulse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_pp(**kwargs) -> PixelPulse:
    """Create a minimal PixelPulse instance without a running server."""
    return PixelPulse(
        agents={"agent-a": {"team": "research", "role": "Researcher"}},
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------


class TestAutoInstrumentReturnType:
    def test_returns_dict(self):
        pp = _make_pp()
        with patch.dict(sys.modules, {
            "crewai": None, "langgraph": None, "agents": None, "autogen": None,
        }):
            result = pp.auto_instrument()
        assert isinstance(result, dict)

    def test_returns_all_expected_keys(self):
        pp = _make_pp()
        with patch.dict(sys.modules, {
            "crewai": None, "langgraph": None, "agents": None, "autogen": None,
        }):
            result = pp.auto_instrument()
        assert set(result.keys()) == {"crewai", "langgraph", "openai", "autogen"}

    def test_values_are_booleans(self):
        pp = _make_pp()
        with patch.dict(sys.modules, {
            "crewai": None, "langgraph": None, "agents": None, "autogen": None,
        }):
            result = pp.auto_instrument()
        for key, val in result.items():
            assert isinstance(val, bool), f"{key} value should be bool, got {type(val)}"


# ---------------------------------------------------------------------------
# No frameworks installed
# ---------------------------------------------------------------------------


class TestNoFrameworksInstalled:
    def test_all_false_when_none_installed(self):
        """With no frameworks installed every value should be False."""
        pp = _make_pp()

        # Force all framework imports to fail
        with patch.dict(sys.modules, {
            "crewai": None,
            "langgraph": None,
            "agents": None,
            "autogen": None,
        }):
            result = pp.auto_instrument()

        for key, val in result.items():
            assert val is False, f"Expected {key}=False, got {val}"

    def test_does_not_raise_when_none_installed(self):
        """auto_instrument must never raise even when no framework is present."""
        pp = _make_pp()

        with patch.dict(sys.modules, {
            "crewai": None,
            "langgraph": None,
            "agents": None,
            "autogen": None,
        }):
            result = pp.auto_instrument()  # should not raise

        assert result is not None


# ---------------------------------------------------------------------------
# Single framework detected
# ---------------------------------------------------------------------------


class TestSingleFrameworkDetected:
    def test_detected_framework_returns_true(self):
        """Mocking a successful import should record True for that framework."""
        pp = _make_pp()
        fake_crewai = MagicMock()

        with patch.dict(sys.modules, {
            "crewai": fake_crewai,
            "langgraph": None,
            "agents": None,
            "autogen": None,
        }):
            # Also patch the adapter creation so we don't need real crewai classes
            with patch.object(pp, "adapter", return_value=MagicMock()) as mock_adapter:
                result = pp.auto_instrument()

        assert result["crewai"] is True
        mock_adapter.assert_called_once_with("crewai")

    def test_detected_framework_stored_in_adapters(self):
        """Detected adapter should be accessible via pp._adapters."""
        pp = _make_pp()
        fake_module = MagicMock()
        fake_adapter = MagicMock()

        with patch.dict(sys.modules, {
            "crewai": fake_module,
            "langgraph": None,
            "agents": None,
            "autogen": None,
        }):
            with patch.object(pp, "adapter", return_value=fake_adapter):
                pp.auto_instrument()

        assert "crewai" in pp._adapters
        assert pp._adapters["crewai"] is fake_adapter


# ---------------------------------------------------------------------------
# Multiple frameworks detected
# ---------------------------------------------------------------------------


class TestMultipleFrameworksDetected:
    def test_multiple_detected_all_true(self):
        pp = _make_pp()
        fake_crewai = MagicMock()
        fake_langgraph = MagicMock()

        with patch.dict(sys.modules, {
            "crewai": fake_crewai,
            "langgraph": fake_langgraph,
            "agents": None,
            "autogen": None,
        }):
            with patch.object(pp, "adapter", return_value=MagicMock()):
                result = pp.auto_instrument()

        assert result["crewai"] is True
        assert result["langgraph"] is True
        assert result["openai"] is False
        assert result["autogen"] is False

    def test_adapters_dict_populated_for_each_detected(self):
        pp = _make_pp()
        fake_crewai = MagicMock()
        fake_langgraph = MagicMock()

        with patch.dict(sys.modules, {
            "crewai": fake_crewai,
            "langgraph": fake_langgraph,
            "agents": None,
            "autogen": None,
        }):
            with patch.object(pp, "adapter", return_value=MagicMock()):
                pp.auto_instrument()

        assert "crewai" in pp._adapters
        assert "langgraph" in pp._adapters
        assert "openai" not in pp._adapters
        assert "autogen" not in pp._adapters


# ---------------------------------------------------------------------------
# _adapters initialisation
# ---------------------------------------------------------------------------


class TestAdaptersAttribute:
    def test_adapters_dict_exists_on_new_instance(self):
        pp = _make_pp()
        assert hasattr(pp, "_adapters")
        assert isinstance(pp._adapters, dict)

    def test_adapters_dict_initially_empty(self):
        pp = _make_pp()
        assert pp._adapters == {}
