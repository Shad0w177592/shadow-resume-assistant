import { downmixAndResample, encodePcm16Wav, recordAndTranscribe } from "./audio";

class FakeRecorder extends EventTarget {
  mimeType = "audio/webm";
  constructor(_stream: MediaStream) { super(); }
  start() {}
  stop() {
    this.dispatchEvent(new MessageEvent("dataavailable", { data: new Blob(["voice"]) }));
    this.dispatchEvent(new Event("stop"));
  }
}

test("transcribes recorded audio and always stops tracks", async () => {
  const stop = vi.fn();
  const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
  const provider = { transcribe: vi.fn(async () => "请把这一段写得更简洁") };
  const result = await recordAndTranscribe(
    stream, provider, 0, FakeRecorder as unknown as typeof MediaRecorder,
  );
  expect(result).toBe("请把这一段写得更简洁");
  expect(provider.transcribe).toHaveBeenCalledOnce();
  expect(stop).toHaveBeenCalledOnce();
});

test("stops tracks when transcription fails", async () => {
  const stop = vi.fn();
  const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
  const provider = { transcribe: vi.fn(async () => { throw new Error("网络失败"); }) };
  await expect(recordAndTranscribe(
    stream, provider, 0, FakeRecorder as unknown as typeof MediaRecorder,
  )).rejects.toThrow("网络失败");
  expect(stop).toHaveBeenCalledOnce();
});


test("encodes browser audio as PCM WAV for Windows recognition", () => {
  const wav = encodePcm16Wav(
    [new Float32Array([-1, -0.5, 0, 0.5, 1])],
    16000,
  );
  const bytes = new Uint8Array(wav);
  const view = new DataView(wav);
  expect(new TextDecoder().decode(bytes.slice(0, 4))).toBe("RIFF");
  expect(new TextDecoder().decode(bytes.slice(8, 12))).toBe("WAVE");
  expect(view.getUint16(20, true)).toBe(1);
  expect(view.getUint16(22, true)).toBe(1);
  expect(view.getUint32(24, true)).toBe(16000);
  expect(view.getUint16(34, true)).toBe(16);
  expect(view.getInt16(44, true)).toBe(-32768);
  expect(view.getInt16(52, true)).toBe(32767);
});
test("downmixes 48kHz browser audio to Windows recognizer compatible 16kHz mono", () => {
  const left = new Float32Array(48000).fill(0.75);
  const right = new Float32Array(48000).fill(0.25);
  const mono = downmixAndResample([left, right], 48000);
  expect(mono).toHaveLength(16000);
  expect(mono[0]).toBeCloseTo(0.5);
  expect(mono[15999]).toBeCloseTo(0.5);
});