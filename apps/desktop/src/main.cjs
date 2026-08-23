const path = require("node:path");
const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { createSidecarSupervisor, waitForUrl } = require("./sidecar.cjs");
const { validateWebBundle } = require("./web-bundle.cjs");
const { transcribeWindowsChinese } = require("./windows-speech.cjs");
const {
  copyManagedData,
  readConfiguredDataDirectory,
  writeConfiguredDataDirectory,
} = require("./data-directory.cjs");

const appRoot = path.resolve(__dirname, "..", "..", "..");
let sidecarSupervisor;
let quitting = false;

// Electron's default userData path is already local and per-user. Calling
// app.getPath("localAppData") this early crashes on newer Electron versions,
// so only override userData when an isolated smoke-test directory is supplied.
if (process.env.SHADOW_SMOKE_DATA_DIR) {
  app.setPath("userData", process.env.SHADOW_SMOKE_DATA_DIR);
}
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) app.quit();

async function createWindow() {
  const controlDirectory = app.getPath("userData");
  let activeDataDirectory = readConfiguredDataDirectory(controlDirectory, controlDirectory);
  const makeSidecarSupervisor = (dataDir) => createSidecarSupervisor(
    { appRoot, resourcesPath: process.resourcesPath, packaged: app.isPackaged, dataDir },
    { onError: (error) => console.error("Failed to restart backend", error.message) },
  );
  sidecarSupervisor = makeSidecarSupervisor(activeDataDirectory);
  await sidecarSupervisor.start();
  if (process.env.SHADOW_SMOKE_TEST === "1") {
    await sidecarSupervisor.stop();
    sidecarSupervisor = null;
    app.quit();
    return;
  }
  ipcMain.handle("backend:health", async () => {
    const response = await fetch(`${sidecarSupervisor.current.baseUrl}/health`);
    return response.json();
  });
  ipcMain.handle("backend:request", async (_event, request) => {
    const method = String(request?.method ?? "GET").toUpperCase();
    const requestPath = String(request?.path ?? "");
    if (!requestPath.startsWith("/api/") || !["GET", "POST", "PUT", "PATCH", "DELETE"].includes(method)) {
      throw new Error("blocked backend request");
    }
    const response = await fetch(`${sidecarSupervisor.current.baseUrl}${requestPath}`, {
      method,
      headers: {
        "content-type": "application/json",
        "x-shadow-session": sidecarSupervisor.current.token,
      },
      body: request?.body === undefined ? undefined : JSON.stringify(request.body),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(payload?.detail ?? `request failed: ${response.status}`);
    }
    return payload;
  });
  ipcMain.handle("file:pick-document", async () => {
    const result = await dialog.showOpenDialog({
      title: "选择简历或作品集",
      properties: ["openFile"],
      filters: [{ name: "支持的文档", extensions: ["pdf", "docx", "txt", "md"] }],
    });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("file:pick-photo", async () => {
    const result = await dialog.showOpenDialog({
      title: "选择个人照片",
      properties: ["openFile"],
      filters: [{ name: "图片", extensions: ["png", "jpg", "jpeg"] }],
    });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("file:pick-backup", async () => {
    const result = await dialog.showOpenDialog({
      title: "选择影子简历助手备份",
      properties: ["openFile"],
      filters: [{ name: "备份文件", extensions: ["zip"] }],
    });
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("data:change-directory", async () => {
    const result = await dialog.showOpenDialog({
      title: "选择新的本地数据文件夹",
      properties: ["openDirectory", "createDirectory"],
      buttonLabel: "使用这个文件夹",
    });
    if (result.canceled) return null;
    const targetDirectory = path.resolve(result.filePaths[0]);
    if (targetDirectory === activeDataDirectory) {
      return { dataDirectory: activeDataDirectory, backupPath: null, oldDirectoryPreserved: true };
    }

    const backupResponse = await fetch(`${sidecarSupervisor.current.baseUrl}/api/backups`, {
      method: "POST",
      headers: { "x-shadow-session": sidecarSupervisor.current.token },
    });
    const backup = await backupResponse.json().catch(() => null);
    if (!backupResponse.ok) {
      throw new Error(backup?.detail || "切换前自动备份失败，数据目录未改变");
    }

    const previousDirectory = activeDataDirectory;
    await sidecarSupervisor.stop();
    try {
      copyManagedData(previousDirectory, targetDirectory);
      writeConfiguredDataDirectory(controlDirectory, targetDirectory);
      activeDataDirectory = targetDirectory;
      sidecarSupervisor = makeSidecarSupervisor(activeDataDirectory);
      await sidecarSupervisor.start();
      return {
        dataDirectory: activeDataDirectory,
        backupPath: backup.path,
        oldDirectory: previousDirectory,
        oldDirectoryPreserved: true,
      };
    } catch (error) {
      writeConfiguredDataDirectory(controlDirectory, previousDirectory);
      activeDataDirectory = previousDirectory;
      sidecarSupervisor = makeSidecarSupervisor(activeDataDirectory);
      await sidecarSupervisor.start();
      throw error;
    }
  });
  ipcMain.handle("audio:transcribe", async (_event, request) => {
    const bytes = request?.bytes;
    const mediaType = String(request?.mediaType || "audio/wav");
    if (mediaType !== "audio/wav" && mediaType !== "audio/wave") {
      throw new Error("录音格式转换失败，请重新录音");
    }
    return { text: await transcribeWindowsChinese(bytes) };
  });
  const window = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    title: "影子简历助手",
    backgroundColor: "#F7F8FA",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.once("ready-to-show", () => window.show());
  if (app.isPackaged) {
    const webRoot = path.join(process.resourcesPath, "web");
    validateWebBundle(webRoot);
    await window.loadFile(path.join(webRoot, "index.html"));
  } else {
    await waitForUrl("http://127.0.0.1:5173");
    await window.loadURL("http://127.0.0.1:5173");
  }
  if (process.env.SHADOW_RENDER_SMOKE_TEST === "1") {
    const deadline = Date.now() + 10000;
    let rendered = false;
    while (Date.now() < deadline) {
      rendered = await window.webContents.executeJavaScript(
        "Boolean(document.querySelector('#root')?.children.length && document.body.innerText.trim())",
      );
      if (rendered) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (!rendered) throw new Error("frontend did not render into #root");
    await sidecarSupervisor.stop();
    sidecarSupervisor = null;
    app.quit();
  }
}

app.whenReady().then(createWindow).catch((error) => {
  console.error("Failed to start application", error.message);
  app.exit(1);
});

app.on("second-instance", () => {
  const window = BrowserWindow.getAllWindows()[0];
  if (window) {
    if (window.isMinimized()) window.restore();
    window.focus();
  }
});

app.on("before-quit", (event) => {
  if (quitting) return;
  event.preventDefault();
  quitting = true;
  Promise.resolve(sidecarSupervisor?.stop()).finally(() => app.exit(0));
});

app.on("window-all-closed", () => app.quit());
