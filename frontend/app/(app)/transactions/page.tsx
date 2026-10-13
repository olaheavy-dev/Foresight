import { SectionPage } from "@/components/SectionPage";

export const metadata = { title: "Transactions · Foresight" };

export default function TransactionsPage() {
  return (
    <SectionPage
      title="Transactions"
      lede="Every transaction with its category and where it came from. Correct a category once and Foresight remembers it."
      what="Transactions, review queue, recurring and imports"
    />
  );
}
