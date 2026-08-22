import { afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { NotificationProvider } from "../components/Notifications";
import { ProfilePage } from "./Profile";
import { JobsPage } from "./Jobs";

afterEach(() => {
  delete window.shadowDesktop;
  vi.restoreAllMocks();
});

function withProviders(component: React.ReactNode) {
  return render(<MemoryRouter><NotificationProvider>{component}</NotificationProvider></MemoryRouter>);
}

test("profile fields are optional and a free-form entry can be added", async () => {
  const request = vi.fn(async (path: string, method = "GET") => {
    if (path === "/api/profile" && method === "GET") return { id: "profile", display_name: "", personal_info: {}, entries: [] };
    if (path === "/api/profile" && method === "PUT") return { id: "profile", display_name: "", personal_info: {} };
    if (path === "/api/profile/entries") return { id: "entry-1", section_key: "other", title: "开源社区", payload: { content: "维护中文文档" }, created_at: "", updated_at: "" };
    if (path === "/api/profile/photo/from-path") return { file_id: "photo-1", data_url: "data:image/png;base64,AA==" };
    if (path === "/api/profile/photo/photo-1") return { file_id: "photo-1", data_url: "data:image/png;base64,AA==" };
    throw new Error(`unexpected ${method} ${path}`);
  });
  window.shadowDesktop = {
    platform: "win32",
    health: async () => ({ status: "ok" }),
    pickDocument: async () => null,
    pickPhoto: async () => "C:\\photo.png",
    pickBackup: async () => null,
    transcribeAudio: async () => ({ text: "" }),
    request: request as unknown as <T>(path: string, method?: string, body?: unknown) => Promise<T>,
  };
  const user = userEvent.setup();
  withProviders(<ProfilePage />);
  expect(await screen.findByText("还没有经历")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "添加照片" }));
  expect(await screen.findByAltText("个人照片预览")).toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("栏目"), "other");
  await user.type(screen.getByLabelText("标题（选填）"), "开源社区");
  await user.type(screen.getByLabelText(/经历内容/), "维护中文文档");
  await user.click(screen.getByRole("button", { name: "新增经历" }));
  expect(await screen.findByText("开源社区")).toBeInTheDocument();
  expect(screen.getAllByText("其他自定义经历或成果")).toHaveLength(2);
});

test("a job can generate a read-only evidence-backed draft preview", async () => {
  const job = { id: "job-1", company: "影子科技", title: "AI Agent 产品经理", jd_text: "负责 Agent 产品", notes: null, status: "draft", updated_at: "" };
  const request = vi.fn(async (path: string, method = "GET") => {
    if (path === "/api/jobs" && method === "GET") return [];
    if (path === "/api/jobs" && method === "POST") return job;
    if (path === "/api/jobs/job-1/analyze") return { stale: false, requirements: [{ id: "r-1", requirement_type: "must_have", summary: "负责 Agent 产品", source_text: "负责 Agent 产品", status: "full", reason: "资料中包含 Agent 产品证据", evidence: { entry_id: "entry-1", title: "影子简历助手", payload: {} } }] };
    if (path === "/api/jobs/job-1/generate") return { id: "draft-1", job_target_id: "job-1", document: { personal_info: { name: "杨丰铭", headline: "", contacts: [] }, sections: [{ section_id: "section-1", title: "项目经历", blocks: [{ block_id: "block-1", heading: "影子简历助手", meta: "", paragraphs: [{ paragraph_id: "p-1", text: "完成本地简历工作流", source_entry_ids: ["entry-1"] }] }] }] } };
    if (path === "/api/jobs/job-1" && method === "DELETE") return null;
    throw new Error(`unexpected ${method} ${path}`);
  });
  window.shadowDesktop = {
    platform: "win32",
    health: async () => ({ status: "ok" }),
    pickDocument: async () => null,
    pickBackup: async () => null,
    transcribeAudio: async () => ({ text: "" }),
    request: request as unknown as <T>(path: string, method?: string, body?: unknown) => Promise<T>,
  };
  const user = userEvent.setup();
  withProviders(<JobsPage />);
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/jobs", "GET", undefined));
  await user.type(screen.getByLabelText("公司（选填）"), "影子科技");
  await user.type(screen.getByLabelText("岗位名称（选填）"), "AI Agent 产品经理");
  await user.type(screen.getByLabelText("岗位 JD"), "负责 Agent 产品");
  await user.click(screen.getByRole("button", { name: "保存岗位" }));
  await user.click(await screen.findByRole("button", { name: "分析匹配" }));
  expect(await screen.findByText("充分匹配")).toBeInTheDocument();
  expect(screen.getByText("证据：影子简历助手")).toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: "生成草稿" }));
  expect(await screen.findByText("完成本地简历工作流")).toBeInTheDocument();
  expect(screen.getByText("杨丰铭")).toBeInTheDocument();
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  await user.click(screen.getByRole("button", { name: "删除" }));
  expect(request).not.toHaveBeenCalledWith("/api/jobs/job-1", "DELETE", undefined);
  await user.click(screen.getByRole("button", { name: "删除" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/jobs/job-1", "DELETE", undefined));
  expect(confirm).toHaveBeenCalledTimes(2);
});
