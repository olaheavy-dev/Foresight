import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { parseAgentResponse } from "@/lib/api";

import { isAgentResponse, isResponsePlan } from "./guards";
import { validate, validateBlock } from "./validate";

// design/contracts examples are documentation, not fixtures, and are not fixed here. This pins
// where each departs from the contracts (the same gaps the Pydantic test pins), so a fix shows up
// as a diff. Indices are blocks / follow-ups that fail even with unknown properties tolerated.
const CONTRACTS = join(__dirname, "../../../design/contracts");
const KNOWN: Record<string, { planValid: boolean; badBlocks: number[]; badFollowUps: number[] }> = {
  "01-spending-question": { planValid: false, badBlocks: [2, 3, 4, 5], badFollowUps: [1] },
  "02-holiday-affordability": { planValid: false, badBlocks: [3, 4, 5, 6], badFollowUps: [0] },
  "03-proactive-risk-alert": { planValid: true, badBlocks: [1, 2, 3, 4], badFollowUps: [] },
  "04-plan-outlook": { planValid: false, badBlocks: [], badFollowUps: [0] },
  "05-verification-loop-timeline": { planValid: true, badBlocks: [1, 2], badFollowUps: [] },
  "06-india-spending-question": { planValid: true, badBlocks: [], badFollowUps: [] },
};

const examples = readdirSync(CONTRACTS)
  .filter((f) => f.endsWith(".json"))
  .map((f) => f.replace(/\.json$/, ""))
  .sort();

function load(name: string): { plan: unknown; response: Record<string, unknown> } {
  return JSON.parse(readFileSync(join(CONTRACTS, `${name}.json`), "utf8"));
}

describe("design/contracts examples", () => {
  it("are all covered", () => {
    expect(examples).toEqual(Object.keys(KNOWN).sort());
  });

  it.each(examples)("%s: plan and blocks match the guards except known gaps", (name) => {
    const { plan, response } = load(name);
    const known = KNOWN[name];
    expect(isResponsePlan(plan)).toBe(known.planValid);

    const blocks = response.blocks as unknown[];
    const bad = blocks.flatMap((b, i) => (validateBlock(b).length > 0 ? [i] : []));
    expect(bad).toEqual(known.badBlocks);
    expect(isAgentResponse(response)).toBe(bad.length === 0 && known.badFollowUps.length === 0);

    const parsed = parseAgentResponse(response);
    expect(parsed).not.toBeNull();
    expect(parsed!.blocks.flatMap((b, i) => (b.ok ? [] : [i]))).toEqual(known.badBlocks);
    const followUps = response.follow_ups as unknown[];
    expect(parsed!.follow_ups).toHaveLength(followUps.length - known.badFollowUps.length);
  });

  it("keeps a failing block's slot so the renderer can show BlockError in place", () => {
    const parsed = parseAgentResponse(load("03-proactive-risk-alert").response)!;
    const failed = parsed.blocks[1];
    expect(failed.ok).toBe(false);
    if (!failed.ok) {
      expect(failed.type).toBe("CashFlowForecastChart");
      expect(failed.placement).toEqual({ area: "overview", slot: "main_visual" });
      expect(failed.errors.map((e) => e.path)).toContain("summary");
    }
  });

  it("only rejects the India example for added fields in strict mode", () => {
    const errors = validate("AgentResponse", load("06-india-spending-question").response, {
      allowUnknownProperties: false,
    });
    expect(errors.map((e) => `${e.path}: ${e.message}`)).toEqual([
      "blocks.2.unit: unknown property",
      "blocks.2.series.0.nature: unknown property",
    ]);
  });
});

describe("validate", () => {
  const U = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
  const narrative = {
    type: "Narrative",
    block_id: "b1",
    placement: { area: "overview", slot: "verdict" },
    segments: [{ kind: "text", text: "Fine" }],
  };

  it("accepts a valid block and tolerates added optional fields by default", () => {
    expect(validateBlock(narrative)).toEqual([]);
    expect(validateBlock({ ...narrative, added_later: true })).toEqual([]);
    expect(validateBlock({ ...narrative, added_later: true }, { allowUnknownProperties: false })).toEqual([
      { path: "added_later", message: "unknown property" },
    ]);
  });

  it("reports unknown block types, bad refs, bad placements and wrong types", () => {
    expect(validateBlock({ ...narrative, type: "PieChart" })[0].message).toMatch(/unknown type/);
    expect(validateBlock({ ...narrative, evidence: ["calc_nope"] })[0].path).toBe("evidence.0");
    expect(validateBlock({ ...narrative, evidence: [`calc_${U}#result.total`] })).toEqual([]);
    expect(validateBlock({ ...narrative, placement: { area: "tab", tab: "overview" } })).not.toEqual([]);
    expect(validateBlock({ ...narrative, segments: "Fine" })).toEqual([
      { path: "segments", message: "expected array, got string" },
    ]);
  });

  it("checks money values field by field", () => {
    const value = { kind: "money", minor: 100, currency: "GBP", display: "x", precision: "exact" };
    const segment = { kind: "value", value };
    expect(validateBlock({ ...narrative, segments: [segment] })).toEqual([]);
    const bad = { ...segment, value: { ...value, minor: 1.5, currency: "gbp" } };
    expect(validateBlock({ ...narrative, segments: [bad] }).map((e) => e.path)).toEqual([
      "segments.0.value.minor",
      "segments.0.value.currency",
    ]);
  });
});
