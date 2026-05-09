import type { Metadata } from "next";

import { ReadAgentWorkbench } from "@/features/read-agent/workbench";

export const metadata: Metadata = {
  title: "结构图纸识读工作台",
};

export default function ReadAgentPage() {
  return <ReadAgentWorkbench />;
}
