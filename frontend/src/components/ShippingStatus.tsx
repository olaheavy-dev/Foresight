import type { Feature } from "@/lib/features";

type Props = { features: Feature[] | null };

/** Honest status: what is shipped and what is still planned. Nothing half-built is shown. */
export function ShippingStatus({ features }: Props) {
  if (features === null) {
    return (
      <p role="status" className="note">
        The Foresight service is not reachable right now. Please try again shortly.
      </p>
    );
  }

  const shipped = features.filter((f) => f.enabled);
  const planned = features.filter((f) => !f.enabled).sort((a, b) => a.stage - b.stage);

  return (
    <div className="status">
      <section aria-labelledby="shipped-heading">
        <h2 id="shipped-heading" className="kicker">
          Shipped
        </h2>
        {shipped.length === 0 ? (
          <p className="note">Nothing yet. Foresight is being built in stages, and each feature appears here once its evaluation passes.</p>
        ) : (
          <ul>
            {shipped.map((f) => (
              <li key={f.key}>{f.title}</li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="planned-heading">
        <h2 id="planned-heading" className="kicker">
          Not shipped yet
        </h2>
        <ul>
          {planned.map((f) => (
            <li key={f.key}>
              <span className="stage">Stage {f.stage}</span> {f.title}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
