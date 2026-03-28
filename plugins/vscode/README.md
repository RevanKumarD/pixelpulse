# PixelPulse — VS Code Extension

Watch your AI agents work in a pixel-art dashboard, right inside VS Code.

## Features

- **Activity Bar icon** — Quick access to the PixelPulse sidebar
- **Sidebar dashboard** — Live pixel-art agent visualization embedded in the sidebar
- **Full editor panel** — Open a full-size dashboard tab with `PixelPulse: Open Dashboard`
- **Auto-detect server** — Status bar shows whether PixelPulse is online
- **One-click start** — Launch the server from VS Code with `PixelPulse: Start Server`
- **Configurable port** — Set `pixelpulse.port` in VS Code settings

## Installation

### From Source (Development)

1. Clone the repo and open `plugins/vscode/` in VS Code
2. Press `F5` to launch a new Extension Development Host window
3. The PixelPulse icon appears in the activity bar

### From VSIX (Local Install)

```bash
cd plugins/vscode
npx vsce package
code --install-extension pixelpulse-0.1.0.vsix
```

## Usage

1. Start the PixelPulse server (either from terminal or via command):

   ```bash
   pip install pixelpulse
   pixelpulse serve
   ```

2. The VS Code status bar shows `$(pulse) PixelPulse` when the server is detected
3. Click the activity bar icon to see the dashboard in the sidebar
4. Use `Ctrl+Shift+P` → `PixelPulse: Open Dashboard` for a full-size editor tab

## Commands

| Command | Description |
|---------|-------------|
| `PixelPulse: Open Dashboard` | Open the dashboard in a full editor tab |
| `PixelPulse: Start Server` | Start the PixelPulse server in a terminal |
| `PixelPulse: Refresh Dashboard` | Refresh the dashboard webview |

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `pixelpulse.port` | `8765` | Port for the PixelPulse server |
| `pixelpulse.autoStart` | `false` | Auto-start server on extension activation |

## How It Works

The extension embeds the PixelPulse web dashboard using a VS Code webview with an iframe pointing to `http://localhost:{port}`. The Content Security Policy explicitly allows `frame-src` for the localhost origin.

Server detection uses Node's built-in `http` module to check `/api/health` — no npm dependencies required. The extension is pure CommonJS JavaScript with zero build step.

## Requirements

- VS Code 1.74 or later
- PixelPulse Python package installed (`pip install pixelpulse`)
- Python 3.10+
