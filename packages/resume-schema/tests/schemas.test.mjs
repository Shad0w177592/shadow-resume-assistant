import assert from "node:assert/strict";
import test from "node:test";
import { loadSchema, schemaNames } from "../index.mjs";

for (const name of schemaNames) {
  test(`${name} schema is valid JSON Schema metadata`, async () => {
    const schema = await loadSchema(name);
    assert.equal(schema.$schema, "https://json-schema.org/draft/2020-12/schema");
    assert.equal(typeof schema.$id, "string");
    assert.equal(schema.type, "object");
    assert.ok(Array.isArray(schema.required));
  });
}

