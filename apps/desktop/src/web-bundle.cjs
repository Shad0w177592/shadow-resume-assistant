const fs = require("node:fs");
const path = require("node:path");

function validateWebBundle(webRoot) {
  const indexPath = path.join(webRoot, "index.html");
  if (!fs.existsSync(indexPath)) throw new Error(`missing web entry: ${indexPath}`);
  const html = fs.readFileSync(indexPath, "utf8");
  const references = [...html.matchAll(/(?:src|href)=["']([^"']+)["']/g)]
    .map((match) => match[1])
    .filter((reference) => !reference.startsWith("data:"));
  if (references.length === 0) throw new Error("web entry has no script or stylesheet assets");
  for (const reference of references) {
    if (reference.startsWith("/") || /^[a-z]+:/i.test(reference)) {
      throw new Error(`web asset must use a relative file URL: ${reference}`);
    }
    const assetPath = path.resolve(webRoot, reference);
    if (!assetPath.startsWith(path.resolve(webRoot) + path.sep) || !fs.existsSync(assetPath)) {
      throw new Error(`missing or unsafe web asset: ${reference}`);
    }
  }
  return references;
}

module.exports = { validateWebBundle };
