const crypto = require("node:crypto");
const net = require("node:net");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

function createSessionToken() {
  return crypto.randomBytes(32).toString("base64url");
}

async function waitForHealth(baseUrl, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/health`);
      if (response.ok) return response.json();
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`backend health timeout: ${lastError?.message ?? "unknown"}`);
}

async function waitForUrl(url, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`URL timeout for ${url}: ${lastError?.message ?? "unknown"}`);
}

async function startSidecar({ appRoot, resourcesPath, packaged, dataDir }) {
  const port = await getFreePort();
  const token = createSessionToken();
  const env = {
    ...process.env,
    SHADOW_SESSION_TOKEN: token,
    ...(dataDir ? { SHADOW_DATA_DIR: dataDir } : {}),
  };
  let executable;
  let args;
  let cwd;
  if (packaged) {
    executable = path.join(resourcesPath, "backend", "shadow-resume-backend.exe");
    args = ["--host", "127.0.0.1", "--port", String(port)];
    cwd = path.dirname(executable);
  } else {
    executable = path.join(appRoot, ".venv", "Scripts", "python.exe");
    args = ["-m", "app", "--host", "127.0.0.1", "--port", String(port)];
    cwd = path.join(appRoot, "backend");
  }
  const child = spawn(executable, args, { cwd, env, windowsHide: true, stdio: "ignore" });
  const baseUrl = `http://127.0.0.1:${port}`;
  await waitForHealth(baseUrl);
  return { child, baseUrl, token };
}

async function stopSidecar(sidecar) {
  const child = sidecar?.child;
  if (!child || child.exitCode !== null) return;
  try {
    await fetch(`${sidecar.baseUrl}/internal/shutdown`, {
      method: "POST",
      headers: { "x-shadow-session": sidecar.token },
    });
    await Promise.race([
      new Promise((resolve) => child.once("exit", resolve)),
      new Promise((resolve) => setTimeout(resolve, 2000)),
    ]);
  } catch {
    // Fall through to the process-tree fallback below.
  }
  if (child.exitCode !== null) return;
  if (process.platform === "win32" && child.pid) {
    spawnSync("taskkill", ["/pid", String(child.pid), "/t", "/f"], {
      windowsHide: true,
      stdio: "ignore",
    });
    return;
  }
  child.kill("SIGTERM");
}

function createSidecarSupervisor(
  options,
  { start = startSidecar, stop = stopSidecar, restartDelayMs = 500, onError = () => {} } = {},
) {
  let current = null;
  let stopping = false;
  let restartTimer = null;

  async function launch() {
    const launched = await start(options);
    current = launched;
    launched.child.once("exit", () => {
      if (stopping || current !== launched) return;
      current = null;
      restartTimer = setTimeout(() => {
        restartTimer = null;
        launch().catch(onError);
      }, restartDelayMs);
    });
    return launched;
  }

  return {
    get current() { return current; },
    async start() {
      stopping = false;
      return launch();
    },
    async stop() {
      stopping = true;
      if (restartTimer) clearTimeout(restartTimer);
      restartTimer = null;
      const active = current;
      current = null;
      if (active) await stop(active);
    },
  };
}

module.exports = {
  createSessionToken,
  createSidecarSupervisor,
  getFreePort,
  startSidecar,
  stopSidecar,
  waitForHealth,
  waitForUrl,
};
