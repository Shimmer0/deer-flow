"use client";

import { Download, FileArchive, FileJson, FileText } from "lucide-react";
import { useCallback } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import {
  exportThreadAsJSON,
  exportThreadAsMarkdown,
} from "@/core/threads/export";
import type { AgentThread } from "@/core/threads/types";

import { useThread } from "./messages/context";
import { Tooltip } from "./tooltip";

function filenameFromContentDisposition(value: string | null) {
  if (!value) {
    return null;
  }
  const match = /filename="?([^";]+)"?/i.exec(value);
  return match?.[1] ?? null;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function shouldShowExportTrigger({
  threadId,
  messageCount,
}: {
  threadId: string;
  messageCount: number;
}) {
  return messageCount > 0 || (threadId.length > 0 && threadId !== "new");
}

export function ExportTrigger({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  const { thread } = useThread();

  const messages = thread.messages;

  const handleExport = useCallback(
    (format: "markdown" | "json") => {
      if (messages.length === 0) {
        toast.error(t.conversation.noMessages);
        return;
      }
      const agentThread = {
        thread_id: threadId,
        updated_at: new Date().toISOString(),
        values: thread.values,
      } as AgentThread;

      if (format === "markdown") {
        exportThreadAsMarkdown(agentThread, messages);
      } else {
        exportThreadAsJSON(agentThread, messages);
      }
      toast.success(t.common.exportSuccess);
    },
    [messages, thread.values, threadId, t],
  );

  const handleDebugExport = useCallback(
    async (format: "json" | "archive") => {
      try {
        const endpoint =
          format === "json"
            ? `/api/threads/${encodeURIComponent(threadId)}/debug-export`
            : `/api/threads/${encodeURIComponent(threadId)}/debug-export/archive`;
        const response = await fetch(endpoint, { credentials: "include" });
        if (!response.ok) {
          throw new Error(`Debug export failed: ${response.status}`);
        }
        const blob = await response.blob();
        const fallbackName =
          format === "json"
            ? `deerflow-debug-export-${threadId}.json`
            : `deerflow-debug-export-${threadId}.zip`;
        downloadBlob(
          blob,
          filenameFromContentDisposition(
            response.headers.get("content-disposition"),
          ) ?? fallbackName,
        );
        toast.success(t.common.exportSuccess);
      } catch {
        toast.error(t.common.exportFailed);
      }
    },
    [threadId, t],
  );

  if (!shouldShowExportTrigger({ threadId, messageCount: messages.length })) {
    return null;
  }

  return (
    <DropdownMenu>
      <Tooltip content={t.common.export}>
        <DropdownMenuTrigger asChild>
          <Button
            className="text-muted-foreground hover:text-foreground"
            variant="ghost"
          >
            <Download />
            {t.common.export}
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => handleExport("markdown")}>
          <FileText className="text-muted-foreground" />
          <span>{t.common.exportAsMarkdown}</span>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => handleExport("json")}>
          <FileJson className="text-muted-foreground" />
          <span>{t.common.exportAsJSON}</span>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void handleDebugExport("json")}>
          <FileJson className="text-muted-foreground" />
          <span>{t.common.exportDebugJSON}</span>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void handleDebugExport("archive")}>
          <FileArchive className="text-muted-foreground" />
          <span>{t.common.exportDebugArchive}</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
