# Fidelity matrix

No capability appears in the interface until this table can truthfully say
**Real execution: Yes**.

"Real execution" means the behaviour was produced by the source repository named,
in that repository's own code, during the interaction — not reproduced in the
frontend, not replayed from a fixture, not approximated.

Every row is checkable at runtime: the event that capability emits carries a
provenance record derived by introspecting the callable before it ran, and the
UI will serve you that exact file from that system's checkout.

## SyberRuntime

| Demonstrated capability | Real execution | Symbol that ran | UI representation |
| --- | :-: | --- | --- |
| Verification debt accrual from mass × radius × criticality × accrual rate | Yes | `runtime.Runtime.record_feature` | Debt ledger, incurred vs residual |
| Floor obligation creation under a rigor profile | Yes | `debt.feature_obligation_payload` | Debt ledger, `floor` column |
| Fail-closed stabilization refusal | Yes | `runtime.Runtime.stabilize` → `StabilizationBlockedError` | Refusal notice + source drill-down |
| Obligation discharge by a deterministic check | Yes | `runtime.Runtime.record_test` → `verification.DeterministicVerifier.run` | Verify action, discharged-obligation count |
| Failing check leaves debt open | Yes | same; `discharged_obligations` stays empty | Refusal persists on next stabilize |
| Center debt budget enforcement | Yes | `runtime.Runtime._enforce_budget` → `BudgetExceededError` | Refusal notice |
| Hash-chained operation log | Yes | `operation_log.OperationLog.append` / `.entries(validate=True)` | Operation log, entry hash + `prev_hash` |
| Merkle root over log history | Yes | `merkle.MerkleHistoryTree` | Evidence panel |
| Inclusion proof | Yes | `operation_log.OperationLog.inclusion_proof` | Evidence panel |
| Deterministic replay equality | Yes | `runtime.Runtime.replay_is_deterministic` | Evidence panel |
| Chain integrity revalidation | Yes | `operation_log` validation → `LogIntegrityError` | Evidence panel |
| Runtime metrics | Yes | `metrics.compute_runtime_metrics` | Evidence panel |
| W3C PROV export | Yes | `export.export_prov_document` | Evidence panel |
| Release-readiness gate failing closed on absent evidence | Yes | `python -m syberruntime.cli acceptance-check` (subprocess, real working tree) | Acceptance panel, per-criterion status |

## Barn

| Demonstrated capability | Real execution | Symbol that ran | UI representation |
| --- | :-: | --- | --- |
| Run creation with a chief agent and goal work item | Yes | `engine.BarnEngine.create_run` | Organization graph |
| Work item creation with required capabilities and dependencies | Yes | `engine.BarnEngine.add_work` | Work table |
| Spawn / reuse / reject licensing decision | Yes | `engine.BarnEngine.request_specialist` | Decision notice with Barn's own reason |
| `capability_gap_licensed` spawn | Yes | same | Decision notice |
| `existing_compatible_agent` reuse | Yes | same | Decision notice |
| `active_agent_budget_exhausted` rejection | Yes | same | Decision notice |
| `capability_not_required` rejection | Yes | same | Decision notice |
| Resolve without an artifact refused | Yes | `engine.BarnEngine.resolve_work` → `artifact_required` | Refusal notice + source |
| Resolve without passing verification refused | Yes | same → `passing_verification_required` | Refusal notice |
| Producer verifying own artifact refused | Yes | `engine.BarnEngine.record_verification` → `independent_verifier_required` | Refusal notice + source |
| Artifact submission | Yes | `engine.BarnEngine.submit_artifact` | Artifact list |
| Materialized state hash vs state replayed from the event log | Yes | `audit.audit_run` → `replay.replay_run` | Replay audit, both hashes shown |
| Causal "why does this agent exist?" | Yes | `causal.why_agent_exists` | Trace drawer, work → capability → request → agent |
| Run metrics | Yes | `metrics.summarize_run` | Metrics |
| Append-only event ledger | Yes | `store.InMemoryGraphStore.list_events` | Event ledger |
| Barn's own HTTP API, unmodified | Yes | `barn.api.create_app()` mounted at `/systems/barn` | Linked from the instrument |

## Bough

| Demonstrated capability | Real execution | Symbol that ran | UI representation |
| --- | :-: | --- | --- |
| Rewrite system compiled to a coalesced jump chain | Yes | `expand.expand` | Jump-chain graph |
| Compression ratio (33 → 16 at bits n=4) | Yes | `report.report` / `ir.MarkovAutomaton.compression_ratio` | Compilation report |
| Edge probabilities after the incremental re-rate pass | Yes | `incrementality.refresh_probabilities` | Numbers on graph edges |
| Exact reach mass and distinct path count | Yes | `infer.reach` | reach() result |
| Refusal on a cyclic automaton | Yes | `infer._assert_dag` → `BoughRefusal("CYCLIC_AUTOMATON")` | Refusal notice + source |
| Refusal on a truncated expansion | Yes | `infer._assert_not_truncated` → `TRUNCATED` | Refusal notice |
| Refusal to run reach from a decision node | Yes | `infer.reach` → `NOT_CHANCE` | Refusal notice |
| Backward-induction optimal policy | Yes | `policy.optimal_policy` | Policy result, root value and action |
| Derived staging | Yes | `staging.stage` | Compilation report |
| Neo4j inspection Cypher export | Yes | `cypher.automaton_to_cypher` | Drawer (generated, never pushed — no credentials) |
| Exact path probability along a trace | Yes | `infer.path_probability` | API route |

## OSAHR Cell

| Demonstrated capability | Real execution | Symbol that ran | UI representation |
| --- | :-: | --- | --- |
| `direct_ssa` scheduler replicates | Yes | `osahr.analysis.run_ensemble` (`SchedulerKind.DIRECT_SSA`) | Agreement bar |
| `next_reaction` scheduler replicates | Yes | same, `SchedulerKind.NEXT_REACTION` | Agreement bar |
| `thinning` scheduler replicates | Yes | same, `SchedulerKind.THINNING` | Agreement bar |
| Empirical first-passage frequency vs an exact analytic answer | Yes | `bough.compare.first_passage_frequency` (Bough), over the above (OSAHR) | Bar with exact-value tick |
| Hoeffding confidence radius at alpha 1e-6 | Yes | `bough.compare.hoeffding_radius` | `within_radius` verdict |
| Typed hypergraph: vertices with declared types and attributes | Yes | `osahr.graph.Hypergraph.vertices` | Hypergraph inspector |
| Typed hyperedges with tail/head incidences and roles | Yes | `osahr.graph.Hypergraph.edges` / `Incidence` | Hyperedge table |
| Rewrite rules as declared (left ⟶ right, hazard, chance/decision) | Yes | `osahr.pattern.Rule` (`left`, `right`, `hazard`, `guard`) | Rewrite-rule table |
| Rule repertoire hash | Yes | `bough.spec.repertoire_hash` | Hypergraph inspector |

The harness and the kernel are recorded as separate events against separate
repositories: `src/bough/compare.py` for the comparison, `osahr/analysis.py` for
each scheduler run.

### The 6G semantic twin

`osahr-6g/osahr_6g_experiment_release/semantic_6g_twin_experiment.py` is a
committed experiment in the OSAHR repository: a RAN/MEC digital twin with four
robot UEs, two gNBs and two MEC nodes, under three routing policies and a
mid-run edge outage. The platform imports that module and drives its model; it
builds no topology, no rule and no hazard of its own.

| Demonstrated capability | Real execution | Symbol that ran | UI representation |
| --- | :-: | --- | --- |
| RAN/MEC topology, schema and rule repertoire | Yes | `semantic_6g_twin_experiment.build_model` | Network canvas |
| Event-by-event stochastic execution | Yes | `osahr.Runtime.step` | Animated frames |
| Rule firing with its hazard and competing activity | Yes | `EventRecord.cause` | Kernel event feed |
| Graph rewriting (tasks appear, Transit binds and dissolves) | Yes | `EventRecord.graph_delta` | Live nodes and hyperedges |
| 4-ary `Transit` hyperedge over (source, task, gNB, edge) | Yes | `osahr.graph.Hyperedge` incidences | Junction with three spokes |
| Edge outage arriving through an open boundary | Yes | `Runtime.inject(ExternalEvent)` | `external_input` event, MEC node marked down |
| Scheduled parameter adaptation (arrivals stop) | Yes | `Runtime.schedule_adaptation` | Timeline marker |
| Policy-dependent routing preference | Yes | `_route_hazard(policy)` | Policy selector + hazard per event |
| Sufficient statistics and goal-utility ratio | Yes | `runtime.memory` | Statistics panel |
| Association rewiring on handover | Yes | `handover` rule | UE→gNB edges move |

The three policies are the experiment's own: `throughput` sees rate, link, load
and energy; `qos` adds reliability and fidelity; `semantic` adds
`utility/deadline x reliability x fidelity`, which is the only one that can see
what a task is worth. Switching policy rebuilds the model from the same source
function — the platform does not reweight anything itself.

## Relay

| Demonstrated capability | Real execution | Symbol that ran | UI representation |
| --- | :-: | --- | --- |
| Canonical posting identity (alias resolution, tracking-param removal) | Yes | `lib/domain.ts` `jobKey` | Identity panel |
| Packet validation | Yes | `integrations/connectors.mjs` `validatePacket` | API route |
| Packet identity mismatch refused | Yes | same → "Packet job identity does not match its URL." | Refusal notice |
| Empty cited facts refused | Yes | same → "Add verified facts before requesting a draft." | Refusal notice |
| Stale packet version refused | Yes | `lib/assistant-handoff.ts` `selectedPacket` | Refusal notice |
| Bounded handoff prompt construction | Yes | `lib/assistant-handoff.ts` `assistantPrompt` | Handoff timeline + prompt drawer |
| Returned-draft identity/version validation | Yes | `lib/assistant-handoff.ts` `assistantResult` | Handoff timeline |
| Ungrounded-claim gate | Yes | `lib/profile.ts` `unsupportedClaims` | Claim gate, per-sentence ✓/✕ |
| Claim-sentence classification | Yes | `lib/profile.ts` `isClaim` / `sentences` | Claim gate |
| Fact usability (expiry, status) | Yes | `lib/profile.ts` `usableFact` | Claim gate payload |
| Requirement extraction from posting text | Yes | `lib/fit.ts` `extractRequirements` | API route |
| Beta-prior response rate | Yes | `lib/scoring.ts` `responseRate` | Planning table |
| Posting freshness decay | Yes | `lib/scoring.ts` `freshness` | Planning table |
| Expected-maximum objective | Yes | `lib/scoring.ts` `expectedMax` | Planning summary |
| Greedy portfolio under an attention budget | Yes | `lib/scoring.ts` `selectPortfolio` | Planning table, `in` marks |
| Per-candidate selection reason | Yes | `lib/scoring.ts` `reason` | Planning table |
| Import status classification and merge | Yes | `lib/domain.ts` `importedJobStatus` / `mergeJobStatus` | API route |
| Live assistant draft | Yes (external) | Google Generative Language API | Handoff timeline, marked as outside Relay |

## Cross-system seams

| Seam | Real execution | Where it comes from | UI representation |
| --- | :-: | --- | --- |
| Bough exact probability vs OSAHR kernel schedulers | Yes | already upstream: `bough/compare.py` | OSAHR instrument |
| Barn heuristic decision vs Bough value-optimal action | Yes | bridge specified by `bough_and_barn/docs/INTEGRATION_PLAN.md` §5/§7/§8, implemented in `adapters/bridge_barn_bough.py` | Advice block beside the committed decision |
| Relay draft becomes a SyberRuntime verification obligation | Yes | `assistantResult` → `runtime.record_feature` → `runtime.stabilize` | Cross-system drawer |

---

## Scenarios

The guided scenarios are **input configuration, not playback**. Each step calls
the same adapter method the interface's controls call, against the same session.
No step has a recorded result.

Every step declares an expectation; the runner compares it to what happened and
labels any mismatch `UNEXPECTED` in the interface rather than smoothing it over.
All 37 steps across the six scenarios currently match — verified by running the
full catalog against the live platform.

| Scenario | Steps | Refusals it provokes, for real |
| --- | --: | --- |
| `runtime-fail-closed` | 8 | `StabilizationBlockedError` twice — once before any check, once after a *failing* one |
| `barn-independence` | 11 | `artifact_required`, `independent_verifier_required`, `passing_verification_required` |
| `bough-exact-or-refuse` | 5 | `CYCLIC_AUTOMATON` |
| `osahr-two-ways` | 3 | — (structural inspection plus the scheduler cross-check) |
| `relay-handoff` | 5 | packet identity mismatch, stale job version |
| `cross-relay-runtime` | 5 | `StabilizationBlockedError` on a draft Relay marked `reviewRequired` |

## What is *not* real, stated plainly

Nothing in the interface is presented as a capability that is not executed. The
items below are the boundaries of what the platform demonstrates.

**SyberRuntime's acceptance gate reports `fail` here.** The criteria it audits
(`dogfooding_rq0_rq6_results`, `agentic_intent_harness_baseline`,
`agentic_intent_harness_live_smoke`, `live_scale3_campaign`,
`live_code_behavioral_campaign`) bind to an evidence corpus stored in gitignored
`.syberruntime-*/` run directories. A fresh clone does not have it, so the gate
fails closed and names each missing criterion. The platform shows that result
verbatim. This is the gate working, not the platform failing.

**Two Barn tests fail upstream.** `test_benchmark.py` and
`test_provider_benchmark.py` fail on a clean checkout; the Barn README already
documents that committed comparison as a synthetic smoke test that is
"intentionally *negative* for Barn on inference efficiency". The platform does
not use the benchmark harness and makes no claim about specialization improving
outcomes — neither does Barn.

**Cypher is generated, never pushed.** No Neo4j credentials exist in this
environment. `try_push_cypher` is not called. Both source repositories are
already fail-closed about this rather than fabricating a push result.

**The Barn→Bough twin is a shape, not a fitted model.** It is calibrated from a
single short run with Laplace smoothing. Every advice block displays its
calibration basis — the artifact and verification counts, budget headroom and
smoothed evidence rate it was derived from — so the number is never shown as
better evidenced than it is. The integration plan's own §7 requires that the
advisor "must *demonstrate* an advantage under matched budgets before it is
allowed to change outcomes online"; it has not, so it changes nothing.

**Barn's provider-backed runs are not exercised.** The Qoder worker runtime and
Neo4j projection require SDKs and credentials that are not present. Barn's live
probes are fail-closed about this already.

**Relay's persistence layer is not exercised.** Only its pure domain modules
run. `lib/obsidian.ts` (needs the `yaml` package), the D1 database, the
Cloudflare Workers runtime, `/api/workspace` authorization and the React
interface are all outside what the sidecar imports. The handoff demonstrated
here is the real handoff *logic*; it does not write a workspace.

**The live assistant is an external system.** When live inference is enabled,
the draft text comes from Google's API, not from Relay or from this platform.
The handoff timeline marks that step as external and shows the trust boundary on
both sides. The assistant cannot write Relay state, change job identity or grant
acceptance — that is enforced by `assistantResult`, which runs after it.

**`_facts_from_packet` is a transport shim.** Relay stores cited facts as a text
block in a packet; `unsupportedClaims` takes `Fact` rows. Splitting that block
on lines is done in the adapter. The grounding decision itself — which sentences
count as claims, and which are supported — is entirely `lib/profile.ts`.

**The bridge module is the one piece of new logic.** `bridge_barn_bough.py`
builds a twin graph and supplies a terminal value function. It computes no
probability itself: `expand`, `optimal_policy` and `reach` are all Bough. It
lives in the adapter layer and neither repository depends on it.
