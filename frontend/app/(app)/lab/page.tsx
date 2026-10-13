import { SectionPage } from "@/components/SectionPage";

export const metadata = { title: "Decision Lab · Foresight" };

export default function LabPage() {
  return (
    <SectionPage
      title="Decision Lab"
      lede="Test a decision before you make it: compare your current path with a what-if on the same simulated paths."
      what="Scenario comparison"
    />
  );
}
