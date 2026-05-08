import { expect, test } from "@playwright/test";

test("read agent workbench deploys and commits an audited operation", async ({
  page,
}) => {
  await page.goto("/read-agent");

  await expect(page.getByRole("heading", { name: "Read Agent WebUI" })).toBeVisible();
  await expect(page.getByText("示意模型，不可用于工程计算").first()).toBeVisible();
  await expect(page.getByText("Operation Preview", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: /Edit/ }).click();
  await page.locator("input").first().fill("KL3(2A)");
  await page.getByRole("button", { name: /Commit/ }).click();

  await expect(page.getByText("1 events")).toBeVisible();
  await expect(page.getByRole("button", { name: "KL3(2A)" })).toBeVisible();

  const canvas = page.getByTestId("read-agent-3d-canvas");
  await expect(canvas).toBeVisible();
  await expect
    .poll(async () => {
      return await canvas.evaluate((node) => {
        if (!(node instanceof HTMLCanvasElement)) return 0;
        return node.toDataURL("image/png").length;
      });
    })
    .toBeGreaterThan(3_000);
});
