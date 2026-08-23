import { afterEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { NotificationProvider } from "../components/Notifications";
import { WorkbenchPage } from "./Workbench";

afterEach(() => {
  delete window.shadowDesktop;
  vi.restoreAllMocks();
});

test("workbench saves layout choices, generates, edits and saves a draft", async () => {
  const config = {
    template: "single_column", page_target: 1, strategies: ["concise"], entry_modes: {},
    sections: [
      { section_key: "project", title: "项目经历", enabled: true, order: 0, column: "right", max_entries: null },
      { section_key: "skills", title: "专业技能", enabled: true, order: 1, column: "left", max_entries: null },
    ],
  };
  const profile = { id: "profile", display_name: "", personal_info: {}, entries: [{ id: "entry-1", section_key: "project", title: "影子项目", payload: { content: "完成工作流" }, importance: 5, created_at: "", updated_at: "" }] };
  const draft = { id: "draft-1", job_target_id: "job-1", document: { personal_info: { name: "杨丰铭", headline: "", contacts: [] }, sections: [{ section_id: "section-1", section_key: "project", title: "项目经历", order: 0, column: "right", blocks: [{ block_id: "block-1", heading: "影子项目", meta: "", paragraphs: [{ paragraph_id: "p-1", text: "完成工作流", source_entry_ids: ["entry-1"] }] }] }] } };
  const savedVersion = { id: "version-1", name: "版本 1", notes: null, created_at: "2026-08-22T12:00:00Z", snapshot: { document: draft.document, config } };
  const request = vi.fn(async (path: string, method = "GET", body?: unknown) => {
    if (path.endsWith("/resume-config") && method === "GET") return { config };
    if (path === "/api/profile") return profile;
    if (path.endsWith("/draft") && method === "GET") throw new Error("no draft");
    if (path.endsWith("/versions") && method === "GET") return [];
    if (path.endsWith("/resume-config") && method === "PUT") return body;
    if (path.endsWith("/generate")) return { ...draft, fact_warnings: ["生成内容中的数字“2”没有出现在用户资料或当前原文中"] };
    if (path.endsWith("/polish")) return { draft, added_real_count: 0, fabricated: Boolean((body as { allow_fabrication?: boolean }).allow_fabrication), warnings: ["已加入 AI 编造内容，请逐项核实"] };
    if (path.endsWith("/edit-proposals")) return { id: "proposal-1", target_block_id: "p-1", before_text: "完成工作流", after_text: "完成可恢复工作流", status: "pending", payload: { instruction: "写得更简洁", reason: "删除重复表达", evidence_ids: ["entry-1"], save_scope: "current_resume", contains_new_fact: false } };
    if (path.endsWith("/edit-proposals/proposal-1/reject")) return { id: "proposal-1", target_block_id: "p-1", before_text: "完成工作流", after_text: "完成可恢复工作流", status: "rejected", payload: { instruction: "写得更简洁", reason: "删除重复表达", evidence_ids: ["entry-1"], save_scope: "current_resume", contains_new_fact: false } };
    if (path.endsWith("/draft") && method === "PUT") return { ...draft, ...(body as object) };
    if (path.endsWith("/versions") && method === "POST") return savedVersion;
    if (path.endsWith("/export") && method === "POST") return { files: ["杨丰铭-简历.docx", "杨丰铭-简历.pdf"] };
    if (path === "/api/versions/version-1/compare" && method === "POST") return { changes: [{ block_id: "p-1", change: "modified" }] };
    if (path === "/api/versions/version-1/restore" && method === "POST") return draft;
    if (path === "/api/versions/version-1" && method === "PATCH") return { ...savedVersion, ...(body as object) };
    if (path === "/api/versions/version-1/export" && method === "POST") return { files: ["版本 1.docx", "版本 1.pdf"] };
    throw new Error(`unexpected ${method} ${path}`);
  });
  window.shadowDesktop = {
    platform: "win32", health: async () => ({ status: "ok" }), pickDocument: async () => null,
    pickBackup: async () => null,
    transcribeAudio: async () => ({ text: "" }),
    request: request as unknown as <T>(path: string, method?: string, body?: unknown) => Promise<T>,
  };
  const user = userEvent.setup();
  render(<MemoryRouter initialEntries={["/workbench/job-1"]}><NotificationProvider><Routes><Route path="/workbench/:jobId" element={<WorkbenchPage />} /></Routes></NotificationProvider></MemoryRouter>);
  expect(await screen.findByText("栏目与取舍")).toBeInTheDocument();
  await user.type(screen.getByLabelText("项目经历最多使用"), "2");
  await user.selectOptions(screen.getByLabelText("模板"), "technical_double_column");
  await user.selectOptions(screen.getByLabelText("页数"), "2");
  const projectCard = screen.getByText("项目经历").closest("article");
  const skillsCard = screen.getByText("专业技能").closest("article");
  fireEvent.dragStart(skillsCard!); fireEvent.dragOver(projectCard!); fireEvent.drop(projectCard!);
  await user.click(screen.getByRole("button", { name: "生成简历" }));
  expect(await screen.findByDisplayValue("完成工作流")).toBeInTheDocument();
  expect(await screen.findByText("简历已生成，请核实 AI 补充内容")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "取消提醒并保留简历" }));
  expect(screen.queryByText("简历已生成，请核实 AI 补充内容")).not.toBeInTheDocument();
  expect(screen.getByDisplayValue("完成工作流")).toBeInTheDocument();
  const putConfig = request.mock.calls.find((call) => call[0].endsWith("/resume-config") && call[1] === "PUT");
  expect((putConfig?.[2] as { config: typeof config }).config.template).toBe("technical_double_column");
  expect((putConfig?.[2] as { config: typeof config }).config.page_target).toBe(2);
  expect((putConfig?.[2] as { config: typeof config }).config.sections.find((section) => section.section_key === "project")?.max_entries).toBe(2);
  await user.click(screen.getByRole("button", { name: "润色" }));
  await user.click(screen.getByText("补充经历"));
  await user.click(screen.getByRole("button", { name: "开始润色" }));
  expect(await screen.findByText("确认 AI 编造风险")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "我已了解风险，继续编造" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/jobs/job-1/polish", "POST", { methods: ["add_experience"], allow_fabrication: true }));
  expect(screen.queryByText("确认 AI 编造风险")).not.toBeInTheDocument();

  await user.clear(screen.getByLabelText("编辑影子项目"));
  await user.type(screen.getByLabelText("编辑影子项目"), "完成可恢复工作流");
  await user.click(screen.getByRole("button", { name: "保存草稿" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/jobs/job-1/draft", "PUT", expect.any(Object)));
  await user.click(screen.getByRole("button", { name: "保存版本" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/jobs/job-1/versions", "POST", { name: "版本 1", notes: null }));
  await user.click(screen.getByRole("button", { name: "导出" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/jobs/job-1/export", "POST", expect.objectContaining({ formats: ["docx", "pdf"] })));
  await user.click(screen.getByRole("button", { name: "历史版本" }));
  expect(await screen.findByText("版本 1")).toBeInTheDocument();
  vi.spyOn(window, "prompt").mockReturnValueOnce("投递版").mockReturnValueOnce("已核对");
  await user.click(screen.getByRole("button", { name: "改名/备注" }));
  expect(await screen.findByText("投递版")).toBeInTheDocument();
  expect(screen.getByText("已核对")).toBeInTheDocument();
  await user.click(screen.getAllByRole("button", { name: "导出" })[1]);
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/versions/version-1/export", "POST", expect.objectContaining({ formats: ["docx", "pdf"] })));
  await user.click(screen.getByRole("button", { name: "对比" }));
  expect(await screen.findByText("对比结果：1 个内容块发生变化")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "恢复" }));
  expect(await screen.findByText("当前草稿可能有尚未保存为历史版本的修改。请选择：")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "放弃当前修改并恢复" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/versions/version-1/restore", "POST", undefined));
  await user.click(screen.getByRole("button", { name: "历史版本" }));
  await user.type(screen.getByLabelText("修改要求"), "写得更简洁");
  await user.click(screen.getByRole("button", { name: "生成修改建议" }));
  expect(await screen.findByText("修改前后对比")).toBeInTheDocument();
  expect(screen.getByText("删除重复表达")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "拒绝" }));
  expect(await screen.findByText("已拒绝")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "语音输入" }));
  expect(await screen.findByText(/文字输入仍可使用/)).toBeInTheDocument();
});
