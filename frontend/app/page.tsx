import { ShippingStatus } from "@/components/ShippingStatus";
import { fetchFeatures } from "@/lib/features";

export const dynamic = "force-dynamic";

export default async function Home() {
  const features = await fetchFeatures();
  return (
    <main className="page">
      <p className="kicker">Agent Arena 2026 · FinPilot</p>
      <h1 className="headline">Foresight</h1>
      <p className="deck">
        Tells you where your money is heading, checks its own advice before it reaches you, and
        gives every number a receipt.
      </p>
      <ShippingStatus features={features} />
    </main>
  );
}
