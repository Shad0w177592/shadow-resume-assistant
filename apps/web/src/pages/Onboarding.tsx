import { useState } from "react";
import { apiRequest } from "../api";
import { Button, Card, Stepper, TextInput } from "../components/ui";

export type BootstrapState = {
  privacy_accepted: boolean;
  initialized: boolean;
  onboarding_step: number;
  api_key_configured: boolean;
  data_directory: string;
};

export function Onboarding({ initial, onComplete }: { initial: BootstrapState; onComplete: () => void }) {
  const [step, setStep] = useState(initial.onboarding_step);
  const [accepted, setAccepted] = useState(initial.privacy_accepted);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("gpt-5-mini");
  const [apiMode, setApiMode] = useState<"responses" | "chat_completions">("responses");
  const [baseUrl, setBaseUrl] = useState("");
  const [error, setError] = useState("");
  const steps = ["隐私说明", "AI 配置", "开始方式", "完成"];

  async function next() {
    setError("");
    if (step === 0 && !accepted) {
      setError("请先确认本地数据与联网调用说明");
      return;
    }
    if (step === 1) {
      try {
        await apiRequest("/api/settings", "PUT", {
          provider: "openai", model, api_mode: apiMode, base_url: baseUrl, voice_device_id: null,
        });
        if (apiKey) await apiRequest("/api/credentials/openai", "PUT", { api_key: apiKey });
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "API Key 保存失败");
        return;
      }
    }
    const nextStep = Math.min(3, step + 1);
    await apiRequest("/api/bootstrap", "PATCH", {
      privacy_accepted: accepted,
      onboarding_step: nextStep,
      initialized: nextStep === 3,
    });
    setStep(nextStep);
    if (nextStep === 3) onComplete();
  }

  return (
    <main className="onboarding">
      <p className="eyebrow">影子简历助手</p>
      <h1>欢迎使用</h1>
      <Stepper steps={steps} current={step} />
      <Card>
        {step === 0 && <>
          <h2>数据保存在这台电脑</h2>
          <p>个人资料、岗位、草稿和版本保存在本地；只有需要 AI 分析或修改时，脱敏后的必要内容才会发送给你配置的模型服务。</p>
          <label className="check"><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} /> 我已理解并同意继续</label>
        </>}
        {step === 1 && <>
          <h2>配置 OpenAI API 或兼容网关</h2>
          <p>API Key 保存到 Windows 凭据管理器，不写入数据库、日志或备份。现在也可以留空，稍后在设置中配置。</p>
          <label className="field"><span>接口模式</span><select aria-label="接口模式" value={apiMode} onChange={(event) => setApiMode(event.target.value as "responses" | "chat_completions")}><option value="responses">Responses API（OpenAI 官方）</option><option value="chat_completions">Chat Completions（JUAPI 等兼容网关）</option></select></label>
          <TextInput label="模型" value={model} onChange={(event) => setModel(event.target.value)} />
          <TextInput label="Base URL（选填）" placeholder="https://api.openai.com/v1" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          <small>使用 JUAPI 时请选择 Chat Completions，并填写 https://www.juapi.net/v1。</small>
          <TextInput label="API Key（选填）" type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} />
        </>}
        {step === 2 && <>
          <h2>选择开始方式</h2>
          <p>你可以从空白资料开始，也可以在后续页面导入 Word 或 PDF 简历。</p>
          <div className="choice-grid"><button type="button">从空白开始</button><button type="button">稍后导入简历</button></div>
        </>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <Button onClick={next}>{step === 2 ? "完成初始化" : "继续"}</Button>
      </Card>
    </main>
  );
}
