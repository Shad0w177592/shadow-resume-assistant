const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { validateWebBundle } = require("../src/web-bundle.cjs");

test("packaged web bundle uses existing relative assets", () => {
  const webRoot = path.resolve(__dirname, "..", "..", "web", "dist");
  const references = validateWebBundle(webRoot);
  assert.ok(references.some((reference) => reference.endsWith(".js")));
  assert.ok(references.some((reference) => reference.endsWith(".css")));
});

test("rejects the absolute asset URLs that cause a packaged blank screen", () => {
  const webRoot = fs.mkdtempSync(path.join(os.tmpdir(), "shadow-web-bundle-"));
  try {
    fs.writeFileSync(path.join(webRoot, "index.html"), '<script src="/assets/app.js"></script>');
    assert.throws(() => validateWebBundle(webRoot), /relative file URL/);
  } finally {
    fs.rmSync(webRoot, { recursive: true, force: true });
  }
});

test("main process does not query localAppData before Electron is ready", () => {
  const mainSource = fs.readFileSync(path.resolve(__dirname, "..", "src", "main.cjs"), "utf8");
  const executableLines = mainSource
    .split(/\r?\n/)
    .filter((line) => !line.trimStart().startsWith("//"))
    .join("\n");
  assert.doesNotMatch(executableLines, /app\.getPath\(["']localAppData["']\)/);
});
