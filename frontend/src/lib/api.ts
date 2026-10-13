/**
 * Typed client for the Foresight API. Every payload is checked against the generated contract
 * guards (docs/08 §6 Step 3) before the UI sees it; anything malformed, late or failed is `null`,
 * so the UI shows an error state and never a number it could not verify.
 */
import {
  isFeaturesPayload,
  isForecastView,
  isHealthz,
  isImportSummary,
  isSimulationView,
} from "@/ui-contracts/guards";
import type {
  AgentResponse,
  Block,
  Feature,
  FollowUpAction,
  ForecastView,
  Healthz,
  ImportSummary,
  Placement,
  ScenarioSpecPayload,
  SimulationView,
} from "@/ui-contracts/types";
import {
  type SchemaError,
  validate,
  validateBlock,
  validateFollowUp,
  validatePlacement,
} from "@/ui-contracts/validate";

const DEFAULT_BASE_URL = process.env.API_BASE_URL ?? "http://backend:8000";
export const TIMEOUTS = { read: 3000, simulate: 10000, import: 30000 } as const;
const RESPONSE_ID = /^rsp_[0-9A-HJKMNP-TV-Z]{26}$/;

export type ApiOptions = {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  baseUrl?: string;
};

async function request<T>(
  path: string,
  accept: (body: unknown, status: number) => T | null,
  { fetchImpl = fetch, timeoutMs = TIMEOUTS.read, baseUrl = DEFAULT_BASE_URL }: ApiOptions,
  init: RequestInit = {},
): Promise<T | null> {
  try {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      cache: "no-store",
      ...init,
      signal: AbortSignal.timeout(timeoutMs),
    });
    return accept(await response.json(), response.ok ? 200 : response.status);
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

/** Upload one or more statement files (multipart, field `files`). */
export function importStatements(
  files: readonly Blob[],
  options: ApiOptions = {},
): Promise<ImportSummary | null> {
  if (files.length === 0) return Promise.resolve(null);
  const form = new FormData();
  for (const file of files) form.append("files", file);
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

/** The current baseline forecast for a scope. */
export function fetchForecast(
  scope: "mine" | "household" | "account" = "mine",
  options: ApiOptions = {},
): Promise<ForecastView | null> {
  const query = new URLSearchParams({ scope });
  return request(`/api/forecast?${query}`, okAnd(isForecastView), options);
}

/** Run a what-if through the engine (deterministic, no AI). */
export function simulate(
  spec: ScenarioSpecPayload,
  options: ApiOptions = {},
): Promise<SimulationView | null> {
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
  const envelopeErrors = validate("AgentResponse", { ...raw, follow_ups: [] }).filter(
    (e) => e.path !== "blocks" && !e.path.startsWith("blocks."),
  );
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
export function fetchResponse(
  responseId: string,
  options: ApiOptions = {},
): Promise<ParsedResponse | null> {
  if (!RESPONSE_ID.test(responseId)) return Promise.resolve(null);
  return request(
    `/api/responses/${encodeURIComponent(responseId)}`,
    (body, status) => (status === 200 ? parseAgentResponse(body) : null),
    options,
  );
}
