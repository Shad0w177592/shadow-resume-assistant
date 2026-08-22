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
});

test("navigates to profile", async () => {
  const user = userEvent.setup();
  renderApp();
  await user.click(screen.getByRole("link", { name: "个人资料" }));
  expect(screen.getByRole("heading", { name: "个人资料" })).toBeInTheDocument();
});
