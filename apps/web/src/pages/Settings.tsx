import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { Button, Card, TextInput } from "../components/ui";
import { useNotifications } from "../components/Notifications";

export function SettingsPage() {
  const { notify } = useNotifications();
  const [model, setModel] = useState("gpt-5-mini");
  const [apiMode, setApiMode] = useState<"responses" | "chat_completions">("responses");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [dataDirectory, setDataDirectory] = useState("加载中…");
  const [configured, setConfigured] = useState(false);
  const [backupPath, setBackupPath] = useState("");
  const [clearText, setClearText] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [dataOperation, setDataOperation] = useState(false);

  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (!dataOperation) return;
      event.preventDefault(); event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dataOperation]);

  useEffect(() => {
    if (!window.shadowDesktop) { setDataDirectory("仅桌面应用可查看"); return; }
    Promise.all([
      apiRequest<{ model: string; api_mode?: "responses" | "chat_completions"; base_url?: string }>("/api/settings"),
      apiRequest<{ data_directory: string; api_key_configured: boolean }>("/api/bootstrap"),
    ]).then(([settings, bootstrap]) => {
      setModel(settings.model);
      setApiMode(settings.api_mode || "responses");
      setBaseUrl(settings.base_url || "");
      setDataDirectory(bootstrap.data_directory);
      setConfigured(bootstrap.api_key_configured);
    }).catch((error) => notify(error.message, "error"));
  }, [notify]);

  async function save() {
    try {
      await apiRequest("/api/settings", "PUT", { provider: "openai", model, api_mode: apiMode, base_url: baseUrl, voice_device_id: null });
      if (apiKey) {
        await apiRequest("/api/credentials/openai", "PUT", { api_key: apiKey });
        setConfigured(true);
        setApiKey("");
      }
      notify("设置已保存", "success");
    } catch (error) {
      notify(error instanceof Error ? error.message : "保存失败", "error");
    }
  }

  async function changeDataDirectory() {
    if (!window.shadowDesktop?.changeDataDirectory) {
      notify("当前版本不支持更改数据目录", "error");
      return;
    }
    setDataOperation(true);
    try {
      const result = await window.shadowDesktop.changeDataDirectory();
      if (!result) return;
      setDataDirectory(result.dataDirectory);
      if (result.backupPath) setBackupPath(result.backupPath);
      notify("本地数据目录已切换；旧目录仍保留为安全副本", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "数据目录切换失败，仍使用原目录", "error"); }
    finally { setDataOperation(false); }
  }

  async function createBackup() {
    setDataOperation(true);
    try {
      const backup = await apiRequest<{ path: string }>("/api/backups", "POST");
      setBackupPath(backup.path); notify("备份已保存到本地", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "备份失败", "error"); }
    finally { setDataOperation(false); }
  }

  async function restoreBackup() {
    const path = await window.shadowDesktop?.pickBackup();
    if (!path) return;
    setDataOperation(true);
    try {
      const result = await apiRequest<{ restored_files: number; automatic_backup: string }>("/api/backups/restore", "POST", { path });
      setBackupPath(result.automatic_backup); notify(`已恢复 ${result.restored_files} 个文件；恢复前数据已自动备份`, "success");
    } catch (error) { notify(error instanceof Error ? error.message : "恢复失败，原数据未改变", "error"); }
    finally { setDataOperation(false); }
  }

  async function clearAll() {
    try {
      await apiRequest("/api/data/clear", "POST", { confirmation: clearText, include_api_key: clearKey });
      setClearText(""); setConfigured(clearKey ? false : configured); notify("本地数据已全部清除", "success");
    } catch (error) { notify(error instanceof Error ? error.message : "清除失败", "error"); }
  }

  return (
    <main className="page" aria-labelledby="page-title">
      <p className="eyebrow">影子简历助手</p><h1 id="page-title">设置</h1>
      <div className="settings-grid">
        <Card title="AI 服务">
          <p>状态：{configured ? "已配置" : "未配置"}</p>
          <label className="field"><span>接口模式</span><select aria-label="接口模式" value={apiMode} onChange={(event) => setApiMode(event.target.value as "responses" | "chat_completions")}><option value="responses">Responses API（OpenAI 官方）</option><option value="chat_completions">Chat Completions（JUAPI 等兼容网关）</option></select></label>
          <TextInput label="模型" value={model} onChange={(event) => setModel(event.target.value)} />
          <TextInput label="Base URL（选填）" placeholder="https://api.openai.com/v1" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          <small>OpenAI 官方请选择 Responses API；JUAPI 请选择 Chat Completions。请填写 API 根地址，不要附加具体接口路径。</small>
          <TextInput label="替换 API Key（选填）" type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} />
          <Button onClick={save}>保存设置</Button>
        </Card>
        <Card title="语音设备"><p>将在语音修改阶段显示麦克风权限和设备状态。文字输入始终可用。</p></Card>
        <Card title="本地数据"><p className="path-text">{dataDirectory}</p><p>可以改到 D 盘等任意可写位置。请选择一个空文件夹；切换前会自动备份并复制数据，旧目录继续保留为安全副本。</p><div className="actions"><Button disabled={dataOperation} onClick={changeDataDirectory}>更改保存位置</Button><Button disabled={dataOperation} onClick={createBackup}>导出全部备份</Button><Button disabled={dataOperation} className="secondary" onClick={restoreBackup}>从备份恢复</Button></div>{backupPath && <p className="path-text">最近备份：{backupPath}</p>}</Card>
        <Card title="软件信息"><p>影子简历助手 0.1.8 · 本地优先桌面版</p></Card>
        <Card title="危险操作"><p className="warning-text">清除个人资料、源文件、岗位、草稿和历史版本。此操作不可撤销。</p><TextInput label="输入“清除全部数据”确认" value={clearText} onChange={(event) => setClearText(event.target.value)} /><label className="check"><input type="checkbox" checked={clearKey} onChange={(event) => setClearKey(event.target.checked)} />同时删除 API Key</label><Button className="danger" disabled={clearText !== "清除全部数据"} onClick={clearAll}>清除全部数据</Button></Card>
      </div>
    </main>
  );
}
