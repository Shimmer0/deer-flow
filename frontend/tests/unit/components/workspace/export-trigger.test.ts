import { expect, test } from "vitest";

import { shouldShowExportTrigger } from "@/components/workspace/export-trigger";

test("shows export trigger for a concrete thread even when visible messages are empty", () => {
  expect(
    shouldShowExportTrigger({ threadId: "thread-1", messageCount: 0 }),
  ).toBe(true);
});

test("hides export trigger for the new-chat placeholder when visible messages are empty", () => {
  expect(shouldShowExportTrigger({ threadId: "new", messageCount: 0 })).toBe(
    false,
  );
});

test("shows export trigger when visible messages exist", () => {
  expect(shouldShowExportTrigger({ threadId: "new", messageCount: 1 })).toBe(
    true,
  );
});
