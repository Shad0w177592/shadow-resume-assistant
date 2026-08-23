const assert = require("node:assert/strict");
const { execFile } = require("node:child_process");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { promisify } = require("node:util");

const {
  isWave,
  recognitionScript,
  transcribeWindowsChinese,
} = require("../src/windows-speech.cjs");

const execFileAsync = promisify(execFile);

function emptyWave() {
  const bytes = Buffer.alloc(44);
  bytes.write("RIFF", 0, "ascii");
  bytes.writeUInt32LE(36, 4);
  bytes.write("WAVE", 8, "ascii");
  bytes.write("fmt ", 12, "ascii");
  bytes.writeUInt32LE(16, 16);
  bytes.writeUInt16LE(1, 20);
  bytes.writeUInt16LE(1, 22);
  bytes.writeUInt32LE(16000, 24);
  bytes.writeUInt32LE(32000, 28);
  bytes.writeUInt16LE(2, 32);
  bytes.writeUInt16LE(16, 34);
  bytes.write("data", 36, "ascii");
  return bytes;
}

test("validates WAV input and deletes the temporary recording", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "shadow-speech-test-"));
  const wav = emptyWave();
  assert.equal(isWave(wav), true);
  assert.equal(isWave(Buffer.from("voice")), false);
  const result = await transcribeWindowsChinese(wav, {
    allowNonWindows: true,
    tempDirectory: directory,
    runner: async (executable, args, options) => {
      assert.equal(executable, "powershell.exe");
      assert.deepEqual(args.slice(0, 3), ["-NoProfile", "-NonInteractive", "-EncodedCommand"]);
      assert.equal(options.windowsHide, true);
      assert.match(Buffer.from(args[3], "base64").toString("utf16le"), /zh-CN/);
      assert.equal((await fs.readdir(directory)).length, 1);
      return { stdout: "请把这一段写得更简洁" };
    },
  });
  assert.equal(result, "请把这一段写得更简洁");
  assert.deepEqual(await fs.readdir(directory), []);
  await fs.rm(directory, { recursive: true, force: true });
});

test("returns actionable Windows recognizer errors", async () => {
  const wav = emptyWave();
  await assert.rejects(
    transcribeWindowsChinese(wav, {
      allowNonWindows: true,
      runner: async () => {
        const error = new Error("PowerShell failed");
        error.stderr = "SHADOW_NO_ZH_RECOGNIZER";
        throw error;
      },
    }),
    /安装简体中文语音识别/,
  );
  await assert.rejects(
    transcribeWindowsChinese(Buffer.from("webm"), { allowNonWindows: true }),
    /录音格式无效/,
  );
  assert.match(recognitionScript("C:\\voice.wav"), /DictationGrammar/);
});

test("desktop speech IPC stays local and has no API transcription fallback", async () => {
  const mainSource = await fs.readFile(path.join(__dirname, "..", "src", "main.cjs"), "utf8");
  assert.match(mainSource, /transcribeWindowsChinese\(bytes\)/);
  assert.doesNotMatch(mainSource, /api\/transcriptions|gpt-4o-mini-transcribe/);
});

test("recognizes synthesized Chinese with the installed Windows engine", {
  skip: process.platform !== "win32",
}, async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "shadow-speech-live-"));
  const target = path.join(directory, "spoken.wav");
  const encodedPath = Buffer.from(target, "utf8").toString("base64");
  const script = `[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName System.Speech
$path=[System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${encodedPath}'))
$voice=[System.Speech.Synthesis.SpeechSynthesizer]::new()
try { $voice.SelectVoice('Microsoft Huihui Desktop'); $voice.SetOutputToWaveFile($path); $voice.Speak('把这段写得简洁一点') } finally { $voice.Dispose() }`;
  const encodedCommand = Buffer.from(script, "utf16le").toString("base64");
  await execFileAsync(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-EncodedCommand", encodedCommand],
    { windowsHide: true, timeout: 30000 },
  );
  const text = await transcribeWindowsChinese(await fs.readFile(target), {
    tempDirectory: directory,
  });
  assert.equal(text, "把这段写得简洁一点");
  await fs.rm(directory, { recursive: true, force: true });
});
