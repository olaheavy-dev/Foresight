"use client";

/**
 * Import / onboarding (`/start`, docs/01 F-15, F-47; .design/foresight/INFORMATION_ARCHITECTURE.md):
 * Step 1 drops one or more statements and shows, per file, the format found, rows read and the
 * reconciliation result, with any question only the user can answer. Step 2 shows what was
 * found (accounts, income, bills) and asks for a balance only where none could be read.
 * Engine data only: no model call.
 */
import { useRouter } from "next/navigation";
import { type ChangeEvent, type DragEvent, type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "@/components/icons/Icon";
import { Badge, Button, ButtonLink, CardHead } from "@/components/ui/primitives";
import {
  declareBalance,
  fetchAccounts,
  fetchDetected,
  fetchProfile,
  type ImportAnswers,
  importStatements,
  startNewProfile,
} from "@/lib/api";
import { formatLongDate, formatMoney, parseAmountMinor } from "@/lib/format";
import type { AccountList, DetectedFlows, ImportedFile, ProfileView } from "@/ui-contracts/types";

import "./start.css";

const MAX_FILES = 10;
const MAX_BYTES = 10 * 1024 * 1024;
const ACCEPT = ".csv,.xlsx,.xls,text/csv";
const ANSWERABLE = new Set(["currency", "date_order", "decimal_separator"]);

type Picked = { file: File; result: ImportedFile | null };

const today = () => new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD in the browser's zone

/** "monzo_current_v1" → "Monzo"; an unrecognised profile is described by what it did. */
function formatName(profile: string | null | undefined): string {
  const p = (profile ?? "").toLowerCase();
  if (p.includes("monzo")) return "Monzo";
  if (p.includes("revolut")) return "Revolut";
  return p ? "Read from its columns" : "Format not recognised";
}

function period(file: ImportedFile, locale: string): string | null {
  return file.period ? `${formatLongDate(file.period.from, locale)} – ${formatLongDate(file.period.to, locale)}` : null;
}

export function ImportFlow({ step }: { step: "files" | "check" }) {
  return step === "check" ? <CheckStep /> : <FilesStep />;
}

// ---------------------------------------------------------------------------------------------
// Step 1 · Drop statements

function FilesStep() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [picked, setPicked] = useState<Picked[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [answers, setAnswers] = useState<Record<string, ImportAnswers>>({});

  const send = useCallback(async (files: File[], given?: ImportAnswers) => {
    setBusy(true);
    setError(null);
    // A statement always goes into the visitor's own profile, never the shared demo.
    const profile = await fetchProfile();
    if (!profile || profile.kind === "demo") {
      if (!(await startNewProfile())) {
        setBusy(false);
        setError("We couldn't start your profile. Check your connection and try again.");
        return;
      }
    }
    const summary = await importStatements(files, {}, given);
    setBusy(false);
    if (!summary) {
      setError("The files couldn't be imported. Check they are CSV exports under 10 MB and try again.");
      return;
    }
    setPicked((prev) => {
      const next = [...prev];
      files.forEach((file, i) => {
        const at = next.findIndex((p) => p.file === file);
        const entry = { file, result: summary.files[i] ?? null };
        if (at >= 0) next[at] = entry;
        else next.push(entry);
      });
      return next;
    });
  }, []);

  const add = (list: FileList | null) => {
    const files = Array.from(list ?? []);
    if (!files.length) return;
    const tooBig = files.filter((f) => f.size > MAX_BYTES).map((f) => f.name);
    const room = MAX_FILES - picked.length;
    if (tooBig.length) {
      setError(`${tooBig.join(", ")} ${tooBig.length === 1 ? "is" : "are"} larger than 10 MB.`);
      return;
    }
    if (files.length > room) {
      setError(`Up to ${MAX_FILES} files at a time.`);
      return;
    }
    void send(files);
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    add(event.dataTransfer.files);
  };

  const imported = picked.filter((p) => p.result?.status === "imported");
  const canContinue = imported.length > 0 && !busy;

  return (
    <>
      <p className="kicker">Import · Step 1 of 2</p>
      <h1 className="serif">Drop your statements</h1>
      <p className="sub">
        CSV exports from your bank. Foresight finds the table, checks it against the running balance where there is one,
        and shows you what it found before anything is used.
      </p>

      <div
        className={["dropzone", dragging ? "over" : "", busy ? "busy" : ""].filter(Boolean).join(" ")}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <span className="icon-chip">
          <Icon name="upload" />
        </span>
        <p className="dz-title">{busy ? "Reading your statements…" : "Drop CSV files here"}</p>
        <p className="dz-sub">
          Up to {MAX_FILES} files, 10 MB each. Monzo and Revolut exports are recognised; other banks’ CSVs are read from
          their column headings.
        </p>
        <Button variant="secondary" onClick={() => input.current?.click()} disabled={busy} icon="clip">
          Choose files
        </Button>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          aria-label="Choose statement files"
          onChange={(e: ChangeEvent<HTMLInputElement>) => {
            add(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {error ? (
        <p className="import-error" role="alert">
          <Icon name="alert" />
          {error}
        </p>
      ) : null}

      {picked.length ? (
        <ul className="file-results" aria-label="Your files" aria-live="polite">
          {picked.map((p, i) => (
            <FileResult
              key={`${p.file.name}-${i}`}
              picked={p}
              busy={busy}
              answers={answers[p.file.name] ?? {}}
              onAnswer={(kind, value) =>
                setAnswers((a) => ({ ...a, [p.file.name]: { ...a[p.file.name], [kind]: value } }))
              }
              onRetry={(given) => void send([p.file], given)}
            />
          ))}
        </ul>
      ) : null}

      <div className="primary-actions">
        <Button
          variant="primary"
          size="lg"
          iconEnd="arrowright"
          disabled={!canContinue}
          onClick={() => router.push("/start?step=check")}
        >
          Check what we found
        </Button>
        <ButtonLink href="/" variant="secondary" size="lg">
          Back to the start
        </ButtonLink>
      </div>
      <p className="privacy-note">
        <Icon name="shield" />
        Your statements stay in your own profile. Import never calls an AI model; account numbers are never sent
        anywhere.
      </p>
    </>
  );
}

function FileResult({
  picked,
  busy,
  answers,
  onAnswer,
  onRetry,
}: {
  picked: Picked;
  busy: boolean;
  answers: ImportAnswers;
  onAnswer: (kind: string, value: string) => void;
  onRetry: (given: ImportAnswers) => void;
}) {
  const r = picked.result;
  const locale = "en-GB";
  if (!r) {
    return (
      <li className="file-result">
        <div className="fr-head">
          <span className="fr-name">{picked.file.name}</span>
          <Badge tone="grey" icon="clock">
            Reading…
          </Badge>
        </div>
      </li>
    );
  }
  const questions = (r.questions ?? []).filter((q) => ANSWERABLE.has(q.kind));
  const rec = r.reconciliation;
  return (
    <li className="file-result">
      <div className="fr-head">
        <span className="fr-name">{r.filename}</span>
        {r.status === "imported" ? (
          <Badge tone="green" icon="checkcircle">
            {r.already_imported ? "Already imported" : "Imported"}
          </Badge>
        ) : r.status === "needs_mapping" ? (
          <Badge tone="amber" icon="info">
            Needs an answer
          </Badge>
        ) : (
          <Badge tone="red" icon="xcircle">
            Not imported
          </Badge>
        )}
      </div>
      <dl className="fr-facts">
        <div>
          <dt>Format</dt>
          <dd>{formatName(r.matched_profile)}</dd>
        </div>
        {period(r, locale) ? (
          <div>
            <dt>Period</dt>
            <dd>{period(r, locale)}</dd>
          </div>
        ) : null}
        <div>
          <dt>Rows</dt>
          <dd>
            {r.status === "imported"
              ? `${r.rows_imported} imported of ${r.rows_read} read`
              : `${r.rows_read} read, none used yet`}
            {r.duplicates ? ` · ${r.duplicates} duplicates skipped` : ""}
          </dd>
        </div>
        {rec ? (
          <div>
            <dt>Balance check</dt>
            <dd className={rec.status === "failed" ? "bad" : rec.status === "passed" ? "good" : ""}>
              {rec.status === "passed"
                ? "Every row adds up to the running balance"
                : rec.status === "failed"
                  ? "Doesn’t add up to the running balance"
                  : "No balance column: you’ll add today’s balance next"}
            </dd>
          </div>
        ) : null}
      </dl>
      {(r.messages ?? []).length ? (
        <ul className="fr-messages">
          {(r.messages ?? []).map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      ) : null}
      {(r.rejections ?? []).length ? (
        <details className="fr-rejections">
          <summary>Rows that didn’t add up ({(r.rejections ?? []).length})</summary>
          <ul>
            {(r.rejections ?? []).slice(0, 20).map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </details>
      ) : null}
      {r.status === "needs_mapping" && questions.length ? (
        <form
          className="fr-questions"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            const given: ImportAnswers = {};
            for (const q of questions) {
              const v = answers[q.kind as keyof ImportAnswers] ?? q.preselected ?? q.options?.[0];
              if (v) given[q.kind as keyof ImportAnswers] = v;
            }
            onRetry(given);
          }}
        >
          {questions.map((q) => (
            <fieldset key={q.kind}>
              <legend>{q.prompt}</legend>
              <div className="options">
                {(q.options ?? []).map((o) => (
                  <label key={o} className="option">
                    <input
                      type="radio"
                      name={`${r.filename}-${q.kind}`}
                      value={o}
                      defaultChecked={(answers[q.kind as keyof ImportAnswers] ?? q.preselected) === o}
                      onChange={() => onAnswer(q.kind, o)}
                    />
                    {o}
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
          <Button type="submit" variant="primary" disabled={busy}>
            Import with these answers
          </Button>
        </form>
      ) : null}
    </li>
  );
}

// ---------------------------------------------------------------------------------------------
// Step 2 · Check what we found

function CheckStep() {
  const [profile, setProfile] = useState<ProfileView | null>(null);
  const [accounts, setAccounts] = useState<AccountList | null>(null);
  const [flows, setFlows] = useState<DetectedFlows | null>(null);
  const [failed, setFailed] = useState(false);
  const [allBills, setAllBills] = useState(false);

  const load = useCallback(async () => {
    const [p, a, f] = await Promise.all([fetchProfile(), fetchAccounts(), fetchDetected()]);
    if (!p || !a || !f) setFailed(true);
    setProfile(p);
    setAccounts(a);
    setFlows(f);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const locale = profile?.locale ?? "en-GB";
  const missing = (accounts?.accounts ?? []).filter((a) => !a.balance);

  return (
    <>
      <p className="kicker">Import · Step 2 of 2</p>
      <h1 className="serif">Check what we found</h1>
      <p className="sub">
        Detected from your transactions. Your forecast starts from these; you can correct them later in Transactions.
      </p>

      {failed ? (
        <p className="import-error" role="alert">
          <Icon name="alert" />
          We couldn’t load what was found. Refresh to try again.
        </p>
      ) : null}

      {profile?.kind === "demo" ? (
        <p className="import-error" role="status">
          <Icon name="info" />
          You’re on the demo profile. Import a statement first to see your own data here.
        </p>
      ) : null}

      <section className="check-card" aria-labelledby="acc-h" aria-busy={!accounts}>
        <CardHead icon="wallet" title="Accounts" titleId="acc-h" />
        {!accounts ? (
          <p className="muted">Loading…</p>
        ) : accounts.accounts.length === 0 ? (
          <p className="muted">No accounts yet. Go back and import a statement.</p>
        ) : (
          <ul className="check-list">
            {accounts.accounts.map((a) => (
              <li key={a.account_id}>
                <div className="cl-main">
                  <span className="cl-title">{a.name}</span>
                  <span className="cl-sub">
                    {a.transactions} transactions
                    {a.period
                      ? ` · ${formatLongDate(a.period.from, locale)} – ${formatLongDate(a.period.to, locale)}`
                      : ""}
                  </span>
                </div>
                {a.balance ? (
                  <div className="cl-value">
                    <span className="num">{a.balance.money.display}</span>
                    <span className="cl-sub">
                      {a.balance.provenance === "declared" ? "you told us" : "from the statement"} ·{" "}
                      {formatLongDate(a.balance.as_of, locale)}
                    </span>
                  </div>
                ) : (
                  <Badge tone="amber" icon="info">
                    Balance needed
                  </Badge>
                )}
              </li>
            ))}
          </ul>
        )}
        {missing.map((a) => (
          <BalanceForm key={a.account_id} accountId={a.account_id} name={a.name} currency={a.currency} onSaved={load} />
        ))}
      </section>

      <section className="check-card" aria-labelledby="inc-h" aria-busy={!flows}>
        <CardHead icon="coins" title="Income" titleId="inc-h" />
        {!flows ? (
          <p className="muted">Loading…</p>
        ) : flows.income.length === 0 ? (
          <p className="muted">
            No regular income found yet. The forecast uses your spending alone until a pay pattern appears.
          </p>
        ) : (
          <ul className="check-list">
            {flows.income.map((s) => (
              <li key={s.income_stream_id}>
                <div className="cl-main">
                  <span className="cl-title">{s.source}</span>
                  <span className="cl-sub">
                    {cadence(s.cadence)} · seen {s.payments} times
                    {s.last_paid ? ` · last ${formatLongDate(s.last_paid, locale)}` : ""}
                  </span>
                </div>
                <span className="cl-value num">{s.amount.display}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="check-card" aria-labelledby="bill-h" aria-busy={!flows}>
        <CardHead
          icon="calendar"
          title="Regular payments"
          titleId="bill-h"
          sub="Bills, subscriptions and transfers that repeat"
        />
        {!flows ? (
          <p className="muted">Loading…</p>
        ) : flows.recurring.length === 0 ? (
          <p className="muted">No regular payments found yet.</p>
        ) : (
          <ul className="check-list">
            {(allBills ? flows.recurring : flows.recurring.slice(0, SHOWN)).map((r) => (
              <li key={r.recurring_id}>
                <div className="cl-main">
                  <span className="cl-title">{r.label}</span>
                  <span className="cl-sub">
                    {cadence(r.cadence)}
                    {r.day_of_month ? ` · around the ${ordinal(r.day_of_month)}` : ""}
                    {r.is_commitment ? " · commitment" : ""}
                  </span>
                </div>
                <span className="cl-value num">{r.amount.display}</span>
              </li>
            ))}
          </ul>
        )}
        {flows && flows.recurring.length > SHOWN && !allBills ? (
          <Button className="show-more" onClick={() => setAllBills(true)} iconEnd="chevdown">
            Show {flows.recurring.length - SHOWN} more
          </Button>
        ) : null}
      </section>

      <div className="primary-actions">
        <ButtonLink href="/home" variant="primary" size="lg" iconEnd="arrowright">
          See your forecast
        </ButtonLink>
        <ButtonLink href="/start" variant="secondary" size="lg" icon="plus">
          Add more statements
        </ButtonLink>
      </div>
    </>
  );
}

const CADENCE: Record<string, string> = {
  weekly: "Weekly",
  fortnightly: "Every two weeks",
  four_weekly: "Every four weeks",
  monthly: "Monthly",
  quarterly: "Every three months",
  annual: "Yearly",
  irregular: "Irregular",
};
const cadence = (c: string) => CADENCE[c] ?? c.replace(/_/g, " ");
const SHOWN = 8;

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

function BalanceForm({
  accountId,
  name,
  currency,
  onSaved,
}: {
  accountId: string;
  name: string;
  currency: string;
  onSaved: () => Promise<void>;
}) {
  const [amount, setAmount] = useState("");
  const [asOf, setAsOf] = useState(today);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const id = `bal-${accountId}`;
  const example = formatMoney(123456, currency);

  return (
    <form
      className="balance-form"
      onSubmit={async (e: FormEvent) => {
        e.preventDefault();
        const minor = parseAmountMinor(amount, currency);
        if (minor === null) {
          setError(`Enter an amount like ${example}.`);
          return;
        }
        setBusy(true);
        setError(null);
        const saved = await declareBalance(accountId, asOf, minor);
        setBusy(false);
        if (!saved) {
          setError("The balance couldn’t be saved. Check the date isn’t in the future and try again.");
          return;
        }
        await onSaved();
      }}
    >
      <p className="bf-why">
        <strong>{name}</strong> has no balance column, so the forecast can’t start from a real figure. Add the balance
        shown in your banking app.
      </p>
      <div className="bf-fields">
        <label htmlFor={`${id}-amount`}>
          Balance
          <input
            id={`${id}-amount`}
            inputMode="decimal"
            autoComplete="off"
            placeholder={example}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${id}-err` : undefined}
          />
        </label>
        <label htmlFor={`${id}-date`}>
          On
          <input id={`${id}-date`} type="date" max={today()} value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </label>
        <Button type="submit" variant="primary" disabled={busy}>
          Save balance
        </Button>
      </div>
      {error ? (
        <p className="bf-error" id={`${id}-err`} role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
