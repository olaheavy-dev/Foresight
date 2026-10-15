"use client";

/**
 * Transactions (`/transactions`, docs/01 F-07, F-11, F-51; IA: tabs via `?tab=`): every
 * transaction with its category and where the category came from, a review queue for the
 * uncertain ones, the regular payments and income found, and the import history. Correcting a
 * category teaches merchant memory and can apply to every row from the same payee.
 * Engine data only: no model call.
 */
import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Icon } from "@/components/icons/Icon";
import { IncomeControls } from "@/components/income/IncomeControls";
import { Badge, Button, ButtonLink, CardHead } from "@/components/ui/primitives";
import {
  correctCategory,
  fetchCategories,
  fetchDetected,
  fetchImports,
  fetchTransactions,
  type TransactionFilters,
} from "@/lib/api";
import { formatLongDate } from "@/lib/format";
import type { CategoryOption, DetectedFlows, ImportHistory, TransactionPage } from "@/ui-contracts/types";

type TransactionRow = TransactionPage["items"][number];

import "./transactions.css";

export type LedgerTab = "all" | "review" | "recurring" | "imports";
const PAGE = 100;

const NAMES: Record<string, string> = {
  "shopping.general": "General shopping",
  "housing.council_tax": "Council tax",
  "utilities.broadband_tv": "Broadband & TV",
  family_support_abroad: "Family support abroad",
  uncategorised: "Uncategorised",
  inflow_unconfirmed: "Money in (not yet confirmed)",
  savings_investment: "Savings and investments",
  "transfer.own": "Between your accounts",
  "transfer.untracked": "To an account not imported",
  "transfer.from_untracked": "From an account not imported",
  "transfer.card_settlement": "Card bill payment",
  "transfer.reimbursement": "Reimbursement",
  "transfer.other_person": "Paid to a person",
  credit_card_bill_unitemised: "Card bill (not itemised)",
  partner_contribution: "Partner contribution",
  betting_return: "Betting return",
  "tax.self_assessment": "Self Assessment tax",
  "income.self_employed": "Self-employed income",
};
/** "food.eating_out" → "Eating out"; a few keys read better with their group. */
export function categoryName(key: string | null | undefined): string {
  if (!key) return "Uncategorised";
  if (NAMES[key]) return NAMES[key];
  const last = key.split(".").pop() ?? key;
  const words = last.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const METHOD: Record<string, string> = { rule: "Rule", memory: "Merchant memory", llm: "AI", user: "You" };
const CADENCE: Record<string, string> = {
  weekly: "Weekly",
  fortnightly: "Every two weeks",
  four_weekly: "Every four weeks",
  monthly: "Monthly",
  quarterly: "Every three months",
  annual: "Yearly",
};

function provenance(r: TransactionRow): string {
  if (!r.categorised_by) return "Not categorised";
  const how = METHOD[r.categorised_by] ?? r.categorised_by;
  return r.categorised_by === "user" || r.confidence == null ? how : `${how} · ${Math.round(r.confidence * 100)}%`;
}

export function Transactions({
  tab,
  readOnly,
  locale,
  initialCategory = "",
}: {
  tab: LedgerTab;
  readOnly: boolean;
  locale: string;
  /** From `?category=` (Home's "See the transactions" link). */
  initialCategory?: string;
}) {
  const [reviewCount, setReviewCount] = useState<number | null>(null);
  useEffect(() => {
    void fetchTransactions({ review: true, limit: 1 }).then((p) => setReviewCount(p?.total ?? null));
  }, []);

  const views: { id: LedgerTab; label: string }[] = [
    { id: "all", label: "All" },
    { id: "review", label: reviewCount ? `To review · ${reviewCount}` : "To review" },
    { id: "recurring", label: "Recurring and income" },
    { id: "imports", label: "Imports" },
  ];

  return (
    <>
      <nav className="ledger-views" aria-label="Transaction views">
        {views.map((v) => (
          <Link
            key={v.id}
            href={`/transactions?tab=${v.id}`}
            aria-current={v.id === tab ? "page" : undefined}
            className={v.id === tab ? "on" : undefined}
          >
            {v.label}
          </Link>
        ))}
      </nav>
      {tab === "recurring" ? (
        <Recurring locale={locale} />
      ) : tab === "imports" ? (
        <Imports locale={locale} />
      ) : (
        <Ledger
          key={tab}
          review={tab === "review"}
          readOnly={readOnly}
          locale={locale}
          initialCategory={tab === "all" ? initialCategory : ""}
          onChanged={setReviewCount}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------------------------
// All transactions / review queue

function Ledger({
  review,
  readOnly,
  locale,
  initialCategory,
  onChanged,
}: {
  review: boolean;
  readOnly: boolean;
  locale: string;
  initialCategory: string;
  onChanged: (reviewTotal: number | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState(initialCategory);
  const [flowKind, setFlowKind] = useState("");
  const [page, setPage] = useState<TransactionPage | null>(null);
  const [rows, setRows] = useState<TransactionRow[]>([]);
  const [failed, setFailed] = useState(false);
  const [categories, setCategories] = useState<CategoryOption[]>([]);
  const [editing, setEditing] = useState<string | null>(null);

  useEffect(() => {
    void fetchCategories().then((c) => setCategories(c?.categories ?? []));
  }, []);

  const filters = useMemo<TransactionFilters>(
    () => ({
      query: query.trim() || undefined,
      category: category || undefined,
      flowKind: flowKind || undefined,
      review: review || undefined,
      limit: PAGE,
    }),
    [query, category, flowKind, review],
  );

  // Only the latest request may update the list: a slow answer for old filters (the ledger
  // timeout is 10 s) must never overwrite a newer one.
  const latest = useRef(0);
  const load = useCallback(
    async (offset = 0) => {
      const ticket = ++latest.current;
      const p = await fetchTransactions({ ...filters, offset });
      if (ticket !== latest.current) return;
      setFailed(!p);
      if (!p) return;
      setPage(p);
      setRows((prev) => (offset === 0 ? p.items : [...prev, ...p.items]));
    },
    [filters],
  );

  useEffect(() => {
    const t = setTimeout(() => void load(0), 250); // debounce typing in the search box
    return () => clearTimeout(t);
  }, [load]);

  const kinds = useMemo(() => [...new Set(categories.map((c) => c.flow_kind))].sort(), [categories]);
  const days = useMemo(() => {
    const groups: { day: string; items: TransactionRow[] }[] = [];
    for (const r of rows) {
      const last = groups.at(-1);
      if (last && last.day === r.posted_on) last.items.push(r);
      else groups.push({ day: r.posted_on, items: [r] });
    }
    return groups;
  }, [rows]);

  const saved = async () => {
    setEditing(null);
    await load(0);
    const total = await fetchTransactions({ review: true, limit: 1 });
    onChanged(total?.total ?? null);
  };

  return (
    <section className="card ledger" aria-labelledby="ledger-h">
      <div className="ledger-top">
        <CardHead
          icon={review ? "eye" : "list"}
          title={review ? "To review" : "All transactions"}
          titleId="ledger-h"
          sub={
            review
              ? "Categories Foresight is less than 85% sure of. Confirm or correct them; a correction is remembered for the payee."
              : "Newest first. Each category shows where it came from."
          }
        />
      </div>
      <div className="ledger-tools" role="search" aria-label="Search and filter transactions">
        <label className="tool grow">
          <span className="sr-only">Search transactions</span>
          <Icon name="search" />
          <input
            type="search"
            placeholder="Search payee or description"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <label className="tool">
          <span className="sr-only">Category</span>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={c.key} value={c.key}>
                {categoryName(c.key)}
              </option>
            ))}
          </select>
        </label>
        <label className="tool">
          <span className="sr-only">Type</span>
          <select value={flowKind} onChange={(e) => setFlowKind(e.target.value)}>
            <option value="">All types</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {categoryName(k)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {failed ? (
        <p className="ledger-empty" role="alert">
          The transactions couldn’t be loaded. Refresh to try again.
        </p>
      ) : !page ? (
        <p className="ledger-empty" aria-busy="true">
          Loading…
        </p>
      ) : rows.length === 0 ? (
        <p className="ledger-empty">
          {review
            ? "Nothing to review: every category is confident or set by you."
            : query || category || flowKind
              ? "No transactions match these filters."
              : "No transactions yet."}
        </p>
      ) : (
        <>
          <p className="ledger-count" aria-live="polite">
            Showing {rows.length} of {page.total}
          </p>
          {days.map((g) => (
            <section key={g.day} className="ledger-day" aria-label={formatLongDate(g.day, locale)}>
              <h3 className="day-h">{formatLongDate(g.day, locale)}</h3>
              <ul className="ledger-rows">
                {g.items.map((r) => (
                  <Row
                    key={r.transaction_id}
                    row={r}
                    categories={categories}
                    editing={editing === r.transaction_id}
                    readOnly={readOnly}
                    onEdit={() => setEditing(editing === r.transaction_id ? null : r.transaction_id)}
                    onSaved={saved}
                  />
                ))}
              </ul>
            </section>
          ))}
          {rows.length < page.total ? (
            <Button className="load-more" onClick={() => void load(rows.length)} iconEnd="chevdown">
              Show more
            </Button>
          ) : null}
        </>
      )}
    </section>
  );
}

function Row({
  row,
  categories,
  editing,
  readOnly,
  onEdit,
  onSaved,
}: {
  row: TransactionRow;
  categories: CategoryOption[];
  editing: boolean;
  readOnly: boolean;
  onEdit: () => void;
  onSaved: () => Promise<void>;
}) {
  // The bank's own description leads; the normalised payee only when it says something else.
  const payee = row.narration || row.counterparty || "Transaction";
  const other = row.counterparty && row.counterparty.toLowerCase() !== payee.toLowerCase() ? row.counterparty : null;
  const inflow = row.amount.minor > 0;
  return (
    <li className={["ledger-row", editing ? "editing" : ""].filter(Boolean).join(" ")}>
      <div className="lr-main">
        <span className="lr-payee">{payee}</span>
        {other ? <span className="lr-narration">{other}</span> : null}
      </div>
      <button
        type="button"
        className="lr-category"
        onClick={onEdit}
        aria-expanded={editing}
        aria-label={`Category: ${categoryName(row.category_key)}, ${provenance(row)}. Change category`}
      >
        <span className="lr-cat">{categoryName(row.category_key)}</span>
        <span className="lr-how">{provenance(row)}</span>
      </button>
      <span className={["lr-amount", "num", inflow ? "in" : ""].filter(Boolean).join(" ")}>
        {inflow ? "+" : ""}
        {row.amount.display}
      </span>
      {editing ? <Correction row={row} categories={categories} readOnly={readOnly} onSaved={onSaved} /> : null}
    </li>
  );
}

function Correction({
  row,
  categories,
  readOnly,
  onSaved,
}: {
  row: TransactionRow;
  categories: CategoryOption[];
  readOnly: boolean;
  onSaved: () => Promise<void>;
}) {
  const [key, setKey] = useState(row.category_key ?? "");
  const [all, setAll] = useState(Boolean(row.counterparty));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = `fix-${row.transaction_id}`;

  if (readOnly) {
    return (
      <p className="lr-edit note">
        <Icon name="info" />
        The demo profile is read-only. Import your own statement to correct categories.
      </p>
    );
  }
  return (
    <form
      className="lr-edit"
      onSubmit={async (e: FormEvent) => {
        e.preventDefault();
        if (!key) return;
        setBusy(true);
        setError(null);
        const done = await correctCategory(row.transaction_id, key, all && Boolean(row.counterparty));
        setBusy(false);
        if (!done) {
          setError("The category couldn’t be saved. Try again.");
          return;
        }
        await onSaved();
      }}
    >
      <label htmlFor={`${id}-cat`}>
        Category
        <select id={`${id}-cat`} value={key} onChange={(e) => setKey(e.target.value)}>
          {categories.map((c) => (
            <option key={c.key} value={c.key}>
              {categoryName(c.key)}
            </option>
          ))}
        </select>
      </label>
      {row.counterparty ? (
        <label className="check">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
          Apply to all from {row.counterparty}
        </label>
      ) : null}
      <Button type="submit" variant="primary" disabled={busy || !key}>
        Save
      </Button>
      {error ? (
        <p className="lr-error" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}

// ---------------------------------------------------------------------------------------------
// Recurring and income

function Recurring({ locale }: { locale: string }) {
  const [flows, setFlows] = useState<DetectedFlows | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    void fetchDetected().then((f) => {
      setFlows(f);
      setFailed(!f);
    });
  }, []);
  const cadence = (c: string) => CADENCE[c] ?? c.replace(/_/g, " ");

  if (failed)
    return (
      <p className="ledger-empty card" role="alert">
        What was found couldn’t be loaded. Refresh to try again.
      </p>
    );
  return (
    <div className="ledger-grid">
      <section className="card ledger" aria-labelledby="inc-h" aria-busy={!flows}>
        <CardHead icon="coins" title="Income" titleId="inc-h" sub="Regular pay found in your transactions" />
        {!flows ? (
          <p className="ledger-empty">Loading…</p>
        ) : flows.income.length === 0 ? (
          <p className="ledger-empty">No regular income found yet.</p>
        ) : (
          <ul className="flow-list">
            {flows.income.map((s) => (
              <li key={s.income_stream_id}>
                <div className="lr-main">
                  <span className="lr-payee">{s.source}</span>
                  <span className="lr-narration">
                    {cadence(s.cadence)} · seen {s.payments} times
                    {s.last_paid ? ` · last ${formatLongDate(s.last_paid, locale)}` : ""}
                  </span>
                </div>
                <span className={`lr-amount num ${s.provenance === "rejected" ? "muted" : "in"}`}>
                  +{s.amount.display}
                </span>
                <IncomeControls
                  stream={s}
                  onChange={(next) =>
                    setFlows(
                      (f) =>
                        f && {
                          ...f,
                          income: f.income.map((x) => (x.income_stream_id === next.income_stream_id ? next : x)),
                        },
                    )
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="card ledger" aria-labelledby="rec-h" aria-busy={!flows}>
        <CardHead
          icon="calendar"
          title="Regular payments"
          titleId="rec-h"
          sub="Bills, subscriptions and transfers that repeat"
        />
        {!flows ? (
          <p className="ledger-empty">Loading…</p>
        ) : flows.recurring.length === 0 ? (
          <p className="ledger-empty">No regular payments found yet.</p>
        ) : (
          <ul className="flow-list">
            {flows.recurring.map((r) => (
              <li key={r.recurring_id}>
                <div className="lr-main">
                  <span className="lr-payee">{r.label}</span>
                  <span className="lr-narration">
                    {cadence(r.cadence)}
                    {r.day_of_month ? ` · around day ${r.day_of_month}` : ""} · {categoryName(r.category_key)}
                  </span>
                </div>
                {r.is_commitment ? <Badge tone="blue">Commitment</Badge> : <span />}
                <span className="lr-amount num">{r.amount.display}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Imports

const IMPORT_STATUS: Record<string, { tone: "green" | "amber" | "red"; label: string }> = {
  committed: { tone: "green", label: "Imported" },
  needs_review: { tone: "amber", label: "Waiting for an answer" },
  rejected: { tone: "red", label: "Not imported" },
};
const RECONCILIATION: Record<string, string> = {
  reconciled: "Every row adds up to the running balance",
  failed: "Doesn’t add up to the running balance",
  not_reconcilable_no_balance: "No balance column to check against",
};

function Imports({ locale }: { locale: string }) {
  const [history, setHistory] = useState<ImportHistory | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    void fetchImports().then((h) => {
      setHistory(h);
      setFailed(!h);
    });
  }, []);
  return (
    <section className="card ledger" aria-labelledby="imp-h" aria-busy={!history}>
      <div className="ledger-top">
        <CardHead icon="upload" title="Imports" titleId="imp-h" sub="Every statement you’ve imported, newest first" />
        <ButtonLink href="/start" variant="secondary" icon="plus">
          Import a statement
        </ButtonLink>
      </div>
      {failed ? (
        <p className="ledger-empty" role="alert">
          The import history couldn’t be loaded. Refresh to try again.
        </p>
      ) : !history ? (
        <p className="ledger-empty">Loading…</p>
      ) : history.imports.length === 0 ? (
        <p className="ledger-empty">No imports yet.</p>
      ) : (
        <ul className="flow-list imports">
          {history.imports.map((b) => {
            const s = IMPORT_STATUS[b.status] ?? { tone: "amber" as const, label: b.status };
            return (
              <li key={b.import_id}>
                <div className="lr-main">
                  <span className="lr-payee">{b.filename}</span>
                  <span className="lr-narration">
                    {formatLongDate(b.imported_at.slice(0, 10), locale)} · {b.rows_imported} of {b.rows_read} rows
                    {b.duplicates ? ` · ${b.duplicates} duplicates skipped` : ""}
                    {b.reconciliation ? ` · ${RECONCILIATION[b.reconciliation] ?? b.reconciliation}` : ""}
                  </span>
                  {b.message ? <span className="lr-narration">{b.message}</span> : null}
                </div>
                <Badge tone={s.tone}>{s.label}</Badge>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
