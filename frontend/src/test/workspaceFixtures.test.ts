import { checkAgentResponse, isCalculationView } from "@/ui-contracts/guards";
import { validateBlock } from "@/ui-contracts/validate";
import {
  affordabilityResponse,
  calculation,
  degradedResponse,
  everyBlock,
  refusalResponse,
  spendingResponse,
} from "./workspaceFixtures";

describe("workspace fixtures match the generated contracts", () => {
  it.each([
    ["affordability", affordabilityResponse()],
    ["spending", spendingResponse()],
    ["refusal", refusalResponse()],
    ["degraded", degradedResponse()],
  ])("%s response is a valid agent_response/1", (_name, response) => {
    expect(checkAgentResponse(response)).toEqual([]);
  });

  it("covers all eleven block types (plus ClarifyingQuestion) and each one is valid", () => {
    const blocks = everyBlock();
    const types = new Set(blocks.map((b) => b.type));
    expect([...types].sort()).toEqual(
      [
        "AgentExecutionTimeline",
        "CashFlowForecastChart",
        "ClarifyingQuestion",
        "EvidencePanel",
        "FinancialMetricGroup",
        "GoalProjection",
        "InterventionCard",
        "Narrative",
        "RiskAssessment",
        "ScenarioComparison",
        "SpendingBreakdownChart",
        "TransactionTable",
      ].sort(),
    );
    for (const b of blocks) expect(validateBlock(b)).toEqual([]);
  });

  it("calculation is a valid CalculationView", () => {
    expect(isCalculationView(calculation())).toBe(true);
  });
});
