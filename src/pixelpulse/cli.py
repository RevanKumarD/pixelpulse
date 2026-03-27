"""CLI entry point for PixelPulse.

Usage::

    pixelpulse                  # Start with demo configuration
    pixelpulse --port 9000      # Custom port
    pixelpulse --no-browser     # Don't auto-open browser
"""
from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pixelpulse",
        description="PixelPulse — Real-time pixel-art dashboard for multi-agent systems",
    )
    parser.add_argument("--port", type=int, default=8765, help="Server port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    parser.add_argument(
        "--theme", choices=["dark", "light"], default="dark", help="Dashboard theme"
    )
    parser.add_argument("--version", action="version", version="pixelpulse 0.1.0")

    args = parser.parse_args(argv)

    from pixelpulse import PixelPulse

    # Demo configuration — shows what the dashboard looks like
    pp = PixelPulse(
        agents={
            "researcher": {"team": "research", "role": "Searches for information"},
            "analyst": {"team": "research", "role": "Analyzes data patterns"},
            "writer": {"team": "content", "role": "Writes articles and reports"},
            "editor": {"team": "content", "role": "Reviews and edits content"},
            "designer": {"team": "design", "role": "Creates visual assets"},
            "reviewer": {"team": "quality", "role": "Quality assurance checks"},
        },
        teams={
            "research": {"label": "Research Lab", "color": "#00d4ff", "icon": "🔬"},
            "content": {"label": "Content Studio", "color": "#ff6ec7", "icon": "📝"},
            "design": {"label": "Design Floor", "color": "#39ff14", "icon": "🎨"},
            "quality": {"label": "QA Center", "color": "#ffae00", "icon": "✅"},
        },
        pipeline=["research", "analysis", "writing", "design", "review", "publish"],
        title="PixelPulse Demo",
        theme=args.theme,
        port=args.port,
    )

    print("\n  PixelPulse v0.1.0")
    print(f"  Dashboard: http://localhost:{args.port}")
    print(f"  Theme: {args.theme}")
    print(f"  Agents: {len(pp.agents)}")
    print(f"  Teams: {len(pp.teams)}")
    print()

    pp.serve(port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
