import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  DEFAULT_LOCAL_SETTINGS,
  LOCAL_SETTINGS_KEY,
  getLocalSettings,
} from "@/core/settings/local";

const storage = new Map<string, string>();

const localStorageStub = {
  getItem: vi.fn((key: string) => storage.get(key) ?? null),
  setItem: vi.fn((key: string, value: string) => {
    storage.set(key, value);
  }),
  removeItem: vi.fn((key: string) => {
    storage.delete(key);
  }),
  clear: vi.fn(() => {
    storage.clear();
  }),
};

beforeEach(() => {
  storage.clear();
  vi.stubGlobal("window", {});
  vi.stubGlobal("localStorage", localStorageStub);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("defaults follow-up suggestions to disabled", () => {
  expect(DEFAULT_LOCAL_SETTINGS.followups.enabled).toBe(false);
  expect(getLocalSettings().followups.enabled).toBe(false);
});

test("fills missing follow-up settings when loading old storage", () => {
  storage.set(
    LOCAL_SETTINGS_KEY,
    JSON.stringify({
      notification: { enabled: false },
    }),
  );

  const settings = getLocalSettings();

  expect(settings.notification.enabled).toBe(false);
  expect(settings.followups.enabled).toBe(false);
});

test("preserves stored follow-up suggestion setting", () => {
  storage.set(
    LOCAL_SETTINGS_KEY,
    JSON.stringify({
      followups: { enabled: false },
    }),
  );

  const settings = getLocalSettings();

  expect(settings.followups.enabled).toBe(false);
  expect(settings.tokenUsage.headerTotal).toBe(true);
});
