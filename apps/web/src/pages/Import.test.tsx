import { afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { NotificationProvider } from "../components/Notifications";
import { ImportPage } from "./Import";

afterEach(() => {
  delete window.shadowDesktop;
  vi.restoreAllMocks();
});

test("import candidates are shown beside source and require explicit confirmation", async () => {
  const request = vi.fn(async (path: string) => {
    if (path === "/api/imports/from-path") return {
      id: "document-1", original_name: "resume.docx", status: "parsed",
      parsed: { pages: [{ page_number: 1, blocks: [{ block_id: "paragraph-0", text: "项目经历：影子简历助手" }] }] },
      candidates: [{ id: "candidate-1", section_key: "project", title: "影子简历助手", payload: { content: "完成本地简历工作流" }, source_locator: { page: 1, block_id: "paragraph-0" }, confidence: "uncertain", duplicate_of: "entry-old" }],
    };
    if (path === "/api/imports/document-1/confirm") return { accepted: 1, ignored: 0 };
    throw new Error(`unexpected ${path}`);
  });
  window.shadowDesktop = {
    platform: "win32", health: async () => ({ status: "ok" }),
    pickDocument: async () => "C:\\fixtures\\resume.docx",
    pickBackup: async () => null,
    transcribeAudio: async () => ({ text: "" }),
    request: request as unknown as <T>(path: string, method?: string, body?: unknown) => Promise<T>,
  };
  const user = userEvent.setup();
  render(<MemoryRouter><NotificationProvider><ImportPage /></NotificationProvider></MemoryRouter>);
  await user.click(screen.getByRole("button", { name: "选择文件" }));
  expect(await screen.findByText("项目经历：影子简历助手")).toBeInTheDocument();
  expect(screen.getByText("归类不确定")).toBeInTheDocument();
  expect(screen.getByText("疑似重复")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "确认写入资料库" }));
  expect(await screen.findByText("已写入 1 条，忽略 0 条")).toBeInTheDocument();
});
