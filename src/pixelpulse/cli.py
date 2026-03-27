"""CLI entry point for PixelPulse.

Usage::

    pixelpulse                    # Start with demo configuration (default)
    pixelpulse demo               # Same as above, explicit
    pixelpulse serve              # Start headless server (no demo agents)
    pixelpulse serve --port 9000  # Custom port
"""
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="pixelpulse",
        description="PixelPulse — Real-time pixel-art dashboard for multi-agent systems",
    )
    parser.add_argument("--version", action="version", version="pixelpulse 0.1.0")
    subparsers = parser.add_subparsers(dest="command")

    # ---- serve: headless server for plugins / external adapters ----
    serve_parser = subparsers.add_parser(
        "serve", help="Start headless PixelPulse server (no demo agents)"
    )
    serve_parser.add_argument(
        "--port", type=int, default=8765, help="Server port (default: 8765)"
    )
    serve_parser.add_argument(
        "--no-browser", action="store_true", help="Don't auto-open browser"
    )
    serve_parser.add_argument(
        "--theme", choices=["dark", "light"], default="dark", help="Dashboard theme"
    )

    # ---- demo: current behavior with sample agents ----
    demo_parser = subparsers.add_parser(
        "demo", help="Start with demo agent configuration (default)"
    )
    demo_parser.add_argument(
        "--port", type=int, default=8765, help="Server port (default: 8765)"
    )
    demo_parser.add_argument(
        "--no-browser", action="store_true", help="Don't auto-open browser"
    )
    demo_parser.add_argument(
        "--theme", choices=["dark", "light"], default="dark", help="Dashboard theme"
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Default to demo if no subcommand given (belt-and-suspenders alongside set_defaults)
    command = args.command or "demo"

    from pixelpulse import PixelPulse  # deferred: keeps build_parser() side-effect free

    if command == "serve":
        # Headless: no pre-configured agents — adapters register dynamically
        pp = PixelPulse(
            agents={},
            teams={},
            title="PixelPulse",
            theme=getattr(args, "theme", "dark"),
            port=args.port,
        )
        print(f"\n  PixelPulse v0.1.0 (serve mode)")
        print(f"  Dashboard: http://localhost:{args.port}")
        print(f"  Hook endpoint: http://localhost:{args.port}/hooks/claude-code")
        print(f"  Waiting for events...\n")
        pp.serve(port=args.port, open_browser=not args.no_browser)

    else:  # demo
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
            theme=getattr(args, "theme", "dark"),
            port=getattr(args, "port", 8765),
        )
        port = getattr(args, "port", 8765)
        theme = getattr(args, "theme", "dark")
        print("\n  PixelPulse v0.1.0")
        print(f"  Dashboard: http://localhost:{port}")
        print(f"  Theme: {theme}")
        print(f"  Agents: {len(pp.agents)}")
        print(f"  Teams: {len(pp.teams)}")
        print()
        pp.serve(port=port, open_browser=not getattr(args, "no_browser", False))


if __name__ == "__main__":
    main()
