// PixelPulse VS Code Extension — pure CommonJS, no build step required
"use strict";

const vscode = require("vscode");
const http = require("http");

// ─── Configuration ───────────────────────────────────────────────────────────

function getPort() {
  return vscode.workspace.getConfiguration("pixelpulse").get("port", 8765);
}

function getBaseUrl() {
  return `http://localhost:${getPort()}`;
}

// ─── Server Detection ────────────────────────────────────────────────────────

function checkServerRunning() {
  return new Promise((resolve) => {
    const url = `${getBaseUrl()}/api/health`;
    const req = http.get(url, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        try {
          const json = JSON.parse(data);
          resolve(json.status === "ok");
        } catch {
          resolve(false);
        }
      });
    });
    req.on("error", () => resolve(false));
    req.setTimeout(2000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

// ─── Webview HTML ────────────────────────────────────────────────────────────

function getOfflineHtml() {
  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src 'unsafe-inline';">
  <style>
    body {
      font-family: var(--vscode-font-family);
      color: var(--vscode-foreground);
      background: var(--vscode-editor-background);
      display: flex;
      align-items: center;
      justify-content: center;
      height: 90vh;
      flex-direction: column;
      text-align: center;
      padding: 20px;
    }
    .status {
      width: 12px; height: 12px; border-radius: 50%;
      background: #f44; display: inline-block; margin-right: 8px;
    }
    h2 { margin-bottom: 8px; }
    p { color: var(--vscode-descriptionForeground); margin: 4px 0; }
    code {
      background: var(--vscode-textCodeBlock-background);
      padding: 2px 6px; border-radius: 3px;
      font-family: var(--vscode-editor-font-family);
    }
    .actions { margin-top: 16px; }
    button {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none; padding: 8px 16px; border-radius: 4px;
      cursor: pointer; font-size: 13px;
    }
    button:hover { background: var(--vscode-button-hoverBackground); }
  </style>
</head>
<body>
  <h2><span class="status"></span> PixelPulse Offline</h2>
  <p>The PixelPulse server is not running.</p>
  <p>Start it with: <code>pixelpulse serve</code></p>
  <p>Or use the Command Palette: <code>PixelPulse: Start Server</code></p>
  <div class="actions">
    <button onclick="acquireVsCodeApi().postMessage({command: 'startServer'})">
      Start Server
    </button>
  </div>
</body>
</html>`;
}

function getDashboardHtml(port) {
  const url = `http://localhost:${port}`;
  return `<!DOCTYPE html>
<html style="height:100%; margin:0; padding:0;">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; frame-src http://localhost:${port}; style-src 'unsafe-inline';">
  <style>
    html, body { height: 100%; margin: 0; padding: 0; overflow: hidden; }
    iframe { width: 100%; height: 100%; border: none; display: block; }
  </style>
</head>
<body>
  <iframe src="${url}"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups">
  </iframe>
</body>
</html>`;
}

// ─── Sidebar Webview Provider ────────────────────────────────────────────────

class PixelPulseSidebarProvider {
  constructor() {
    this._view = null;
  }

  async resolveWebviewView(webviewView) {
    this._view = webviewView;

    webviewView.webview.options = { enableScripts: true };

    // Handle messages from the offline page
    webviewView.webview.onDidReceiveMessage((msg) => {
      if (msg.command === "startServer") {
        vscode.commands.executeCommand("pixelpulse.startServer");
      }
    });

    await this._updateContent();
  }

  async refresh() {
    await this._updateContent();
  }

  async _updateContent() {
    if (!this._view) return;
    const running = await checkServerRunning();
    this._view.webview.html = running
      ? getDashboardHtml(getPort())
      : getOfflineHtml();
  }
}

// ─── Extension Entry Point ───────────────────────────────────────────────────

async function activate(context) {
  const provider = new PixelPulseSidebarProvider();

  // Register sidebar webview
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("pixelpulse.sidebar", provider)
  );

  // Command: Open Dashboard (full editor panel)
  context.subscriptions.push(
    vscode.commands.registerCommand("pixelpulse.openDashboard", async () => {
      const port = getPort();
      const running = await checkServerRunning();

      const panel = vscode.window.createWebviewPanel(
        "pixelpulseDashboard",
        "PixelPulse Dashboard",
        vscode.ViewColumn.One,
        {
          enableScripts: true,
          retainContextWhenHidden: true,
        }
      );

      panel.webview.html = running
        ? getDashboardHtml(port)
        : getOfflineHtml();

      // Handle messages from offline page
      panel.webview.onDidReceiveMessage((msg) => {
        if (msg.command === "startServer") {
          vscode.commands.executeCommand("pixelpulse.startServer");
        }
      });

      // Auto-refresh when server comes online
      if (!running) {
        const interval = setInterval(async () => {
          const nowRunning = await checkServerRunning();
          if (nowRunning) {
            panel.webview.html = getDashboardHtml(port);
            clearInterval(interval);
          }
        }, 3000);
        panel.onDidDispose(
          () => clearInterval(interval),
          null,
          context.subscriptions
        );
      }
    })
  );

  // Command: Start Server
  context.subscriptions.push(
    vscode.commands.registerCommand("pixelpulse.startServer", async () => {
      const running = await checkServerRunning();
      if (running) {
        vscode.window.showInformationMessage(
          "PixelPulse server is already running."
        );
        return;
      }

      const terminal = vscode.window.createTerminal("PixelPulse");
      terminal.show();
      terminal.sendText(`pixelpulse serve --port ${getPort()}`);

      vscode.window.showInformationMessage("Starting PixelPulse server...");

      // Wait for server to come up, then refresh sidebar
      setTimeout(() => provider.refresh(), 5000);
    })
  );

  // Command: Refresh Dashboard
  context.subscriptions.push(
    vscode.commands.registerCommand("pixelpulse.refreshDashboard", async () => {
      await provider.refresh();
      vscode.window.showInformationMessage("PixelPulse dashboard refreshed.");
    })
  );

  // Status bar item
  const statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100
  );
  statusBar.command = "pixelpulse.openDashboard";
  context.subscriptions.push(statusBar);

  // Update status bar
  async function updateStatusBar() {
    const running = await checkServerRunning();
    statusBar.text = running
      ? "$(pulse) PixelPulse"
      : "$(circle-slash) PixelPulse";
    statusBar.tooltip = running
      ? "Open PixelPulse Dashboard (server running)"
      : "PixelPulse server offline — click to open";
    statusBar.show();
  }

  await updateStatusBar();

  // Poll server status every 30s
  const statusInterval = setInterval(updateStatusBar, 30000);
  context.subscriptions.push({ dispose: () => clearInterval(statusInterval) });

  // Auto-start if configured
  const autoStart = vscode.workspace
    .getConfiguration("pixelpulse")
    .get("autoStart", false);
  if (autoStart) {
    const running = await checkServerRunning();
    if (!running) {
      vscode.commands.executeCommand("pixelpulse.startServer");
    }
  }
}

function deactivate() {}

module.exports = { activate, deactivate };
