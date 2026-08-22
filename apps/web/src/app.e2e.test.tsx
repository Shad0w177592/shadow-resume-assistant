import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";
import { NotificationProvider } from "./components/Notifications";

test("all primary navigation destinations are reachable", async () => {
  const user = userEvent.setup();
  render(<MemoryRouter><NotificationProvider><App /></NotificationProvider></MemoryRouter>);
  for (const label of ["个人资料", "目标岗位", "简历工作台", "设置", "首页"]) {
    await user.click(screen.getByRole("link", { name: label }));
    expect(screen.getByRole("heading", { name: label })).toBeInTheDocument();
  }
});
