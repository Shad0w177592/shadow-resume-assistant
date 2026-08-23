const { execFile } = require("node:child_process");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { promisify } = require("node:util");
const { randomUUID } = require("node:crypto");

const execFileAsync = promisify(execFile);

function isWave(bytes) {
  const value = Buffer.from(bytes);
  return value.length >= 12
    && value.subarray(0, 4).toString("ascii") === "RIFF"
    && value.subarray(8, 12).toString("ascii") === "WAVE";
}

function recognitionScript(audioPath) {
  const encodedPath = Buffer.from(audioPath, "utf8").toString("base64");
  return `$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName System.Speech
$recognizer = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() |
  Where-Object { $_.Culture.Name -eq 'zh-CN' } |
  Select-Object -First 1
if ($null -eq $recognizer) { throw 'SHADOW_NO_ZH_RECOGNIZER' }
$engine = [System.Speech.Recognition.SpeechRecognitionEngine]::new($recognizer)
try {
  $audioPath = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${encodedPath}'))
  $engine.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
  $engine.SetInputToWaveFile($audioPath)
  $parts = [System.Collections.Generic.List[string]]::new()
  while ($true) {
    try {
      $result = $engine.Recognize()
    } catch {
      if ($parts.Count -gt 0 -and $_.Exception.InnerException -is [System.InvalidOperationException]) { break }
      throw
    }
    if ($null -eq $result) { break }
    if (-not [string]::IsNullOrWhiteSpace($result.Text)) { $parts.Add($result.Text.Trim()) }
  }
  if ($parts.Count -eq 0) { throw 'SHADOW_NO_SPEECH' }
  [Console]::Write(($parts -join ''))
} finally {
  $engine.Dispose()
}`;
}

async function transcribeWindowsChinese(bytes, options = {}) {
  if (process.platform !== "win32" && !options.allowNonWindows) {
    throw new Error("Windows 中文语音识别仅支持 Windows");
  }
  if (!bytes || bytes.byteLength === 0 || bytes.byteLength > 15 * 1024 * 1024) {
    throw new Error("录音为空或超过 15MB");
  }
  if (!isWave(bytes)) {
    throw new Error("录音格式无效，请重新录音");
  }
  const temporaryDirectory = options.tempDirectory || os.tmpdir();
  const audioPath = path.join(temporaryDirectory, `shadow-speech-${randomUUID()}.wav`);
  const runner = options.runner || execFileAsync;
  await fs.mkdir(temporaryDirectory, { recursive: true });
  await fs.writeFile(audioPath, Buffer.from(bytes));
  try {
    const encodedCommand = Buffer.from(recognitionScript(audioPath), "utf16le").toString("base64");
    const { stdout = "" } = await runner(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-EncodedCommand", encodedCommand],
      { windowsHide: true, timeout: 45000, encoding: "utf8" },
    );
    const text = String(stdout).trim();
    if (!text) throw new Error("没有识别到清晰的中文，请靠近麦克风后重试");
    return text;
  } catch (error) {
    const details = `${error?.stdout || ""}\n${error?.stderr || ""}\n${error?.message || ""}`;
    if (details.includes("SHADOW_NO_ZH_RECOGNIZER")) {
      throw new Error("Windows 未安装简体中文语音识别，请先安装中文语音包");
    }
    if (details.includes("SHADOW_NO_SPEECH")) {
      throw new Error("没有识别到清晰的中文，请靠近麦克风后重试");
    }
    if (error instanceof Error && error.message.startsWith("没有识别到")) throw error;
    throw new Error("Windows 中文语音识别失败，请检查麦克风和中文语音包");
  } finally {
    await fs.unlink(audioPath).catch(() => undefined);
  }
}

module.exports = { isWave, recognitionScript, transcribeWindowsChinese };
