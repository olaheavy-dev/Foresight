import { SectionPage } from "@/components/SectionPage";

export const metadata = { title: "Activity · Foresight" };

export default function ActivityPage() {
  return (
    <SectionPage
      title="Activity"
      lede="What Foresight did and when: insights, checked and rejected recommendations, forecast updates, imports and agent runs."
      what="Activity feed"
    />
  );
}
