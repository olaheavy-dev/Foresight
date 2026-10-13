import { SectionPage } from "@/components/SectionPage";

export const metadata = { title: "AI Workspace · Foresight" };

export default function WorkspacePage() {
  return (
    <SectionPage
      title="AI Workspace"
      lede="Ask anything about your money. Every number is computed from your transactions and the forecast engine, then checked before you see it."
      what="Questions and checked answers"
    />
  );
}
