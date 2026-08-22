import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Onboarding, type BootstrapState } from "./Onboarding";
import { apiRequest } from "../api";

vi.mock("../api", () => ({ apiRequest: vi.fn(async () => ({})) }));

const initial: BootstrapState = {
  privacy_accepted: false,
  initialized: false,
  onboarding_step: 0,
  api_key_configured: false,
  data_directory: "C:\\test",
};

beforeEach(() => vi.clearAllMocks());

test("privacy consent is required before onboarding continues", async () => {
  render(<Onboarding initial={initial} onComplete={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "继续" }));
  expect(screen.getByRole("alert")).toHaveTextContent("请先确认");
  expect(screen.getByRole("heading", { name: "数据保存在这台电脑" })).toBeInTheDocument();
});

test("API key input is masked after accepting privacy", async () => {
  render(<Onboarding initial={initial} onComplete={vi.fn()} />);
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(screen.getByRole("button", { name: "继续" }));
  expect(screen.getByLabelText("API Key（选填）")).toHaveAttribute("type", "password");
  expect(screen.getByLabelText("模型")).toHaveValue("gpt-5-mini");
  expect(screen.getByLabelText("接口模式")).toHaveValue("responses");
  expect(screen.getByLabelText("Base URL（选填）")).toHaveValue("");
});

test("onboarding saves gateway settings before testing its API key", async () => {
  const user = userEvent.setup();
  render(<Onboarding initial={{ ...initial, privacy_accepted: true, onboarding_step: 1 }} onComplete={vi.fn()} />);
  await user.clear(screen.getByLabelText("模型"));
  await user.type(screen.getByLabelText("模型"), "gateway-model");
  await user.type(screen.getByLabelText("Base URL（选填）"), "https://gateway.example.com/v1");
  await user.type(screen.getByLabelText("API Key（选填）"), "gateway-token");
  await user.selectOptions(screen.getByLabelText("接口模式"), "chat_completions");
  await user.click(screen.getByRole("button", { name: "继续" }));
  expect(vi.mocked(apiRequest)).toHaveBeenNthCalledWith(1, "/api/settings", "PUT", {
    provider: "openai",
    model: "gateway-model",
    api_mode: "chat_completions",
    base_url: "https://gateway.example.com/v1",
    voice_device_id: null,
  });
  expect(vi.mocked(apiRequest)).toHaveBeenNthCalledWith(
    2, "/api/credentials/openai", "PUT", { api_key: "gateway-token" },
  );
});
