const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

test("release version matches desktop, web, settings and installer verification", () => {
  const root = path.resolve(__dirname, "../../..");
  const read = (file) => fs.readFileSync(path.join(root, file), "utf8");
  const metadata = JSON.parse(read("package.json"));
  for (const file of ["apps/desktop/package.json", "apps/web/package.json"]) {
    assert.equal(JSON.parse(read(file)).version, metadata.version, file);
  }
  assert.ok(read("apps/web/src/pages/Settings.tsx").includes(`影子简历助手 ${metadata.version} ·`));
  assert.ok(metadata.scripts["verify:package"].includes(`Setup ${metadata.version}.exe`));
});
