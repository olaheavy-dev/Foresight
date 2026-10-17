import {
  CLIENT_HEADER,
  deleteMyData,
  fetchAuthProviders,
  fetchCalculation,
  fetchDemoForecast,
  fetchFeatures,
  fetchForecast,
  fetchHealthz,
  fetchProfile,
  fetchResponse,
  fetchTransactions,
  importStatements,
  signOut,
  parseAgentResponse,
  simulate,
  startDemo,
  startNewProfile,
  startProactiveCheck,
} from "./api";
import type { ScenarioSpecPayload } from "@/ui-contracts/types";

const U = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const base = { baseUrl: "http://api.test" };

type Call = { url: string; init?: RequestInit };

function respond(body: unknown, status = 200, calls: Call[] = []): typeof fetch {
  return async (input, init) => {
    calls.push({ url: String(input), init });
    return new Response(JSON.stringify(body), { status });
  };
}

const failing: typeof fetch = async () => {
  throw new TypeError("network down");
};

const hanging: typeof fetch = (_input, init) =>
  new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
  });

const money = (minor: number) => ({
  kind: "money",
  minor,
  currency: "GBP",
  display: "£1",
  precision: "rounded",
});
const scope = {
  kind: "mine",
  label: "Current account",
  account_ids: [`acct_${U}`],
  switchable: false,
};
const chart = {
  as_of: "2026-10-13",
  scope,
  balance_mode: "absolute",
  resolution: "daily",
  history: { dates: ["2026-10-12"], balance_minor: [1000] },
  forecast: { dates: ["2026-10-14"], p10: [900], p50: [1000], p90: [1100] },
  buffer_minor: null,
  summary: {
    min_balance: money(900),
    min_date: { kind: "date", value: "2026-10-14", display: "14 Oct" },
    starting_balance: {
      money: { ...money(1000), precision: "exact" },
      provenance: "declared",
    },
  },
};
const forecastView = {
  forecast_id: `fc_${U}`,
  workspace_id: `wsp_${U}`,
  currency: "GBP",
  locale: "en-GB",
  engine_version: "0.1.0",
  data_version: 1,
  chart,
};
const series = { dates: ["2026-10-14"], p50: [1000] };
const simulationView = {
  simulation_id: `sim_${U}`,
  scenario_id: `scn_${U}`,
  workspace_id: `wsp_${U}`,
  currency: "GBP",
  locale: "en-GB",
  engine_version: "0.1.0",
  comparison: {
    scope,
    baseline: { label: "No change", series },
    scenarios: [
      {
        simulation_id: `sim_${U}`,
        scenario_id: `scn_${U}`,
        label: "Trip",
        series,
        modifiers_summary: ["One-off payment"],
      },
    ],
  },
};
const spec: ScenarioSpecPayload = {
  schema: "scenario_spec/1",
  name: "Trip",
  scope: "mine",
  currency: "GBP",
  modifiers: [
    {
      type: "one_off_outflow",
      date: "2026-11-06",
      amount_minor: 1000,
      label: "Trip",
    },
  ],
};
const narrative = {
  type: "Narrative",
  block_id: "b1",
  placement: { area: "overview", slot: "verdict" },
  segments: [{ kind: "text", text: "Fine" }],
};
const agentResponse = {
  schema_version: "agent_response/1",
  response_id: `rsp_${U}`,
  run_id: `run_${U}`,
  surface: "workspace",
  created_at: "2026-10-13T08:00:00Z",
  as_of: "2026-10-13",
  workspace_id: `wsp_${U}`,
  currency: "GBP",
  locale: "en-GB",
  data_version: 1,
  prefs_version: 1,
  engine_version: "0.1.0",
  status: "complete",
  blocks: [narrative],
  follow_ups: [
    {
      action_id: "fu_1",
      label: "Ask more",
      kind: "ask",
      payload: { question: "Why?" },
      requires_confirmation: false,
    },
  ],
  provenance: {},
};

describe("read endpoints", () => {
  it("validates features, healthz and forecast payloads", async () => {
    const calls: Call[] = [];
    const features = {
      features: [{ key: "forecast", stage: 1, title: "Forecast", enabled: true }],
    };
    expect(
      await fetchFeatures({
        ...base,
        fetchImpl: respond(features, 200, calls),
      }),
    ).toEqual(features.features);
    expect(
      await fetchForecast("mine", {
        ...base,
        fetchImpl: respond(forecastView, 200, calls),
      }),
    ).toEqual(forecastView);
    expect(calls.map((c) => c.url)).toEqual([
      "http://api.test/api/features",
      "http://api.test/api/forecast?scope=mine",
    ]);
  });

  it("returns an unavailable healthz body on 503 but not other errors", async () => {
    const down = { status: "unavailable", sha: null, database: false };
    expect(await fetchHealthz({ ...base, fetchImpl: respond(down, 503) })).toEqual(down);
    expect(await fetchHealthz({ ...base, fetchImpl: respond(down, 500) })).toBeNull();
  });

  it.each([
    ["a non-OK status", respond(forecastView, 502)],
    ["a malformed payload", respond({ ...forecastView, chart: { ...chart, buffer_minor: "500" } })],
    ["a network failure", failing],
    ["a non-JSON body", (async () => new Response("<html>")) as typeof fetch],
  ])("returns null on %s, never a partial number", async (_label, fetchImpl) => {
    expect(await fetchForecast("mine", { ...base, fetchImpl })).toBeNull();
  });

  it("gives up after the timeout", async () => {
    expect(
      await fetchForecast("mine", {
        ...base,
        fetchImpl: hanging,
        timeoutMs: 20,
      }),
    ).toBeNull();
  });
});

describe("write endpoints", () => {
  it("uploads statements as multipart and validates the summary", async () => {
    const calls: Call[] = [];
    const summary = {
      import_id: `imp_${U}`,
      workspace_id: `wsp_${U}`,
      data_version: 2,
      files: [
        {
          filename: "statement.csv",
          source_type: "csv",
          status: "imported",
          rows_read: 10,
          rows_imported: 10,
          rows_rejected: 0,
        },
      ],
    };
    const file = new Blob(["Date,Amount\n"], { type: "text/csv" });
    expect(
      await importStatements([file], {
        ...base,
        fetchImpl: respond(summary, 200, calls),
      }),
    ).toEqual(summary);
    expect(calls[0].url).toBe("http://api.test/api/imports");
    expect(calls[0].init?.method).toBe("POST");
    expect((calls[0].init?.body as FormData).getAll("files")).toHaveLength(1);
    expect(await importStatements([], { ...base, fetchImpl: respond(summary) })).toBeNull();
  });

  it("posts a scenario spec and validates the comparison", async () => {
    const calls: Call[] = [];
    expect(
      await simulate(spec, {
        ...base,
        fetchImpl: respond(simulationView, 200, calls),
      }),
    ).toEqual(simulationView);
    expect(JSON.parse(String(calls[0].init?.body))).toEqual(spec);
    const tooMany = {
      ...simulationView.comparison,
      scenarios: Array(4).fill(simulationView.comparison.scenarios[0]),
    };
    expect(
      await simulate(spec, {
        ...base,
        fetchImpl: respond({ ...simulationView, comparison: tooMany }),
      }),
    ).toBeNull();
  });
});

describe("responses", () => {
  it("fetches a snapshot by id and refuses malformed ids without calling the API", async () => {
    const calls: Call[] = [];
    const parsed = await fetchResponse(`rsp_${U}`, {
      ...base,
      fetchImpl: respond(agentResponse, 200, calls),
    });
    expect(parsed?.blocks).toEqual([{ ok: true, block: narrative }]);
    expect(calls[0].url).toBe(`http://api.test/api/responses/rsp_${U}`);
    expect(
      await fetchResponse("../admin", {
        ...base,
        fetchImpl: respond(agentResponse, 200, calls),
      }),
    ).toBeNull();
    expect(calls).toHaveLength(1);
  });

  it("isolates an invalid block and drops an invalid follow-up", () => {
    const broken = { ...narrative, block_id: "b2", type: "PieChart" };
    const badFollowUp = {
      action_id: "fu_2",
      label: "Go",
      kind: "open_tab",
      payload: {},
    };
    const parsed = parseAgentResponse({
      ...agentResponse,
      blocks: [narrative, broken],
      follow_ups: [...agentResponse.follow_ups, badFollowUp],
    });
    expect(parsed?.blocks[0].ok).toBe(true);
    expect(parsed?.blocks[1]).toMatchObject({
      ok: false,
      blockId: "b2",
      type: "PieChart",
      placement: { area: "overview", slot: "verdict" },
    });
    expect(parsed?.follow_ups.map((f) => f.action_id)).toEqual(["fu_1"]);
  });

  it.each([
    ["not an object", "nope"],
    ["no blocks", { ...agentResponse, blocks: [] }],
    ["a bad envelope", { ...agentResponse, currency: "pounds" }],
    ["a wrong schema version", { ...agentResponse, schema_version: "agent_response/2" }],
  ])("rejects %s", (_label, body) => {
    expect(parseAgentResponse(body)).toBeNull();
  });
});

describe("session and ledger", () => {
  const profile = {
    workspace_id: `wsp_${U}`,
    name: "Demo",
    kind: "demo",
    persona: "P1",
    country: "GB",
    home_currency: "GBP",
    locale: "en-GB",
    timezone: "Europe/London",
    data_version: 1,
    read_only: true,
  };

  it("sends credentials so the session cookie travels, and forwards a server-side cookie", async () => {
    const calls: Call[] = [];
    expect(
      await startDemo("P1", {
        ...base,
        fetchImpl: respond(profile, 200, calls),
      }),
    ).toEqual(profile);
    expect(calls[0].url).toBe("http://api.test/api/session/demo?persona=P1");
    expect(calls[0].init?.method).toBe("POST");
    expect(calls[0].init?.credentials).toBe("include");

    await fetchProfile({
      ...base,
      cookie: "foresight_session=abc",
      fetchImpl: respond(profile, 200, calls),
    });
    expect(new Headers(calls[1].init?.headers).get("cookie")).toBe("foresight_session=abc");
  });

  it("marks every write with the client header (CSRF) and leaves reads plain", async () => {
    const calls: Call[] = [];
    await startDemo("P1", { ...base, fetchImpl: respond(profile, 200, calls) });
    await fetchProfile({ ...base, fetchImpl: respond(profile, 200, calls) });
    expect(new Headers(calls[0].init?.headers).get(CLIENT_HEADER)).toBe("web");
    expect(new Headers(calls[1].init?.headers).get(CLIENT_HEADER)).toBeNull();
  });

  it("signs out and deletes data with POSTs, and reads the sign-in providers", async () => {
    const calls: Call[] = [];
    const noContent: typeof fetch = async (input, init) => {
      calls.push({ url: String(input), init });
      return new Response(null, { status: 204 });
    };
    expect(await signOut({ ...base, fetchImpl: noContent })).toBe(true);
    expect(await deleteMyData({ ...base, fetchImpl: noContent })).toBe(true);
    expect(calls.map((c) => [c.url, c.init?.method])).toEqual([
      ["http://api.test/api/session/logout", "POST"],
      ["http://api.test/api/session/delete", "POST"],
    ]);
    expect(await fetchAuthProviders({ ...base, fetchImpl: respond({ google: true, guest: true }) })).toEqual({
      google: true,
      guest: true,
    });
    expect(await fetchAuthProviders({ ...base, fetchImpl: respond({}, 200) })).toBeNull();
  });

  it("reads the public demo forecast without a session", async () => {
    const calls: Call[] = [];
    expect(await fetchDemoForecast({ ...base, fetchImpl: respond({}, 404, calls) })).toBeNull();
    expect(calls[0].url).toBe("http://api.test/api/public/demo-forecast");
    expect(calls[0].init?.method ?? "GET").toBe("GET");
  });

  it("creates a new profile and refuses an error response", async () => {
    const user = { ...profile, kind: "user", persona: null, read_only: false };
    expect(await startNewProfile({ ...base, fetchImpl: respond(user, 201) })).toEqual(user);
    expect(await startNewProfile({ ...base, fetchImpl: respond(user, 500) })).toBeNull();
  });

  it("builds ledger queries and validates the page", async () => {
    const calls: Call[] = [];
    const page = {
      workspace_id: `wsp_${U}`,
      total: 1,
      limit: 50,
      offset: 0,
      items: [
        {
          transaction_id: `txn_${U}`,
          account_id: `acct_${U}`,
          posted_on: "2026-10-12",
          narration: "Coffee",
          channel: "card",
          amount: { ...money(-350), precision: "exact" },
        },
      ],
    };
    expect(
      await fetchTransactions(
        { category: "food.coffee", limit: 50 },
        { ...base, fetchImpl: respond(page, 200, calls) },
      ),
    ).toEqual(page);
    expect(calls[0].url).toBe("http://api.test/api/transactions?category=food.coffee&limit=50");
    expect(await fetchTransactions({}, { ...base, fetchImpl: respond({ ...page, total: -1 }) })).toBeNull();
  });

  it("rejects a malformed calculation id without calling the API", async () => {
    const calls: Call[] = [];
    expect(
      await fetchCalculation("../x", {
        ...base,
        fetchImpl: respond({}, 200, calls),
      }),
    ).toBeNull();
    expect(calls).toHaveLength(0);
  });
});

describe("startProactiveCheck", () => {
  it("keeps the server's reason for a 429, so Home can say why (#59 review)", async () => {
    const detail = "Today’s guest allowance for your network is used.";
    expect(await startProactiveCheck({ ...base, fetchImpl: respond({ detail }, 429) })).toEqual({ refused: detail });
    expect(await startProactiveCheck({ ...base, fetchImpl: respond({ detail: "x" }, 500) })).toBeNull();
  });
});
