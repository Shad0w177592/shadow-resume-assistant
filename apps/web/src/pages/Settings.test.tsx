import { afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { NotificationProvider } from "../components/Notifications";
import { SettingsPage } from "./Settings";

afterEach(() => {
  delete window.shadowDesktop;
  vi.restoreAllMocks();
});

test("backup restore and exact clear confirmation are available from settings", async () => {
  const request = vi.fn(async (path: string, method = "GET") => {
    if (path === "/api/settings")
      return {
        model: "gpt-5-mini",
        api_mode: "chat_completions",
        base_url: "https://gateway.example.com/v1",
        transcription_base_url: "https://speech.example.com/v1",
        transcription_model: "whisper-1",
      };
    if (path === "/api/bootstrap")
      return {
        data_directory: "C:\\data",
        api_key_configured: true,
        transcription_api_key_configured: true,
      };
    if (path === "/api/backups" && method === "POST")
      return { path: "C:\\data\\backups\\backup.zip" };
    if (path === "/api/backups/restore")
      return {
        restored_files: 3,
        automatic_backup: "C:\\data\\backups\\auto.zip",
      };
    if (path === "/api/data/clear") return { cleared: true };
    throw new Error(`unexpected ${method} ${path}`);
  });
  window.shadowDesktop = {
    platform: "win32",
    health: async () => ({ status: "ok" }),
    pickDocument: async () => null,
    pickBackup: async () => "C:\\backup.zip",
    transcribeAudio: async () => ({ text: "" }),
    changeDataDirectory: async () => ({
      dataDirectory: "D:\\影子简历数据",
      backupPath: "C:\\data\\backups\\before-move.zip",
      oldDirectory: "C:\\data",
      oldDirectoryPreserved: true,
    }),
    request: request as unknown as <T>(
      path: string,
      method?: string,
      body?: unknown,
    ) => Promise<T>,
  };
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <NotificationProvider>
        <SettingsPage />
      </NotificationProvider>
    </MemoryRouter>,
  );
  expect(await screen.findByText("状态：已配置")).toBeInTheDocument();
  expect(screen.getByLabelText("Base URL（选填）")).toHaveValue(
    "https://gateway.example.com/v1",
  );
  expect(screen.getByLabelText("接口模式")).toHaveValue("chat_completions");
  expect(screen.getByLabelText("语音 Base URL（选填）")).toHaveValue(
    "https://speech.example.com/v1",
  );
  expect(screen.getByLabelText("语音转写模型")).toHaveValue("whisper-1");
  await user.click(screen.getByRole("button", { name: "保存设置" }));
  expect(request).toHaveBeenCalledWith("/api/settings", "PUT", {
    provider: "openai",
    model: "gpt-5-mini",
    api_mode: "chat_completions",
    base_url: "https://gateway.example.com/v1",
    transcription_base_url: "https://speech.example.com/v1",
    transcription_model: "whisper-1",
    voice_device_id: null,
  });
  await user.click(screen.getByRole("button", { name: "更改保存位置" }));
  expect(await screen.findByText("D:\\影子简历数据")).toBeInTheDocument();
  expect(await screen.findByText(/旧目录仍保留为安全副本/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "导出全部备份" }));
  expect(await screen.findByText(/backup.zip/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "从备份恢复" }));
  expect(await screen.findByText(/已恢复 3 个文件/)).toBeInTheDocument();
  const clear = screen.getByRole("button", { name: "清除全部数据" });
  expect(clear).toBeDisabled();
  await user.type(
    screen.getByLabelText("输入“清除全部数据”确认"),
    "清除全部数据",
  );
  expect(clear).toBeEnabled();
  await user.click(clear);
  expect(await screen.findByText("本地数据已全部清除")).toBeInTheDocument();
});
test("selecting DeepSeek configures the official compatible API", async () => {
  const request = vi.fn(async (path: string) => {
    if (path === "/api/settings")
      return {
        provider: "openai",
        model: "gpt-5-mini",
        api_mode: "responses",
        base_url: "",
      };
    if (path === "/api/bootstrap")
      return {
        data_directory: "C:\\data",
        api_key_configured: false,
        transcription_api_key_configured: false,
      };
    return {};
  });
  window.shadowDesktop = {
    platform: "win32",
    health: async () => ({ status: "ok" }),
    pickDocument: async () => null,
    pickBackup: async () => null,
    transcribeAudio: async () => ({ text: "" }),
    changeDataDirectory: async () => null,
    request: request as unknown as <T>(
      path: string,
      method?: string,
      body?: unknown,
    ) => Promise<T>,
  };
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <NotificationProvider>
        <SettingsPage />
      </NotificationProvider>
    </MemoryRouter>,
  );

  await user.selectOptions(await screen.findByLabelText("服务商"), "deepseek");
  expect(screen.getByLabelText("接口模式")).toHaveValue("chat_completions");
  expect(screen.getByLabelText("模型")).toHaveValue("deepseek-v4-flash");
  expect(screen.getByLabelText("Base URL（选填）")).toHaveValue(
    "https://api.deepseek.com",
  );
  await user.click(screen.getByRole("button", { name: "保存设置" }));
  expect(request).toHaveBeenCalledWith(
    "/api/settings",
    "PUT",
    expect.objectContaining({
      provider: "deepseek",
      model: "deepseek-v4-flash",
      api_mode: "chat_completions",
      base_url: "https://api.deepseek.com",
    }),
  );
});
