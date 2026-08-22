import { afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { NotificationProvider } from "../components/Notifications";
import { WorkbenchLandingPage } from "./WorkbenchLanding";

afterEach(() => {
  delete window.shadowDesktop;
  vi.restoreAllMocks();
});

test("lists target jobs as direct workbench links", async () => {
  const request = vi.fn(async (path: string) => {
    if (path === "/api/jobs") {
      return [{
        id: "job-1",
        company: "影子科技",
        title: "AI Agent 产品经理",
        jd_text: "负责 AI Agent 产品",
        notes: null,
        status: "draft",
        updated_at: "",
      }];
    }
    throw new Error(`unexpected path ${path}`);
  });
  window.shadowDesktop = {
    platform: "win32",
    health: async () => ({ status: "ok" }),
    pickDocument: async () => null,
    pickBackup: async () => null,
    transcribeAudio: async () => ({ text: "" }),
    request: request as unknown as <T>(path: string, method?: string, body?: unknown) => Promise<T>,
  };

  render(
    <MemoryRouter>
      <NotificationProvider>
        <WorkbenchLandingPage />
      </NotificationProvider>
    </MemoryRouter>,
  );

  expect(screen.getByRole("heading", { name: "简历工作台" })).toBeInTheDocument();
  expect(await screen.findByText("AI Agent 产品经理")).toBeInTheDocument();
  expect(screen.getByText("影子科技")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "打开工作台" })).toHaveAttribute("href", "/workbench/job-1");
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/jobs", "GET", undefined));
});
