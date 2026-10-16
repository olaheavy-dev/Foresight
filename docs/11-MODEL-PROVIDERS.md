# 11 — Model providers after the hackathon (evaluation, 16 Oct 2026)

> Status: **PROPOSED** (open decision 14 in [`00`](00-DECISION-REGISTER.md) §12). Nothing changes while Foresight is entered in Agent Arena 2026: the hackathon requires every model call to go through Mesh (`00` §2), so Mesh stays until the owner leaves the hackathon or it ends.

## Recommendation

- **Advisor (reasoning tier): call Anthropic directly, with prompt caching on.** About 3,000 of the Advisor's ~4,200 input tokens are the same on every call (system prompt and rules), so cached reads cut an advice answer by about 20% at steady traffic.
- **Understand, scenario parsing, categorisation (fast tier) and the Verifier: call OpenAI directly** (or Azure AI Foundry's Global deployment, at the same price).
- **Keep our own single model gateway.** `backend/mesh/mesh_client.py` stays the only module that calls a model, with tiers, prices (`backend/mesh/models.yaml`), spend guards, recordings and redaction. Swapping a provider stays a configuration change, and the import contract that keeps model SDKs out of other modules stays.
- **If EU data residency becomes a requirement:** use Azure's EU Data Zone for the OpenAI models and accept that Claude inference stays Global (see below).

## Why: cost

Prices are USD per million tokens, from the providers' official pricing pages on 16 Oct 2026. Our token profile comes from the recorded calls in `evals/cassettes/` (average per call):

| Tier | Model | Input / output tokens | List price in / out | Cached input |
|---|---|---|---|---|
| fast | `gpt-6-luna` | ~1,850 / ~180 | $0.10 / $0.50 | $0.01 |
| reasoning | `claude-sonnet-5.5` | ~4,200 / ~1,250 | $2.00 / $10.00 | read $0.10; 5-minute write $2.50 |
| verifier | `gpt-6.1-sol` | ~950 / ~150 | $2.00 / $10.00 | $0.10 |

A typical advice answer makes about 3 fast calls, 1.6 Advisor calls and 3 Verifier calls. That model reproduces our measured mean of $0.044 (E-EFF), and with 3 Advisor calls it gives $0.074, close to our measured p95 of $0.08.

| Option | Per advice answer | Per 1,000 advice answers |
|---|---|---|
| Mesh (list prices, no cache discount) | $0.0445 | $44.46 |
| Direct, no caching | $0.0445 | $44.46 |
| **Direct, Advisor caching, steady traffic** | **$0.0353** | **$35.34** |
| Direct, caching, low traffic (first call in 5 minutes writes the cache) | $0.0425 | $42.55 |
| Azure Global (OpenAI models; Claude on Foundry) | same as direct | same as direct |
| Azure EU Data Zone for OpenAI, Claude Global, caching | $0.0376 | $37.55 |

Simple answers cost about $0.0004–0.0006 on every option.

- **Mesh** states "0% markup" on pay-as-you-go, so its per-token prices match the providers' list prices. Our 13 Oct catalogue rates match for all three models. Credits are prepaid and non-refundable. Mesh documents a 24-hour cache for exact repeated requests, but not how provider prompt caching is billed. We observed cache writes and no cached-read discount (`models.yaml`, 13 Oct).
- **Batch** pricing (50% off at both providers) would only apply to background work such as recordings, not to answers.

## Why: terms and residency (checked 16 Oct 2026)

- **Data residency:** no option keeps Claude inference in the UK or EU. Anthropic offers global or US inference. OpenAI offers EU processing, and UK data storage only, both with approval.
- **Retention:** zero data retention needs approval from both providers. By default, neither trains on API data.
- **Contract terms:** a UK fintech needs a data processing agreement that covers UK transfers (the UK IDTA or the UK addendum to the EU clauses). Check this for whichever provider or gateway is chosen. Mesh's DPA cites the EU clauses only, and Mesh publishes no SLA.
- **New-account limits:** both providers start new accounts at a $500/month spend cap, enough for this stage.
- **Startup credits:** Microsoft for Startups offers Azure credits, but reportedly not for Claude bought through Azure Marketplace. Anthropic's startup programme runs through partner VCs. OpenAI has no public self-serve programme.

## Not verified

- Mesh's current per-model rates (its public catalogue page rendered empty), any top-up fees, and how it bills provider prompt caching.
- Azure UK South and provisioned-throughput prices, and whether `gpt-6.1-sol` is offered on Azure. The nearest listed model is GPT-6 Sol at $2 / $10 with $0.20 cached input.
- Azure SLA figures for these models.

## If adopted

- Re-record the evals once on the new providers within an owner-approved cap (`AGENTS.md` rule 3), and report cost and latency against the core metrics (E-EFF).
- Add Anthropic prompt-cache markers to the Advisor's system prompt, and record the cache-read share in `AgentStep` rows, so the saving is measured rather than assumed.

## Sources

- Mesh: https://meshapi.ai/pricing, https://meshapi.ai/terms, https://meshapi.ai/dpa
- OpenAI: https://developers.openai.com/api/docs/pricing, https://developers.openai.com/api/docs/guides/your-data
- Anthropic: https://platform.claude.com/docs/en/about-claude/pricing, https://platform.claude.com/docs/en/manage-claude/data-residency
- Azure: https://azure.microsoft.com/en-us/blog/gpt-6-astra-sol-and-luna-for-production-agents-in-microsoft-foundry/
