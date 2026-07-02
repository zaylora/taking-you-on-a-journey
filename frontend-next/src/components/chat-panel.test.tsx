import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { ChatPanel } from "./chat-panel";

const renderChatPanel = (ui: React.ReactElement) =>
  render(<TooltipProvider>{ui}</TooltipProvider>);

describe("ChatPanel", () => {
  it("renders assistant markdown with GFM elements", () => {
    renderChatPanel(
      <ChatPanel
        messages={[
          {
            id: "assistant-1",
            role: "assistant",
            parts: [
              {
                type: "text",
                text:
                  "### 广州路线\n\n" +
                  "**上午**：陈家祠\n\n" +
                  "- 沙面\n" +
                  "- 永庆坊\n\n" +
                  "[查看攻略](https://example.com/guide)",
              },
            ],
          },
        ]}
        activeNodeLabel={null}
        loading={false}
        onSubmit={vi.fn()}
        onStop={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "广州路线", level: 3 }),
    ).toBeVisible();
    expect(screen.getByText("上午")).toBeVisible();
    expect(screen.getByRole("list")).toBeVisible();
    expect(screen.getByRole("button", { name: "查看攻略" })).toBeVisible();
    expect(screen.getByTestId("ai-elements-conversation")).toBeVisible();
    expect(screen.getByTestId("ai-elements-prompt-input")).toBeVisible();
  });

  it("shows historical messages in the same conversation", () => {
    renderChatPanel(
      <ChatPanel
        messages={[
          {
            id: "user-1",
            role: "user",
            parts: [{ type: "text", text: "第一轮：广州三天" }],
          },
          {
            id: "assistant-1",
            role: "assistant",
            parts: [{ type: "text", text: "可以，先安排老城和珠江。" }],
          },
          {
            id: "user-2",
            role: "user",
            parts: [{ type: "text", text: "第二轮：加一点亲子活动" }],
          },
        ]}
        activeNodeLabel={null}
        loading={false}
        onSubmit={vi.fn()}
        onStop={vi.fn()}
      />,
    );

    expect(screen.getByText("第一轮：广州三天")).toBeVisible();
    expect(screen.getByText("可以，先安排老城和珠江。")).toBeVisible();
    expect(screen.getByText("第二轮：加一点亲子活动")).toBeVisible();
    expect(screen.getAllByTestId("ai-elements-message")).toHaveLength(3);
  });

  it("renders reasoning and tools without generic loading copy", () => {
    renderChatPanel(
      <ChatPanel
        messages={[
          {
            id: "user-1",
            role: "user",
            parts: [{ type: "text", text: "帮我规划广州三天" }],
          },
          {
            id: "assistant-1",
            role: "assistant",
            parts: [
              { type: "text", text: "我先检查天气和路线。" },
              {
                type: "tool",
                tool: "weather",
                label: "查询广州天气",
                status: "running",
              },
              { type: "text", text: "### 行程建议\n\n第一天去沙面。" },
            ],
          },
        ]}
        activeNodeLabel={null}
        loading
        onSubmit={vi.fn()}
        onStop={vi.fn()}
      />,
    );

    expect(screen.getByTestId("ai-elements-reasoning")).toBeVisible();
    expect(screen.getByText("我先检查天气和路线。")).toBeVisible();
    expect(screen.getByTestId("ai-elements-tool")).toBeVisible();
    expect(screen.getByText("查询广州天气")).toBeVisible();
    expect(screen.getByText("运行中")).toBeVisible();
    expect(screen.queryByText("正在生成")).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "行程建议", level: 3 }),
    ).toBeVisible();
  });

  it("keeps the conversation wrapper from becoming a second scroll container", () => {
    renderChatPanel(
      <ChatPanel
        messages={[
          {
            id: "assistant-1",
            role: "assistant",
            parts: [{ type: "text", text: "广州三天两晚路线。" }],
          },
        ]}
        activeNodeLabel={null}
        loading={false}
        onSubmit={vi.fn()}
        onStop={vi.fn()}
      />,
    );

    expect(screen.getByTestId("ai-elements-conversation")).toHaveClass(
      "overflow-y-hidden",
    );
  });

  it("hides assistant message actions while the latest answer is generating", () => {
    renderChatPanel(
      <ChatPanel
        messages={[
          {
            id: "assistant-1",
            role: "assistant",
            parts: [{ type: "text", text: "广州三天两晚路线生成中。" }],
          },
        ]}
        activeNodeLabel={null}
        loading
        onSubmit={vi.fn()}
        onStop={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "复制" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "赞" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "踩" })).not.toBeInTheDocument();
  });

  it("uses the active node label for transient thinking output", () => {
    renderChatPanel(
      <ChatPanel
        messages={[
          {
            id: "user-1",
            role: "user",
            parts: [{ type: "text", text: "查一下广州美食" }],
          },
        ]}
        activeNodeLabel="正在思考..."
        loading
        onSubmit={vi.fn()}
        onStop={vi.fn()}
      />,
    );

    expect(screen.getByText("正在思考...")).toBeVisible();
    expect(screen.queryByText("正在生成")).not.toBeInTheDocument();
  });

  it("submits and stops through the AI Elements prompt input", async () => {
    const onSubmit = vi.fn();
    const onStop = vi.fn();
    const { rerender } = renderChatPanel(
      <ChatPanel
        messages={[]}
        activeNodeLabel={null}
        loading={false}
        onSubmit={onSubmit}
        onStop={onStop}
      />,
    );

    fireEvent.change(screen.getByLabelText("发送消息"), {
      target: { value: "帮我规划广州三天两晚" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith("帮我规划广州三天两晚"),
    );

    rerender(
      <TooltipProvider>
        <ChatPanel
          messages={[]}
          activeNodeLabel={null}
          loading
          onSubmit={onSubmit}
          onStop={onStop}
        />
      </TooltipProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "停止生成" }));

    expect(onStop).toHaveBeenCalledTimes(1);
  });
});
