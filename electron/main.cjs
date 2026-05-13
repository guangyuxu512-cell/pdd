const path = require("path");
const fs = require("fs");
const { app, BrowserWindow, Menu, session } = require("electron");

app.setName("淘宝工具箱");
app.setPath("userData", path.join(__dirname, "..", "data", "electron-shell"));
app.commandLine.appendSwitch("disable-http-cache");

function createWindow() {
  Menu.setApplicationMenu(null);

  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1280,
    minHeight: 820,
    resizable: false,
    maximizable: false,
    fullscreenable: false,
    title: "淘宝工具箱",
    icon: path.join(__dirname, "..", "backend", "app", "static", "assets", "app-icon.png"),
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  const portArg = process.argv.find((arg) => arg.startsWith("--port="));
  const port = portArg ? portArg.slice("--port=".length) : "8800";
  win.loadURL(`http://127.0.0.1:${port}/`);
  win.on("closed", () => {
    app.quit();
  });
}

function stopBackend() {
  const pidFileArg = process.argv.find((arg) => arg.startsWith("--backend-pid-file="));
  const pidFile = pidFileArg ? pidFileArg.slice("--backend-pid-file=".length) : "";
  if (!pidFile || !fs.existsSync(pidFile)) return;
  const pid = Number(fs.readFileSync(pidFile, "utf8").trim());
  if (!Number.isInteger(pid) || pid <= 0) return;
  try {
    process.kill(pid);
  } catch {
  }
}

app.whenReady().then(() => {
  session.defaultSession.clearCache().catch(() => {});
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  stopBackend();
});
