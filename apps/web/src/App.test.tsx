import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";
import { NotificationProvider } from "./components/Notifications";

function renderApp() {
  return render(<MemoryRouter><NotificationProvider><App /></NotificationProvider></MemoryRouter>);
}

test("renders the Chinese application shell", () => {
  renderApp();
  expect(screen.getByRole("heading", { name: "首页" })).toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "主导航" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "把真实经历，整理成更贴近目标岗位的简历。" })).toBeInTheDocument();
  expect(document.querySelector(".home-hero")).toBeInTheDocument();
  expect(document.querySelector(".brand-mark")).toHaveTextContent("影");
});

test("navigates to profile", async () => {
  const user = userEvent.setup();
  renderApp();
  await user.click(screen.getByRole("link", { name: "个人资料" }));
  expect(screen.getByRole("heading", { name: "个人资料" })).toBeInTheDocument();
});
