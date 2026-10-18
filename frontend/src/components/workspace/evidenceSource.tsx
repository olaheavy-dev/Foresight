/**
 * Where a piece of evidence comes from (mandatory F, docs/06 §10.2): how many transactions it
 * counts and over which dates, the imported file they came from and whether its balances
 * reconciled, and a link to the transactions themselves. Shown in the Evidence drawer and in the
 * "How it was checked" tab.
 */
import { Icon } from "@/components/icons/Icon";
import { formatLongDate } from "@/lib/format";
import type { EvidenceItem } from "@/ui-contracts/types";

// An import's reconciliation status in words, as the Transactions page says it.
const RECONCILED: Record<string, string> = {
  reconciled: "Every row adds up to the running balance",
  failed: "Doesn’t add up to the running balance",
  not_reconcilable_no_balance: "No balance column to check against",
};

export function EvidenceSource({ item, locale }: { item: EvidenceItem; locale: string }) {
  return (
    <>
      {item.inputs?.transaction_count ? (
        <p className="ev-line">
          Based on {item.inputs.transaction_count}{" "}
          {item.inputs.transaction_count === 1 ? "transaction" : "transactions"}
          {item.inputs.date_range
            ? `, ${formatLongDate(item.inputs.date_range.from, locale)} to ${formatLongDate(item.inputs.date_range.to, locale)}`
            : ""}
          .
        </p>
      ) : null}
      {item.source_chain ? (
        <dl className="facts-dl">
          <dt>From</dt>
          <dd>{item.source_chain.filename}</dd>
          <dt>Rows</dt>
          <dd>{item.source_chain.rows}</dd>
          {item.source_chain.reconciliation ? (
            <>
              <dt>Balances</dt>
              <dd>{RECONCILED[item.source_chain.reconciliation.status] ?? item.source_chain.reconciliation.status}</dd>
            </>
          ) : null}
        </dl>
      ) : null}
      {item.link ? (
        <p className="ev-line">
          <a href={item.link}>
            See these transactions <Icon name="arrowright" />
          </a>
        </p>
      ) : null}
    </>
  );
}
