"""Tests for PixelPulse configuration."""
from pixelpulse.config import (
    AgentConfig,
    TeamConfig,
    normalize_agents,
    normalize_teams,
)


class TestAgentConfig:
    def test_from_dict(self):
        config = AgentConfig.from_dict({"role": "Researcher", "team": "research"})
        assert config.role == "Researcher"
        assert config.team == "research"
        assert config.sprite == "default"

    def test_from_dict_defaults(self):
        config = AgentConfig.from_dict({})
        assert config.role == ""
        assert config.team == "default"

    def test_frozen(self):
        config = AgentConfig(role="test")
        try:
            config.role = "changed"  # type: ignore
            assert False, "Should not allow mutation"
        except AttributeError:
            pass


class TestTeamConfig:
    def test_from_dict(self):
        config = TeamConfig.from_dict({"label": "Research", "color": "#00d4ff", "icon": "🔬"})
        assert config.label == "Research"
        assert config.color == "#00d4ff"
        assert config.icon == "🔬"


class TestNormalize:
    def test_normalize_agents_from_dicts(self):
        raw = {
            "researcher": {"role": "Finds info", "team": "research"},
            "writer": {"role": "Writes", "team": "content"},
        }
        result = normalize_agents(raw)
        assert len(result) == 2
        assert isinstance(result["researcher"], AgentConfig)
        assert result["researcher"].team == "research"

    def test_normalize_agents_from_configs(self):
        raw = {"researcher": AgentConfig(role="Finds info", team="research")}
        result = normalize_agents(raw)
        assert result["researcher"].role == "Finds info"

    def test_normalize_teams_none(self):
        result = normalize_teams(None)
        assert result == {}

    def test_normalize_teams_from_dicts(self):
        raw = {"research": {"label": "Research Lab", "color": "#00d4ff"}}
        result = normalize_teams(raw)
        assert isinstance(result["research"], TeamConfig)
        assert result["research"].label == "Research Lab"
