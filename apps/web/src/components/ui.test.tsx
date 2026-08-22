import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Dialog, Progress, Stepper, TextInput } from "./ui";

test("input exposes its validation error", () => {
  render(<TextInput label="手机号" error="手机号格式不正确" />);
  expect(screen.getByRole("textbox", { name: "手机号" })).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("alert")).toHaveTextContent("手机号格式不正确");
});

test("dialog can be closed from its accessible close button", async () => {
  const onClose = vi.fn();
  render(<Dialog open title="确认删除" onClose={onClose}>不可恢复</Dialog>);
  await userEvent.click(screen.getByRole("button", { name: "关闭" }));
  expect(onClose).toHaveBeenCalledOnce();
});

test("progress clamps values and stepper marks current step", () => {
  render(<><Progress label="导入进度" value={120} /><Stepper steps={["导入", "确认"]} current={1} /></>);
  expect(screen.getByRole("progressbar", { name: "导入进度" })).toHaveAttribute("value", "100");
  expect(screen.getByText("确认").closest("li")).toHaveAttribute("aria-current", "step");
});

