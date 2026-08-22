export interface TranscriptionProvider {
  transcribe(blob: Blob): Promise<string>;
}

export async function recordAndTranscribe(
  stream: MediaStream,
  provider: TranscriptionProvider,
  durationMs: number,
  Recorder: typeof MediaRecorder = MediaRecorder,
): Promise<string> {
  const chunks: BlobPart[] = [];
  const recorder = new Recorder(stream);
  const stopped = new Promise<void>((resolve, reject) => {
    recorder.addEventListener("dataavailable", (event: BlobEvent) => chunks.push(event.data));
    recorder.addEventListener("stop", () => resolve());
    recorder.addEventListener("error", () => reject(new Error("录音失败")));
  });
  try {
    recorder.start();
    await new Promise((resolve) => setTimeout(resolve, durationMs));
    recorder.stop();
    await stopped;
    return await provider.transcribe(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
  } finally {
    stream.getTracks().forEach((track) => track.stop());
  }
}

