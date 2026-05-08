import type { Metadata } from "next";

import { ReadAgentWorkbench } from "@/features/read-agent/workbench";

export const metadata: Metadata = {
  title: "Read Agent WebUI",
};

export default function ReadAgentPage() {
  return <ReadAgentWorkbench />;
}
