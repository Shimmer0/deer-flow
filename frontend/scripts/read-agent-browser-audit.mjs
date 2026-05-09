import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const baseUrl =
  process.env.READ_AGENT_AUDIT_BASE_URL ?? "http://127.0.0.1:2026";
const outputDir =
  process.env.READ_AGENT_AUDIT_OUTPUT_DIR ??
  "/mnt/e/deerflow-agent-lab/harness-workbench/browser-audit/read-agent";

function compactText(value, limit = 2000) {
  return value.replace(/\s+/g, " ").trim().slice(0, limit);
}

function rectsOverlap(a, b) {
  return (
    a.x < b.x + b.width &&
    a.x + a.width > b.x &&
    a.y < b.y + b.height &&
    a.y + a.height > b.y
  );
}

async function screenshot(page, name) {
  const file = path.join(outputDir, name);
  await page.screenshot({ path: file, fullPage: true });
  const stat = await fs.stat(file);
  return { file, bytes: stat.size };
}

async function main() {
  await fs.mkdir(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  const network = [];
  const consoleMessages = [];
  const pageErrors = [];

  const email = `browser-audit-${Date.now()}@example.com`;
  const password = `StrongPass${Date.now()}!a`;
  const registerResponse = await context.request.post(
    `${baseUrl}/api/v1/auth/register`,
    {
      data: { email, password },
    },
  );

  const page = await context.newPage();
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      consoleMessages.push({ type: message.type(), text: message.text() });
    }
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    const url = response.url();
    if (url.includes("/api/") || url.includes("/read-agent")) {
      network.push({
        url,
        status: response.status(),
        method: response.request().method(),
      });
    }
  });
  page.on("requestfailed", (request) => {
    const url = request.url();
    if (!url.includes("/api/") && !url.includes("/read-agent")) {
      return;
    }
    network.push({
      url,
      status: 0,
      method: request.method(),
      failure: request.failure()?.errorText,
    });
  });

  await page.goto(`${baseUrl}/read-agent`, { waitUntil: "domcontentloaded" });
  await expect(
    page.getByRole("heading", { name: "结构图纸识读工作台" }),
  ).toBeVisible();
  await expect(page.getByText("提交前校验", { exact: true })).toBeVisible();
  const chatInputBox = await page
    .getByRole("textbox", { name: /今天我能为你做些什么/ })
    .boundingBox();
  const workbenchBox = await page
    .getByTestId("read-agent-chat-shell")
    .boundingBox();
  if (!chatInputBox || !workbenchBox) {
    throw new Error(
      "Read Agent layout audit failed: missing chat input or workbench bounds.",
    );
  }
  const chatInputOverlapsWorkbench = rectsOverlap(chatInputBox, workbenchBox);
  if (chatInputOverlapsWorkbench) {
    throw new Error(
      `Read Agent layout audit failed: chat input overlaps workbench. input=${JSON.stringify(
        chatInputBox,
      )} workbench=${JSON.stringify(workbenchBox)}`,
    );
  }
  const processingShot = await screenshot(page, "01-processing.png");

  await expect(page.getByText("已由你锁定")).toBeVisible();
  await expect(
    page.getByTestId("openseadragon-evidence-viewer"),
  ).toHaveAttribute("data-viewer-engine", "openseadragon");
  await page.getByRole("textbox", { name: "梁号" }).fill("KL3(2A)");
  await page.locator("summary").filter({ hasText: "开发者视图" }).click();
  await page.getByRole("button", { name: "差异" }).click();
  await expect(page.getByTestId("json-diff-summary")).toContainText(/变更路径/);
  const diffSummary = await page.getByTestId("json-diff-summary").innerText();
  const editDiffShot = await screenshot(page, "02-edit-diff.png");

  await page.getByRole("button", { name: "提交修改" }).click();
  await expect(page.getByText("1 条事件")).toBeVisible();
  await expect(page.getByText("KL3(2A)").first()).toBeVisible();
  const committedShot = await screenshot(page, "03-committed.png");

  const canvasBytes = await page
    .getByTestId("read-agent-3d-canvas")
    .evaluate((node) => {
      if (!(node instanceof HTMLCanvasElement)) return 0;
      return node.toDataURL("image/png").length;
    });
  const layout = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    bodyText: document.body.innerText,
  }));

  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    storageState: await context.storageState(),
  });
  const mobilePage = await mobile.newPage();
  await mobilePage.goto(`${baseUrl}/read-agent`, {
    waitUntil: "domcontentloaded",
  });
  await expect(
    mobilePage.getByRole("heading", { name: "结构图纸识读工作台" }),
  ).toBeVisible();
  await expect(
    mobilePage.getByText("示意模型，不可用于工程计算").first(),
  ).toBeVisible();
  const mobileLayout = await mobilePage.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  const mobileShot = await screenshot(mobilePage, "04-mobile.png");
  await mobile.close();

  const assetResponses = network.filter((entry) =>
    entry.url.includes("/api/read-agent/assets/"),
  );
  const apiFailures = network.filter(
    (entry) => entry.status >= 400 || entry.status === 0,
  );
  const report = {
    baseUrl,
    registerStatus: registerResponse.status(),
    screenshots: [processingShot, editDiffShot, committedShot, mobileShot],
    assertions: {
      headingVisible: true,
      operationPreviewVisible: true,
      editLockVisible: true,
      openseadragonEngine: await page
        .getByTestId("openseadragon-evidence-viewer")
        .getAttribute("data-viewer-engine"),
      diffSummary,
      commitAuditVisible: true,
      canvasPngBytes: canvasBytes,
      chatInputOverlapsWorkbench,
      chatInputBox,
      workbenchBox,
      desktopNoHorizontalOverflow: layout.scrollWidth <= layout.clientWidth,
      mobileNoHorizontalOverflow:
        mobileLayout.scrollWidth <= mobileLayout.clientWidth,
    },
    assetResponses,
    apiFailures,
    consoleMessages,
    pageErrors,
    bodyTextExcerpt: compactText(layout.bodyText),
  };

  const reportFile = path.join(outputDir, "report.json");
  await fs.writeFile(reportFile, `${JSON.stringify(report, null, 2)}\n`);
  await browser.close();

  console.log(
    JSON.stringify(
      {
        reportFile,
        screenshots: report.screenshots,
        assertions: report.assertions,
        assetResponses,
        apiFailures,
        consoleMessages: consoleMessages.length,
        pageErrors: pageErrors.length,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
