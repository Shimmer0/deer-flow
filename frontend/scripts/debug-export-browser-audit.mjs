import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const baseUrl =
  process.env.DEBUG_EXPORT_AUDIT_BASE_URL ?? "http://127.0.0.1:2026";
const email = process.env.DEBUG_EXPORT_AUDIT_EMAIL ?? "test@qq.com";
const password = process.env.DEBUG_EXPORT_AUDIT_PASSWORD ?? "test@qq.com";
const outputDir =
  process.env.DEBUG_EXPORT_AUDIT_OUTPUT_DIR ??
  "/mnt/e/deerflow-agent-lab/harness-workbench/browser-audit/debug-export";
const requireRedactions =
  process.env.DEBUG_EXPORT_AUDIT_REQUIRE_REDACTIONS !== "0";

const oneByOnePngBase64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

function threadIdFromUrl(url) {
  const match = new URL(url).pathname.match(/^\/workspace\/chats\/([^/]+)$/);
  return match && match[1] !== "new" ? match[1] : null;
}

function hasHostPathLeak(value) {
  return (
    value.includes("/mnt/e/deerflow-agent-lab") ||
    value.includes("\\deerflow-agent-lab")
  );
}

function redactionReportPath(parent, key) {
  if (typeof key === "number") {
    return `${parent}[${key}]`;
  }
  if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key)) {
    return `${parent}.${key}`;
  }
  return `${parent}[${JSON.stringify(key)}]`;
}

function collectHiddenChainOfThoughtRedactionPaths(value, parent = "$") {
  if (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    value.redacted === true &&
    value.reason === "hidden_chain_of_thought"
  ) {
    return [parent];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item, index) =>
      collectHiddenChainOfThoughtRedactionPaths(
        item,
        redactionReportPath(parent, index),
      ),
    );
  }
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) =>
      collectHiddenChainOfThoughtRedactionPaths(
        item,
        redactionReportPath(parent, key),
      ),
    );
  }
  return [];
}

async function loginThroughUi(page, network) {
  await page.goto(`${baseUrl}/login?next=/workspace/chats/new`, {
    waitUntil: "domcontentloaded",
  });
  if (new URL(page.url()).pathname.startsWith("/workspace/")) {
    return { method: "existing-session", reachedWorkspace: true };
  }

  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Sign In" }).click();
  await page
    .waitForFunction(() => location.pathname.startsWith("/workspace/"), null, {
      timeout: 25_000,
    })
    .catch(() => null);

  const reachedWorkspace = new URL(page.url()).pathname.startsWith(
    "/workspace/",
  );
  const login200 = network.some(
    (entry) =>
      entry.url.includes("/api/v1/auth/login/local") && entry.status === 200,
  );
  return { method: "ui-login", reachedWorkspace, login200 };
}

async function loginThroughSameOriginFetch(page) {
  await page
    .goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded" })
    .catch(() => null);
  return await page.evaluate(
    async ({ loginEmail, loginPassword }) => {
      const response = await fetch("/api/v1/auth/login/local", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: `username=${encodeURIComponent(loginEmail)}&password=${encodeURIComponent(loginPassword)}`,
        credentials: "include",
      });
      return {
        status: response.status,
        text: (await response.text()).slice(0, 200),
      };
    },
    { loginEmail: email, loginPassword: password },
  );
}

async function waitForExport(page, threadId) {
  let last = null;
  for (let attempt = 0; attempt < 12; attempt += 1) {
    last = await page.evaluate(async (id) => {
      const response = await fetch(
        `/api/threads/${encodeURIComponent(
          id,
        )}/debug-export?include_files=true&include_file_contents=false&event_limit_per_run=2000`,
        { credentials: "include" },
      );
      const text = await response.text();
      let json = null;
      try {
        json = JSON.parse(text);
      } catch {
        // Keep text for diagnostics.
      }
      return { status: response.status, json, text };
    }, threadId);

    const run = last.json?.runs?.[0];
    if (last.status === 200 && run?.event_count > 0) {
      return last;
    }
    await page.waitForTimeout(5_000);
  }
  return last;
}

async function main() {
  await fs.mkdir(outputDir, { recursive: true });
  const uploadFile = path.join(outputDir, "debug-export-audit.png");
  await fs.writeFile(uploadFile, Buffer.from(oneByOnePngBase64, "base64"));

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    acceptDownloads: true,
    viewport: { width: 1365, height: 900 },
  });
  const page = await context.newPage();
  const network = [];
  const consoleMessages = [];
  const pageErrors = [];

  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      consoleMessages.push({ type: message.type(), text: message.text() });
    }
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    const url = response.url();
    if (url.includes("/api/") || url.includes("/workspace/")) {
      network.push({
        url,
        status: response.status(),
        method: response.request().method(),
      });
    }
  });

  let auth = await loginThroughUi(page, network);
  if (!auth.reachedWorkspace) {
    const fetchAuth = await loginThroughSameOriginFetch(page);
    auth = { ...auth, fallback: "same-origin-fetch", fetchAuth };
    if (fetchAuth.status !== 200) {
      throw new Error(
        `Debug export audit login failed: ${JSON.stringify(auth)}`,
      );
    }
  }

  await page.goto(`${baseUrl}/workspace/chats/new`, {
    waitUntil: "domcontentloaded",
  });
  const textarea = page.locator('textarea[name="message"]').first();
  await expect(textarea).toBeVisible({ timeout: 25_000 });

  await page.locator('input[type="file"]').setInputFiles(uploadFile);
  await textarea.fill(
    "Debug export browser audit: inspect this uploaded 1x1 PNG and answer one sentence.",
  );
  await page.getByLabel("Submit").click();
  await page
    .waitForFunction(
      () => /^\/workspace\/chats\/(?!new)[^/]+$/.test(location.pathname),
      null,
      {
        timeout: 35_000,
      },
    )
    .catch(() => null);

  const threadId = threadIdFromUrl(page.url());
  if (!threadId) {
    throw new Error(
      `Debug export audit did not navigate to a concrete thread: ${page.url()}`,
    );
  }

  const exportResponse = await waitForExport(page, threadId);
  const exportJson = exportResponse?.json ?? {};
  const exportText = exportResponse?.text ?? JSON.stringify(exportJson);
  const firstRun = exportJson.runs?.[0] ?? {};
  const redaction = exportJson.redaction_report?.hidden_chain_of_thought ?? {};
  const redactionMarkerPaths =
    collectHiddenChainOfThoughtRedactionPaths(exportJson);
  const archive = await page.evaluate(async (id) => {
    const response = await fetch(
      `/api/threads/${encodeURIComponent(id)}/debug-export/archive`,
      {
        credentials: "include",
      },
    );
    const buffer = await response.arrayBuffer();
    return {
      status: response.status,
      contentType: response.headers.get("content-type"),
      contentDisposition: response.headers.get("content-disposition"),
      magic: Array.from(new Uint8Array(buffer.slice(0, 4)))
        .map((byte) => byte.toString(16).padStart(2, "0"))
        .join(" "),
      size: buffer.byteLength,
    };
  }, threadId);

  const assertions = {
    authStatus: auth,
    threadId,
    exportStatus: exportResponse?.status,
    schemaVersion: exportJson.schema_version,
    runCount: Array.isArray(exportJson.runs) ? exportJson.runs.length : null,
    eventCount: firstRun.event_count ?? null,
    fileTotal: exportJson.files?.total_files ?? null,
    uploadCount: Array.isArray(exportJson.files?.sections?.uploads)
      ? exportJson.files.sections.uploads.length
      : null,
    redactionCount: redaction.count ?? null,
    redactionPaths: Array.isArray(redaction.paths)
      ? redaction.paths.slice(0, 10)
      : [],
    redactionMarkerCount: redactionMarkerPaths.length,
    redactionMarkerPaths: redactionMarkerPaths.slice(0, 10),
    redactionReportPathMismatch:
      JSON.stringify(Array.isArray(redaction.paths) ? redaction.paths : []) !==
      JSON.stringify(
        redactionMarkerPaths.slice(
          0,
          Array.isArray(redaction.paths) ? redaction.paths.length : 0,
        ),
      ),
    hostPathLeak: hasHostPathLeak(exportText),
    archive,
  };

  if (assertions.exportStatus !== 200) {
    throw new Error(`Debug export returned ${assertions.exportStatus}`);
  }
  if (assertions.schemaVersion !== 1) {
    throw new Error(
      `Unexpected debug export schema version: ${assertions.schemaVersion}`,
    );
  }
  if (!assertions.runCount || assertions.runCount < 1) {
    throw new Error("Debug export did not include any runs.");
  }
  if (!assertions.eventCount || assertions.eventCount < 1) {
    throw new Error("Debug export did not include persisted run events.");
  }
  if (
    !assertions.fileTotal ||
    assertions.fileTotal < 1 ||
    !assertions.uploadCount ||
    assertions.uploadCount < 1
  ) {
    throw new Error("Debug export did not include the uploaded image file.");
  }
  if (
    requireRedactions &&
    (!assertions.redactionCount || assertions.redactionCount < 1)
  ) {
    throw new Error(
      "Debug export did not report hidden chain-of-thought redactions.",
    );
  }
  if (assertions.redactionCount !== assertions.redactionMarkerCount) {
    throw new Error(
      `Debug export redaction count does not match marker count: report=${assertions.redactionCount} markers=${assertions.redactionMarkerCount}`,
    );
  }
  if (assertions.redactionReportPathMismatch) {
    throw new Error(
      "Debug export redaction report paths do not match redaction marker paths.",
    );
  }
  if (assertions.hostPathLeak) {
    throw new Error("Debug export leaked a host filesystem path.");
  }
  if (
    archive.status !== 200 ||
    archive.contentType !== "application/zip" ||
    archive.magic !== "50 4b 03 04"
  ) {
    throw new Error(
      `Debug export archive check failed: ${JSON.stringify(archive)}`,
    );
  }

  const exportButton = page.getByRole("button", { name: /导出|Export/ }).last();
  await expect(exportButton).toBeVisible({ timeout: 25_000 });
  await exportButton.click();
  await expect(page.getByText(/导出调试 JSON|Export debug JSON/)).toBeVisible();

  const [debugJsonDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByText(/导出调试 JSON|Export debug JSON/).click(),
  ]);
  const debugJsonDownloadFile = path.join(outputDir, "debug-export-ui.json");
  await debugJsonDownload.saveAs(debugJsonDownloadFile);
  const debugJsonDownloadText = await fs.readFile(
    debugJsonDownloadFile,
    "utf8",
  );
  const debugJsonDownloadPayload = JSON.parse(debugJsonDownloadText);
  const debugJsonDownloadRedaction =
    debugJsonDownloadPayload.redaction_report?.hidden_chain_of_thought ?? {};
  const debugJsonDownloadRedactionMarkerPaths =
    collectHiddenChainOfThoughtRedactionPaths(debugJsonDownloadPayload);

  await exportButton.click();
  const [debugArchiveDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByText(/导出调试 ZIP|Export debug ZIP/).click(),
  ]);
  const debugArchiveDownloadFile = path.join(outputDir, "debug-export-ui.zip");
  await debugArchiveDownload.saveAs(debugArchiveDownloadFile);
  const debugArchiveDownloadBytes = await fs.readFile(debugArchiveDownloadFile);
  const debugArchiveDownloadMagic = Array.from(
    debugArchiveDownloadBytes.subarray(0, 4),
  )
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join(" ");

  if (debugJsonDownloadPayload.schema_version !== 1) {
    throw new Error(
      `UI debug JSON download has unexpected schema: ${debugJsonDownloadPayload.schema_version}`,
    );
  }
  if (hasHostPathLeak(debugJsonDownloadText)) {
    throw new Error("UI debug JSON download leaked a host filesystem path.");
  }
  if (
    requireRedactions &&
    (!debugJsonDownloadRedaction.count || debugJsonDownloadRedaction.count < 1)
  ) {
    throw new Error(
      "UI debug JSON download did not include redaction report counts.",
    );
  }
  if (
    debugJsonDownloadRedaction.count !==
    debugJsonDownloadRedactionMarkerPaths.length
  ) {
    throw new Error(
      `UI debug JSON redaction count does not match marker count: report=${debugJsonDownloadRedaction.count} markers=${debugJsonDownloadRedactionMarkerPaths.length}`,
    );
  }
  if (debugArchiveDownloadMagic !== "50 4b 03 04") {
    throw new Error(
      `UI debug ZIP download has invalid magic: ${debugArchiveDownloadMagic}`,
    );
  }

  const report = {
    baseUrl,
    email,
    uploadFile,
    assertions: {
      ...assertions,
      uiDownloads: {
        jsonSuggestedFilename: debugJsonDownload.suggestedFilename(),
        jsonFile: debugJsonDownloadFile,
        jsonSchemaVersion: debugJsonDownloadPayload.schema_version,
        jsonRedactionCount: debugJsonDownloadRedaction.count ?? null,
        jsonRedactionMarkerCount: debugJsonDownloadRedactionMarkerPaths.length,
        jsonHostPathLeak: hasHostPathLeak(debugJsonDownloadText),
        archiveSuggestedFilename: debugArchiveDownload.suggestedFilename(),
        archiveFile: debugArchiveDownloadFile,
        archiveMagic: debugArchiveDownloadMagic,
        archiveBytes: debugArchiveDownloadBytes.byteLength,
      },
    },
    networkFailures: network.filter((entry) => entry.status >= 400),
    consoleMessages,
    pageErrors,
  };
  const reportFile = path.join(outputDir, "report.json");
  await fs.writeFile(reportFile, `${JSON.stringify(report, null, 2)}\n`);
  await browser.close();

  console.log(
    JSON.stringify(
      {
        reportFile,
        assertions: report.assertions,
        networkFailures: report.networkFailures,
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
