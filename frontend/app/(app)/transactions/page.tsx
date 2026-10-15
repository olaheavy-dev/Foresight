import { SectionPage } from "@/components/SectionPage";
import { type LedgerTab, Transactions } from "@/components/transactions/Transactions";
import { isShipped } from "@/lib/flags";
import { loadShell } from "@/lib/server";

export const metadata = { title: "Transactions · Foresight" };
export const dynamic = "force-dynamic";

const TABS: LedgerTab[] = ["all", "review", "recurring", "imports"];
const LEDE =
  "Every transaction with its category and where it came from. Correct a category once and Foresight remembers it.";

export default async function TransactionsPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string | string[] }>;
}) {
  const [{ profile, features }, params] = await Promise.all([loadShell(), searchParams]);
  if (!isShipped(features, "ledger")) {
    return <SectionPage title="Transactions" lede={LEDE} what="Transactions, review queue, recurring and imports" />;
  }
  const tab = TABS.find((t) => t === params.tab) ?? "all";
  return (
    <main className="page section-page" id="main">
      <h1>Transactions</h1>
      <p className="lede">{LEDE}</p>
      {profile ? (
        <Transactions tab={tab} readOnly={Boolean(profile.read_only)} locale={profile.locale} />
      ) : (
        <p className="lede">Choose the demo profile or import a statement first.</p>
      )}
    </main>
  );
}
