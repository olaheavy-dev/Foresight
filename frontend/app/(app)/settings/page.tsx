import { SectionPage } from "@/components/SectionPage";

export const metadata = { title: "Settings · Foresight" };

export default function SettingsPage() {
  return (
    <SectionPage
      title="Settings"
      lede="Your profile, buffer and goals, digest delivery, and your data: export or delete it at any time."
      what="Settings"
    />
  );
}
