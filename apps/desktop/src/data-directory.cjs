const fs = require("node:fs");
const path = require("node:path");

const CONFIG_NAME = "data-location.json";
const MANAGED_ENTRIES = ["data", "documents", "exports", "backups", "logs"];

function normalizeDataDirectory(value) {
  if (typeof value !== "string" || !value.trim()) throw new Error("数据目录不能为空");
  const resolved = path.resolve(value.trim());
  if (!path.isAbsolute(resolved)) throw new Error("数据目录必须是绝对路径");
  return resolved;
}

function samePath(left, right) {
  return process.platform === "win32"
    ? left.toLowerCase() === right.toLowerCase()
    : left === right;
}

function pathsOverlap(left, right) {
  if (samePath(left, right)) return true;
  const relativeLeft = path.relative(left, right);
  const relativeRight = path.relative(right, left);
  return (
    (relativeLeft && !relativeLeft.startsWith("..") && !path.isAbsolute(relativeLeft))
    || (relativeRight && !relativeRight.startsWith("..") && !path.isAbsolute(relativeRight))
  );
}

function configPath(controlDirectory) {
  return path.join(controlDirectory, CONFIG_NAME);
}

function readConfiguredDataDirectory(controlDirectory, fallbackDirectory) {
  const fallback = normalizeDataDirectory(fallbackDirectory);
  try {
    const payload = JSON.parse(fs.readFileSync(configPath(controlDirectory), "utf8"));
    const configured = normalizeDataDirectory(payload.dataDirectory);
    fs.mkdirSync(configured, { recursive: true });
    return configured;
  } catch {
    return fallback;
  }
}

function writeConfiguredDataDirectory(controlDirectory, dataDirectory) {
  const resolved = normalizeDataDirectory(dataDirectory);
  fs.mkdirSync(controlDirectory, { recursive: true });
  const target = configPath(controlDirectory);
  const temporary = `${target}.tmp`;
  const previous = `${target}.previous`;
  fs.writeFileSync(temporary, JSON.stringify({ dataDirectory: resolved }, null, 2), "utf8");
  if (fs.existsSync(previous)) fs.unlinkSync(previous);
  if (fs.existsSync(target)) fs.renameSync(target, previous);
  try {
    fs.renameSync(temporary, target);
    if (fs.existsSync(previous)) fs.unlinkSync(previous);
  } catch (error) {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
    if (fs.existsSync(previous) && !fs.existsSync(target)) {
      fs.renameSync(previous, target);
    }
    throw error;
  }
}

function assertTargetIsEmpty(targetDirectory) {
  if (!fs.existsSync(targetDirectory)) return;
  const entries = fs.readdirSync(targetDirectory);
  if (entries.length) throw new Error("请选择一个空文件夹作为新的本地数据目录");
}

function copyManagedData(currentDirectory, targetDirectory) {
  const current = normalizeDataDirectory(currentDirectory);
  const target = normalizeDataDirectory(targetDirectory);
  if (samePath(current, target)) return { copiedEntries: [], unchanged: true };
  if (pathsOverlap(current, target)) {
    throw new Error("新旧数据目录不能互相包含，请选择另一个独立文件夹");
  }
  assertTargetIsEmpty(target);
  fs.mkdirSync(target, { recursive: true });
  const probe = path.join(target, ".shadow-write-test");
  fs.writeFileSync(probe, "ok", "utf8");
  fs.unlinkSync(probe);
  const copiedEntries = [];
  for (const name of MANAGED_ENTRIES) {
    const source = path.join(current, name);
    if (!fs.existsSync(source)) continue;
    fs.cpSync(source, path.join(target, name), {
      recursive: true,
      errorOnExist: true,
      force: false,
    });
    copiedEntries.push(name);
  }
  return { copiedEntries, unchanged: false };
}

module.exports = {
  CONFIG_NAME,
  copyManagedData,
  normalizeDataDirectory,
  readConfiguredDataDirectory,
  writeConfiguredDataDirectory,
};
