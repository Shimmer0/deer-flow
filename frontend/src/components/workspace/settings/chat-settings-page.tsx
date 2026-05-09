"use client";

import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";

import { SettingsSection } from "./settings-section";

export function ChatSettingsPage() {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();

  const handleFollowupsEnabledChange = (enabled: boolean) => {
    setSettings("followups", { enabled });
  };

  return (
    <SettingsSection
      title={t.settings.chat.title}
      description={t.settings.chat.description}
    >
      <div className="border-border flex items-center justify-between gap-4 rounded-md border p-4">
        <div className="space-y-1">
          <div className="text-sm font-medium">
            {t.settings.chat.followupSuggestionsTitle}
          </div>
          <div className="text-muted-foreground text-sm">
            {t.settings.chat.followupSuggestionsDescription}
          </div>
        </div>
        <Switch
          aria-label={t.settings.chat.followupSuggestionsTitle}
          checked={settings.followups.enabled}
          onCheckedChange={handleFollowupsEnabledChange}
        />
      </div>
    </SettingsSection>
  );
}
