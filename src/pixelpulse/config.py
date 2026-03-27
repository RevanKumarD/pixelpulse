"""Configuration dataclasses for PixelPulse agents and teams."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentConfig:
    """Configuration for a single agent in the dashboard.

    Can be created from a dict for convenience::

        AgentConfig.from_dict({"team": "research", "role": "Finds info"})
    """

    role: str = ""
    team: str = "default"
    sprite: str = "default"

    @classmethod
    def from_dict(cls, data: dict) -> AgentConfig:
        return cls(
            role=data.get("role", ""),
            team=data.get("team", "default"),
            sprite=data.get("sprite", "default"),
        )


@dataclass(frozen=True)
class TeamConfig:
    """Configuration for a team grouping in the dashboard."""

    label: str = ""
    color: str = "#64748b"
    icon: str = ""
    role: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> TeamConfig:
        return cls(
            label=data.get("label", ""),
            color=data.get("color", "#64748b"),
            icon=data.get("icon", ""),
            role=data.get("role", ""),
        )


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration for optional pipeline stages."""

    stages: tuple[str, ...] = ()
    stage_to_team: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_list(cls, stages: list[str], mapping: dict[str, str] | None = None) -> PipelineConfig:
        return cls(
            stages=tuple(stages),
            stage_to_team=mapping or {},
        )


def normalize_agents(raw: dict) -> dict[str, AgentConfig]:
    """Convert a dict of agent definitions to AgentConfig instances.

    Accepts both ``{"name": AgentConfig(...)}`` and ``{"name": {"role": "...", "team": "..."}}``
    """
    result = {}
    for name, config in raw.items():
        if isinstance(config, AgentConfig):
            result[name] = config
        elif isinstance(config, dict):
            result[name] = AgentConfig.from_dict(config)
        else:
            raise TypeError(f"Agent config for '{name}' must be a dict or AgentConfig, got {type(config)}")
    return result


def normalize_teams(raw: dict | None) -> dict[str, TeamConfig]:
    """Convert a dict of team definitions to TeamConfig instances."""
    if not raw:
        return {}
    result = {}
    for name, config in raw.items():
        if isinstance(config, TeamConfig):
            result[name] = config
        elif isinstance(config, dict):
            result[name] = TeamConfig.from_dict(config)
        else:
            raise TypeError(f"Team config for '{name}' must be a dict or TeamConfig, got {type(config)}")
    return result
