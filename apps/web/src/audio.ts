export interface TranscriptionProvider {
  transcribe(blob: Blob): Promise<string>;
}

export function downmixAndResample(
  channels: Float32Array[],
  sourceRate: number,
  targetRate = 16000,
): Float32Array {
  if (channels.length === 0 || channels.some((channel) => channel.length !== channels[0].length)) {
    throw new Error("录音声道数据无效");
  }
  if (sourceRate <= 0 || targetRate <= 0) throw new Error("录音采样率无效");
  const outputLength = Math.max(1, Math.round(channels[0].length * targetRate / sourceRate));
  const output = new Float32Array(outputLength);
  for (let index = 0; index < outputLength; index += 1) {
    const position = index * sourceRate / targetRate;
    const left = Math.min(Math.floor(position), channels[0].length - 1);
    const right = Math.min(left + 1, channels[0].length - 1);
    const fraction = position - left;
    let mixed = 0;
    for (const channel of channels) {
      mixed += channel[left] + (channel[right] - channel[left]) * fraction;
    }
    output[index] = mixed / channels.length;
  }
  return output;
}

export function encodePcm16Wav(channels: Float32Array[], sampleRate: number): ArrayBuffer {
  if (channels.length === 0 || channels.some((channel) => channel.length !== channels[0].length)) {
    throw new Error("录音声道数据无效");
  }
  const frameCount = channels[0].length;
  const bytesPerSample = 2;
  const dataLength = frameCount * channels.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataLength);
  const view = new DataView(buffer);
  const writeAscii = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };
  writeAscii(0, "RIFF");
  view.setUint32(4, 36 + dataLength, true);
  writeAscii(8, "WAVE");
  writeAscii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels.length, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * channels.length * bytesPerSample, true);
  view.setUint16(32, channels.length * bytesPerSample, true);
  view.setUint16(34, 16, true);
  writeAscii(36, "data");
  view.setUint32(40, dataLength, true);
  let offset = 44;
  for (let frame = 0; frame < frameCount; frame += 1) {
    for (const channel of channels) {
      const sample = Math.max(-1, Math.min(1, channel[frame]));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += bytesPerSample;
    }
  }
  return buffer;
}

export async function convertRecordedAudioToWav(blob: Blob): Promise<Blob> {
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer());
    const channels = Array.from(
      { length: decoded.numberOfChannels },
      (_, index) => decoded.getChannelData(index),
    );
    return new Blob([encodePcm16Wav([downmixAndResample(channels, decoded.sampleRate)], 16000)], {
      type: "audio/wav",
    });
  } finally {
    await context.close();
  }
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

