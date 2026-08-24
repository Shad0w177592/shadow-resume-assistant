function isWave(bytes) {
  const value = Buffer.from(bytes || []);
  return value.length >= 12
    && value.subarray(0, 4).toString("ascii") === "RIFF"
    && value.subarray(8, 12).toString("ascii") === "WAVE";
}

async function transcribeWithBackend(
  { bytes, mediaType = "audio/wav", baseUrl, token },
  fetchImpl = fetch,
) {
  const value = Buffer.from(bytes || []);
  if (!isWave(value)) throw new Error("录音格式无效，请重新录音");
  if (value.byteLength > 15 * 1024 * 1024) throw new Error("录音超过 15MB，请缩短后重试");
  if (mediaType !== "audio/wav" && mediaType !== "audio/wave") {
    throw new Error("录音格式转换失败，请重新录音");
  }
  const form = new FormData();
  form.append("audio", new Blob([value], { type: "audio/wav" }), "shadow-voice.wav");
  const response = await fetchImpl(`${baseUrl}/api/transcriptions`, {
    method: "POST",
    headers: { "x-shadow-session": token },
    body: form,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(payload?.detail || `语音转写失败（HTTP ${response.status}）`);
  const text = String(payload?.text || "").trim();
  if (!text) throw new Error("没有识别到清晰语音，请靠近麦克风后重试");
  return { text };
}

module.exports = { isWave, transcribeWithBackend };
