const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const {
  copyManagedData,
  readConfiguredDataDirectory,
  writeConfiguredDataDirectory,
} = require("../src/data-directory.cjs");

test("copies managed local data and remembers the selected directory", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "shadow-data-move-"));
  const current = path.join(root, "current");
  const target = path.join(root, "D-drive-data");
  const control = path.join(root, "control");
  try {
    fs.mkdirSync(path.join(current, "data"), { recursive: true });
    fs.mkdirSync(path.join(current, "documents", "imports"), { recursive: true });
    fs.mkdirSync(path.join(current, "temp"), { recursive: true });
    fs.writeFileSync(path.join(current, "data", "app.db"), "database");
    fs.writeFileSync(path.join(current, "documents", "imports", "resume.docx"), "word");
    fs.writeFileSync(path.join(current, "temp", "partial"), "temporary");

    const result = copyManagedData(current, target);
    assert.deepEqual(result.copiedEntries, ["data", "documents"]);
    assert.equal(fs.readFileSync(path.join(target, "data", "app.db"), "utf8"), "database");
    assert.equal(
      fs.readFileSync(path.join(target, "documents", "imports", "resume.docx"), "utf8"),
      "word",
    );
    assert.equal(fs.existsSync(path.join(target, "temp")), false);

    writeConfiguredDataDirectory(control, target);
    assert.equal(readConfiguredDataDirectory(control, current), path.resolve(target));
    writeConfiguredDataDirectory(control, current);
    assert.equal(readConfiguredDataDirectory(control, target), path.resolve(current));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("rejects non-empty and overlapping target directories", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "shadow-data-guard-"));
  const current = path.join(root, "current");
  const nonEmpty = path.join(root, "non-empty");
  try {
    fs.mkdirSync(current, { recursive: true });
    fs.mkdirSync(nonEmpty, { recursive: true });
    fs.writeFileSync(path.join(nonEmpty, "existing.txt"), "keep");
    assert.throws(() => copyManagedData(current, nonEmpty), /空文件夹/);
    assert.throws(() => copyManagedData(current, path.join(current, "nested")), /不能互相包含/);
    assert.equal(fs.readFileSync(path.join(nonEmpty, "existing.txt"), "utf8"), "keep");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
