import { Icon } from "@/components/icons/Icon";

/**
 * Honest placeholder for anything whose feature flag is off or whose API does not exist yet
 * (docs/01 FR-86): it says so plainly and never shows a sample number in its place.
 */
export function NotShipped({
  title,
  detail = "This part of Foresight is still being built. It appears here once its evaluation passes.",
  compact = false,
}: {
  title: string;
  detail?: string;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "not-shipped compact" : "not-shipped"} role="note">
      <Icon name="clock" />
      <div>
        <p className="ns-title">
          {title} <span className="badge grey">Not shipped yet</span>
        </p>
        <p className="ns-detail">{detail}</p>
      </div>
    </div>
  );
}

/** Data could not be loaded or verified: say so, never fall back to a guessed figure. */
export function Unavailable({ what }: { what: string }) {
  return (
    <div className="not-shipped" role="status">
      <Icon name="info" />
      <div>
        <p className="ns-title">{what} isn’t available right now</p>
        <p className="ns-detail">
          The Foresight service didn’t answer, or answered with data we couldn’t check. Try again shortly.
        </p>
      </div>
    </div>
  );
}
