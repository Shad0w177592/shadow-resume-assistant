import assert from "node:assert/strict";
import test from "node:test";

test("OpenAPI snapshot contains health and authenticated session routes", async () => {
  const schema = await import("../openapi.json", { with: { type: "json" } });
  assert.ok(schema.default.paths["/health"]);
  assert.ok(schema.default.paths["/api/session-check"]);
});

