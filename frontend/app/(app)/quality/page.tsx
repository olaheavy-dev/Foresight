import { ShippingStatus } from "@/components/ShippingStatus";
import { loadShell } from "@/lib/server";

export const metadata = { title: "Quality · Foresight" };

/** Always on (TASKS: Quality): reports honestly whatever is shipped and what is still planned.
 *  The measured evaluation tables arrive with the evaluation results API. */
export default async function QualityPage() {
  const { features } = await loadShell();
  return (
    <main className="page section-page" id="main">
      <h1>Quality checks</h1>
      <p className="lede">
        Each feature is switched on only when its evaluation passes. Measured results are published in the
        repository’s README and evals/results; this page will show them once the results API ships.
      </p>
      <ShippingStatus features={features} />
    </main>
  );
}
