import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

export async function loadSchema(name) {
  const raw = await readFile(join(here, "schemas", `${name}.schema.json`), "utf8");
  return JSON.parse(raw);
}

export const schemaNames = [
  "parsed-document",
  "resume-document",
  "job-analysis",
  "evidence-match",
];

