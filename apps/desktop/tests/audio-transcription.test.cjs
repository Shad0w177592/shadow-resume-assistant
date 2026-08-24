const assert = require("node:assert/strict");
const test = require("node:test");
const { isWave, transcribeWithBackend } = require("../src/audio-transcription.cjs");

function wave() {
  const bytes = Buffer.alloc(44);
  bytes.write("RIFF", 0, "ascii");
  bytes.write("WAVE", 8, "ascii");
  return bytes;
}

test("forwards WAV recordings to the authenticated local transcription endpoint", async () => {
  let request;
  const result = await transcribeWithBackend({
    bytes: wave(), mediaType: "audio/wav", baseUrl: "http://127.0.0.1:43111", token: "session-token",
  }, async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ text: "请把这一段写得更简洁" }), {
      status: 200, headers: { "content-type": "application/json" },
    });
  });
  assert.deepEqual(result, { text: "请把这一段写得更简洁" });
  assert.equal(request.url, "http://127.0.0.1:43111/api/transcriptions");
  assert.equal(request.options.headers["x-shadow-session"], "session-token");
  assert.equal(request.options.body.get("audio").type, "audio/wav");
});

test("rejects invalid audio and preserves backend error details", async () => {
  assert.equal(isWave(wave()), true);
  await assert.rejects(
    transcribeWithBackend({ bytes: Buffer.from("webm"), baseUrl: "http://local", token: "x" }),
    /录音格式无效/,
  );
  await assert.rejects(
    transcribeWithBackend({ bytes: wave(), baseUrl: "http://local", token: "x" }, async () => (
      new Response(JSON.stringify({ detail: "当前网关不支持语音模型" }), {
        status: 422, headers: { "content-type": "application/json" },
      })
    )),
    /当前网关不支持语音模型/,
  );
});
