/**
 * Typed client for the Foresight API. Every payload is checked against the generated contract
 * guards (docs/08 §6 Step 3) before the UI sees it; anything malformed, late or failed is `null`,
 * so the UI shows an error state and never a number it could not verify.
 *
 * Session: the API identifies the browser by an opaque HttpOnly cookie (`foresight_session`), set
 * by `startDemo()` / `startNewProfile()` or Google sign-in; writes also carry `X-Foresight-Client`. In the browser, calls go to this origin's `/api/*` (proxied
 * to the backend by next.config.ts) with `credentials: "include"`, so the cookie travels and the
 * browser stores the one the backend sets. On the server (React Server Components, route
 * handlers) there is no cookie jar: pass the incoming request's cookie header as `cookie`. Only
 * browser calls can *choose* a profile, because only the browser can store the new cookie.
 */
import {
  isCategoryCorrected,
  isCategoryList,
  isImportHistory,
  isAccountList,
  isAccountView,
  isCalculationView,
  isDetectedFlows,
  isFeaturesPayload,
  isForecastView,
  isHealthz,
  isImportSummary,
  isProfileView,
  isSimulationView,
  isTransactionPage,
} from "@/ui-contracts/guards";
import type {
  CategoryCorrected,
  CategoryList,
  ImportHistory,
  AccountList,
  AccountView,
  AgentResponse,
  DetectedFlows,
  Block,
  CalculationView,
  Feature,
  FollowUpAction,
  ForecastView,
  Healthz,
  ImportSummary,
  Placement,
  ProfileView,
  ScenarioSpecPayload,
  SimulationView,
  TransactionPage,
} from "@/ui-contracts/types";
import {
  type SchemaError,
  validate,
  validateBlock,
  validateFollowUp,
  validatePlacement,
} from "@/ui-contracts/validate";

// Browser: same origin (the Next proxy). Server: straight to the private backend container.
const DEFAULT_BASE_URL = typeof window === "undefined" ? (process.env.API_BASE_URL ?? "http://backend:8000") : "";
// forecast: the first one after an import is computed on demand (Monte Carlo), not just read.
// ledger: a page of transactions with their categories; a busy server may need more than a read.
export const TIMEOUTS = {
  read: 3000,
  forecast: 8000,
  ledger: 10000,
  simulate: 10000,
  import: 30000,
  seed: 30000,
} as const;
export const CLIENT_HEADER = "X-Foresight-Client";
const RESPONSE_ID = /^rsp_[0-9A-HJKMNP-TV-Z]{26}$/;

export type ApiOptions = {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  baseUrl?: string;
  /** Server-side only: the incoming request's `cookie` header, forwarded to the API. */
  cookie?: string;
};

export type Scope = "mine" | "household" | `account:${string}`;

async function request<T>(
  path: string,
  accept: (body: unknown, status: number) => T | null,
  { fetchImpl = fetch, timeoutMs = TIMEOUTS.read, baseUrl = DEFAULT_BASE_URL, cookie }: ApiOptions,
  init: RequestInit = {},
): Promise<T | null> {
  try {
    const headers = new Headers(init.headers);
    if (cookie) headers.set("cookie", cookie);
    // CSRF (docs/05 §7.2): every write carries the client header the API requires.
    if (init.method && init.method !== "GET") headers.set(CLIENT_HEADER, "web");
    const response = await fetchImpl(`${baseUrl}${path}`, {
      cache: "no-store",
      credentials: "include",
      ...init,
      headers,
      signal: AbortSignal.timeout(timeoutMs),
    });
    const text = await response.text(); // a 204 (sign out, delete) has no body
    return accept(text ? JSON.parse(text) : null, response.ok ? 200 : response.status);
  } catch {
    return null;
  }
}

function okAnd<T>(guard: (body: unknown) => body is T) {
  return (body: unknown, status: number): T | null => (status === 200 && guard(body) ? body : null);
}

/** Which features are shipped (the UI hides anything disabled). */
export async function fetchFeatures(options: ApiOptions = {}): Promise<Feature[] | null> {
  const payload = await request("/api/features", okAnd(isFeaturesPayload), options);
  return payload?.features ?? null;
}

/** Readiness. A 503 still carries a valid body ("unavailable"), which is returned as-is. */
export function fetchHealthz(options: ApiOptions = {}): Promise<Healthz | null> {
  return request(
    "/healthz",
    (body, status) => ((status === 200 || status === 503) && isHealthz(body) ? body : null),
    options,
  );
}

/** Answers to an import's questions, applied to every file sent with them (docs/06 H13). */
export type ColumnRole = "date" | "description" | "amount" | "money_in" | "money_out" | "balance";
/** Which column holds what, for a file whose headings weren't recognised (normalised names). */
export type ColumnMapping = Partial<Record<ColumnRole, string>>;
export type ImportAnswers = Partial<Record<"currency" | "date_order" | "decimal_separator", string>> & {
  columns?: ColumnMapping;
};

/** Upload one or more statement files (multipart, field `files`), with any answers. */
export function importStatements(
  files: readonly Blob[],
  options: ApiOptions = {},
  answers?: ImportAnswers,
): Promise<ImportSummary | null> {
  if (files.length === 0) return Promise.resolve(null);
  const form = new FormData();
  for (const file of files) form.append("files", file);
  if (answers && Object.keys(answers).length) form.append("answers", JSON.stringify(answers));
  return request(
    "/api/imports",
    okAnd(isImportSummary),
    {
      timeoutMs: TIMEOUTS.import,
      ...options,
    },
    { method: "POST", body: form },
  );
}

/** Choose the seeded demo profile (browser only: stores the session cookie). */
export function startDemo(persona: "P1" | "P2" = "P1", options: ApiOptions = {}): Promise<ProfileView | null> {
  const query = new URLSearchParams({ persona });
  return request(
    `/api/session/demo?${query}`,
    okAnd(isProfileView),
    { timeoutMs: TIMEOUTS.seed, ...options },
    {
      method: "POST",
    },
  );
}

/** Create a new, empty profile to import statements into (browser only). */
export function startNewProfile(options: ApiOptions = {}): Promise<ProfileView | null> {
  return request("/api/session/new", okAnd(isProfileView), options, {
    method: "POST",
  });
}

/** The profile the session cookie points at; null when no profile is chosen yet. */
export function fetchProfile(options: ApiOptions = {}): Promise<ProfileView | null> {
  return request("/api/session", okAnd(isProfileView), options);
}

export type TransactionFilters = {
  dateFrom?: string;
  dateTo?: string;
  category?: string;
  flowKind?: string;
  accountId?: string;
  query?: string;
  review?: boolean;
  limit?: number;
  offset?: number;
};

/** One page of the ledger, newest first. */
export function fetchTransactions(
  filters: TransactionFilters = {},
  options: ApiOptions = {},
): Promise<TransactionPage | null> {
  const names: Record<keyof TransactionFilters, string> = {
    dateFrom: "date_from",
    dateTo: "date_to",
    category: "category",
    flowKind: "flow_kind",
    accountId: "account_id",
    query: "q",
    review: "review",
    limit: "limit",
    offset: "offset",
  };
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined) query.set(names[key as keyof TransactionFilters], String(value));
  }
  const suffix = query.size > 0 ? `?${query}` : "";
  return request(`/api/transactions${suffix}`, okAnd(isTransactionPage), { timeoutMs: TIMEOUTS.ledger, ...options });
}

/** A stored calculation for the Evidence drawer. */
export function fetchCalculation(calcId: string, options: ApiOptions = {}): Promise<CalculationView | null> {
  if (!/^calc_[0-9A-Za-z]+$/.test(calcId)) return Promise.resolve(null);
  return request(`/api/calculations/${encodeURIComponent(calcId)}`, okAnd(isCalculationView), options);
}

/** The current baseline forecast for a scope. */
export function fetchForecast(scope: Scope = "mine", options: ApiOptions = {}): Promise<ForecastView | null> {
  const query = new URLSearchParams({ scope });
  return request(`/api/forecast?${query}`, okAnd(isForecastView), { timeoutMs: TIMEOUTS.forecast, ...options });
}

/** The fictional demo's forecast for the public Landing preview (no session, no cookie). */
export function fetchDemoForecast(options: ApiOptions = {}): Promise<ForecastView | null> {
  return request("/api/public/demo-forecast", okAnd(isForecastView), options);
}

/** Run a what-if through the engine (deterministic, no AI). */
export function simulate(spec: ScenarioSpecPayload, options: ApiOptions = {}): Promise<SimulationView | null> {
  return request(
    "/api/simulate",
    okAnd(isSimulationView),
    {
      timeoutMs: TIMEOUTS.simulate,
      ...options,
    },
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(spec),
    },
  );
}

export type BlockResult =
  | { ok: true; block: Block }
  | {
      ok: false;
      blockId: string | null;
      type: string | null;
      placement: Placement | null;
      errors: SchemaError[];
    };

export type ParsedResponse = Omit<AgentResponse, "blocks" | "follow_ups"> & {
  blocks: BlockResult[];
  follow_ups: FollowUpAction[];
};

/**
 * Validates an `agent_response/1` envelope, then each block on its own: one bad block becomes a
 * BlockError tile in its slot (§9) instead of blanking the answer. Invalid follow-ups are
 * dropped. Returns null if the envelope itself is invalid.
 */
export function parseAgentResponse(body: unknown): ParsedResponse | null {
  if (typeof body !== "object" || body === null) return null;
  const raw = body as Record<string, unknown>;
  if (!Array.isArray(raw.blocks) || raw.blocks.length === 0) return null;
  const envelopeErrors = validate("AgentResponse", {
    ...raw,
    follow_ups: [],
  }).filter((e) => e.path !== "blocks" && !e.path.startsWith("blocks."));
  if (envelopeErrors.length > 0) return null;

  const blocks = raw.blocks.map((block): BlockResult => {
    const errors = validateBlock(block);
    if (errors.length === 0) return { ok: true, block: block as Block };
    const b = (typeof block === "object" && block !== null ? block : {}) as Record<string, unknown>;
    return {
      ok: false,
      blockId: typeof b.block_id === "string" ? b.block_id : null,
      type: typeof b.type === "string" ? b.type : null,
      placement: validatePlacement(b.placement).length === 0 ? (b.placement as Placement) : null,
      errors,
    };
  });
  const followUps = Array.isArray(raw.follow_ups) ? raw.follow_ups : [];
  return {
    ...(raw as unknown as AgentResponse),
    blocks,
    follow_ups: followUps.filter((f) => validateFollowUp(f).length === 0) as FollowUpAction[],
  };
}

/** A persisted answer snapshot (no agent or engine re-run, docs/08 §10). */
export function fetchResponse(responseId: string, options: ApiOptions = {}): Promise<ParsedResponse | null> {
  if (!RESPONSE_ID.test(responseId)) return Promise.resolve(null);
  return request(
    `/api/responses/${encodeURIComponent(responseId)}`,
    (body, status) => (status === 200 ? parseAgentResponse(body) : null),
    options,
  );
}

/** The profile's accounts with their latest known balance (none until one is read or declared). */
export function fetchAccounts(options: ApiOptions = {}): Promise<AccountList | null> {
  return request("/api/accounts", okAnd(isAccountList), options);
}

/** Declare an account's balance on a day (browser; the demo profile is read-only). */
export function declareBalance(
  accountId: string,
  asOf: string,
  amountMinor: number,
  options: ApiOptions = {},
): Promise<AccountView | null> {
  return request(`/api/accounts/${encodeURIComponent(accountId)}/balance`, okAnd(isAccountView), options, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ as_of: asOf, amount_minor: amountMinor }),
  });
}

/** Income and recurring payments the detectors found. */
export function fetchDetected(options: ApiOptions = {}): Promise<DetectedFlows | null> {
  return request("/api/detected", okAnd(isDetectedFlows), options);
}

/** The categories a transaction can be moved to (the profile's locale pack). */
export function fetchCategories(options: ApiOptions = {}): Promise<CategoryList | null> {
  return request("/api/categories", okAnd(isCategoryList), options);
}

/** Correct a transaction's category; `applyToMerchant` changes every row from the same payee. */
export function correctCategory(
  transactionId: string,
  categoryKey: string,
  applyToMerchant: boolean,
  options: ApiOptions = {},
): Promise<CategoryCorrected | null> {
  return request(
    `/api/transactions/${encodeURIComponent(transactionId)}/category`,
    okAnd(isCategoryCorrected),
    options,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ category_key: categoryKey, apply_to_merchant: applyToMerchant }),
    },
  );
}

/** Every import batch, newest first. */
export function fetchImports(options: ApiOptions = {}): Promise<ImportHistory | null> {
  return request("/api/imports", okAnd(isImportHistory), options);
}

export type AuthProviders = { google: boolean; guest: boolean };

/** Which sign-in methods the API offers (Google appears only once it is configured). */
export function fetchAuthProviders(options: ApiOptions = {}): Promise<AuthProviders | null> {
  return request(
    "/api/auth/providers",
    (body, status) => {
      const b = body as Partial<AuthProviders> | null;
      return status === 200 && typeof b?.google === "boolean" ? { google: b.google, guest: b.guest !== false } : null;
    },
    options,
  );
}

/** End this session (browser). */
export function signOut(options: ApiOptions = {}): Promise<boolean | null> {
  return request("/api/session/logout", (_b, status) => status === 200 || null, options, {
    method: "POST",
  });
}

/** Delete every profile this session or account owns, then end the session (browser). */
export function deleteMyData(options: ApiOptions = {}): Promise<boolean | null> {
  return request("/api/session/delete", (_b, status) => status === 200 || null, options, {
    method: "POST",
  });
}
