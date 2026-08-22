import { recordAndTranscribe } from "./audio";

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

