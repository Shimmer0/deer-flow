import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.describe("Read Agent chat workspace", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page);
  });

  test("redirects /read-agent into chat and keeps the read-agent workspace visible", async ({
    page,
  }) => {
    await page.goto("/read-agent");

    await expect(page).toHaveURL(/\/workspace\/chats\/new\?readAgent=1/);
    await expect(
      page.getByRole("textbox", { name: /今天我能为你做些什么/ }),
    ).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("read-agent-chat-shell")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "结构图纸识读工作台" }),
    ).toBeVisible();
    const chatInputBox = await page
      .getByRole("textbox", { name: /今天我能为你做些什么/ })
      .boundingBox();
    const workbenchBox = await page
      .getByTestId("read-agent-chat-shell")
      .boundingBox();
    expect(chatInputBox).not.toBeNull();
    expect(workbenchBox).not.toBeNull();
    expect(chatInputBox!.x + chatInputBox!.width).toBeLessThanOrEqual(
      workbenchBox!.x,
    );
    await expect(
      page
        .getByTestId("read-agent-chat-shell")
        .getByText("PL-S-001", {
          exact: true,
        })
        .first(),
    ).toBeVisible();
    await expect(page.getByText("识图进度")).toBeVisible();
    await expect(page.getByText("图纸语义视图")).toBeVisible();
    await expect(page.getByText("提交前校验", { exact: true })).toBeVisible();
    await expect(page.getByText("开发者视图")).toBeVisible();
    await expect(page.getByText("Stage JSON")).toBeHidden();
  });

  test("preserves read-agent mode after the first chat message creates a thread", async ({
    page,
  }) => {
    await page.goto("/workspace/chats/new?readAgent=1");

    const textarea = page.getByRole("textbox", {
      name: /今天我能为你做些什么/,
    });
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("读取这张结构图并展示识图阶段");
    await textarea.press("Enter");

    expect(page.url()).toContain("readAgent=1");
    await expect(page.getByTestId("read-agent-chat-shell")).toBeVisible();
    await expect(page.getByText("Hello from DeerFlow!")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("识图工具")).toBeVisible();
  });
});
