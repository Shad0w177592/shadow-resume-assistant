const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { EventEmitter } = require("node:events");
const test = require("node:test");
const { createSessionToken, createSidecarSupervisor, getFreePort, startSidecar, stopSidecar } = require("../src/sidecar.cjs");

test("creates an unpredictable session token", () => {
  const first = createSessionToken();
  const second = createSessionToken();
  assert.notEqual(first, second);
  assert.ok(first.length >= 40);
});

test("reserves a loopback random port", async () => {
  const port = await getFreePort();
  assert.ok(Number.isInteger(port));
  assert.ok(port > 0 && port < 65536);
});

test("restarts a crashed sidecar but does not restart after application stop", async () => {
  const children = [];
  let starts = 0;
  const supervisor = createSidecarSupervisor({}, {
    restartDelayMs: 5,
    start: async () => {
      starts += 1;
      const child = new EventEmitter();
      child.exitCode = null;
      children.push(child);
      return { child, baseUrl: `http://127.0.0.1:${starts}`, token: `token-${starts}` };
    },
    stop: async (sidecar) => {
      sidecar.child.exitCode = 0;
      sidecar.child.emit("exit", 0);
    },
  });
  await supervisor.start();
  children[0].exitCode = 1;
  children[0].emit("exit", 1);
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(starts, 2);
  assert.equal(supervisor.current.token, "token-2");
  await supervisor.stop();
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(starts, 2);
});

test("starts the FastAPI sidecar and shuts it down", async () => {
  const appRoot = path.resolve(__dirname, "..", "..", "..");
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "shadow-dev-sidecar-"));
  const startedAt = performance.now();
  const sidecar = await startSidecar({ appRoot, resourcesPath: "", packaged: false, dataDir });
  try {
    assert.ok(performance.now() - startedAt < 5000, "backend should become healthy within 5 seconds");
    const response = await fetch(`${sidecar.baseUrl}/api/session-check`, {
      headers: { "x-shadow-session": sidecar.token },
    });
    assert.equal(response.status, 200);
  } finally {
    await stopSidecar(sidecar);
    fs.rmSync(dataDir, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  }
});

test("starts and stops the packaged PyInstaller sidecar", {
  skip: !process.env.SHADOW_PACKAGED_BACKEND,
}, async () => {
  const resourcesPath = fs.mkdtempSync(path.join(os.tmpdir(), "shadow-sidecar-"));
  const backendDir = path.join(resourcesPath, "backend");
  fs.mkdirSync(backendDir);
  fs.copyFileSync(
    process.env.SHADOW_PACKAGED_BACKEND,
    path.join(backendDir, "shadow-resume-backend.exe"),
  );
  const sidecar = await startSidecar({
    appRoot: "",
    resourcesPath,
    packaged: true,
    dataDir: path.join(resourcesPath, "data"),
  });
  try {
    const response = await fetch(`${sidecar.baseUrl}/health`);
    assert.equal(response.status, 200);
    const settings = await fetch(`${sidecar.baseUrl}/api/settings`, {
      method: "PUT",
      headers: {
        "content-type": "application/json",
        "x-shadow-session": sidecar.token,
      },
      body: JSON.stringify({
        provider: "openai",
        model: "gateway-model",
        base_url: "https://gateway.example.com/v1/",
      }),
    });
    assert.equal(settings.status, 200);
    assert.equal((await settings.json()).base_url, "https://gateway.example.com/v1");
    const fixture = path.resolve(__dirname, "..", "..", "..", "tests", "fixtures", "documents", "docx-04-mixed.docx");
    const imported = await fetch(`${sidecar.baseUrl}/api/imports/from-path`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-shadow-session": sidecar.token,
      },
      body: JSON.stringify({ path: fixture }),
    });
    assert.equal(imported.status, 201);
    const payload = await imported.json();
    assert.equal(payload.status, "parsed");
    assert.ok(payload.candidates.some((candidate) => candidate.section_key === "project"));
  } finally {
    await stopSidecar(sidecar);
    await new Promise((resolve) => setTimeout(resolve, 300));
    fs.rmSync(resourcesPath, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  }
});
