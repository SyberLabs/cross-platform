# Phase 1 — Integration Map

Established by reading and executing the repositories, not by reading their
READMEs. Every claim below is backed by a command that was run in this
environment. Version pins are recorded so the map can be re-verified.

| System | Checkout | HEAD | Language | Required deps |
| --- | --- | --- | --- | --- |
| SyberRuntime | `systems/syber_runtime` | `5251df5` | Python 3.11+ | none |
| Barn | `systems/bough_and_barn/barn` | `bough-and-barn` HEAD | Python 3.11+ | fastapi, pydantic, uvicorn |
| Bough | `systems/bough_and_barn/bough` | same | Python 3.11+ | `osahr @ 59cbe0c` |
| OSAHR Cell | `systems/osahr` | `59cbe0c` | Python 3.11+ | none |
| Relay | `systems/relay` | `3d5bb3c` | TypeScript | Node >= 24 (native type-strip) |

`systems/osahr` HEAD is byte-identical to the commit Bough pins
(`osahr @ git+...@59cbe0c3ebef2f8c972a7745009c7d60d0c5fe3a`), verified with
`git merge-base --is-ancestor`. One editable install therefore serves both the
Bough compiler and the direct OSAHR instrument with no version skew.

---

## SyberRuntime

```text
core primitive      Operation. An append-only, hash-chained operation log is the
                    source of truth; artifacts are projections folded from it;
                    verification debt is bounded accounting over obligations.
entry point         syberruntime.Runtime(root)  (in-process facade)
                    python -m syberruntime.cli  (21 subcommands)
observable state    LogEntry.entry_hash / prev_hash chain, RuntimeState
                    (threads, artifacts, DebtLedger), Merkle root, inclusion and
                    consistency proofs, RuntimeMetrics, acceptance criteria
user inputs         intent, artifact text, generative_mass / blast_radius /
                    criticality, rigor profile, center debt budget
meaningful output   accrued debt + floor obligations, refusal to stabilize,
                    obligation discharge, deterministic replay equality,
                    cryptographic inclusion proof
visualization       operation ledger, debt ledger, evidence inspector, hash chain
integration         direct Python import (zero third-party dependencies)
adapter needs       per-session runtime root under a scratch dir; no repo writes
failure modes       StabilizationBlockedError (open floor obligations),
                    BudgetExceededError (center debt cap), LogIntegrityError
                    (chain tamper), acceptance-check fail-closed on absent evidence
```

Verified: `python -m unittest discover -s tests` -> 80 passed, 3 failed. The 3
failures are `test_phase5_acceptance` and are **the fail-closed gate working**:
the evidence corpus those criteria audit lives in gitignored `.syberruntime-*/`
run directories, so a fresh clone cannot assert acceptance. `acceptance-check`
on the fresh clone reports `overall_status: fail` naming each missing criterion.
This is surfaced in the UI rather than papered over.

One environment correction was required and is **not** a semantic change: the
clone was re-checked-out with `core.autocrlf false`. Git's CRLF conversion
altered `docs/rq0_rq6_preregistration.md`, changing its sha256 and breaking the
`protocol_sha256` binding the dogfood criterion checks. This is checkout
hygiene, not a modification of SyberRuntime.

## Barn

```text
core primitive      BarnEvent. Every organizational mutation is append-only and
                    licensed by a deterministic transition engine. No model call
                    mutates authoritative state.
entry point         barn.api.create_app() -> FastAPI ASGI application
observable state    run snapshot (agents, work_items, artifacts, verifications),
                    event ledger, AuditReport, AgentExplanation, RunMetrics
user inputs         work items + required capabilities, specialist requests,
                    artifacts, verifications, resolutions, retirements
meaningful output   SpecialistDecision {SPAWNED | REUSED | REJECTED, reason},
                    named TransitionError refusals, materialized-vs-replayed hash
visualization       organization graph, event ledger, causal "why" chain,
                    audit hash comparison
integration         mount the real create_app() as an ASGI sub-application
adapter needs       none beyond mounting; in-memory store is the default
failure modes       artifact_required, passing_verification_required,
                    independent_verifier_required, agent_busy, work_terminal,
                    agent_missing_required_capability, work_dependencies_unresolved,
                    active_agent_budget_exhausted, capability_not_required
```

Verified: `pytest -q` -> 60 passed, 2 failed. Both failures are in
`test_benchmark.py` / `test_provider_benchmark.py`, the synthetic comparison
harness the repository README already documents as "intentionally *negative* for
Barn on inference efficiency". The transition, replay, audit and orchestration
suites pass. The benchmark harness is not used by this platform.

## Bough

```text
core primitive      A typed hypergraph rewrite system compiled into an
                    exhaustively coalesced jump chain (Markov automaton) with
                    exact path and reachability probabilities.
entry point         bough.expand / reach / optimal_policy / automaton_to_cypher
                    python -m bough {bits, ontology, machine, c2, cypher}
observable state    Situation {signature, kind(chance|decision|terminal), depth,
                    label}, Edge {rule_id, match_id, probability},
                    compression_ratio, reach mass + distinct path count,
                    optimal_policy value/action per situation
user inputs         family + parameters (bits n, ontology copies), horizon
                    (max_depth, max_situations), target terminal label
meaningful output   exact probabilities, coalesced automaton, value-optimal action
visualization       the jump chain itself, stratified by depth and node kind
integration         direct Python import
adapter needs       serialize Situation/Edge to JSON; none semantic
failure modes       BoughRefusal: TRUNCATED, CYCLIC_AUTOMATON, NOT_CHANCE,
                    AMBIGUOUS_TRACE
```

Verified: `pytest -q` -> 34 passed. `python -m bough bits -n 4` reproduces the
README headline exactly: 33 uncoalesced states compressed to 16
(ratio 2.0625), `reach(all-on) = 1.0` over 24 distinct paths.
`python -m bough machine` selects **protect** with root value 1.0.

## OSAHR Cell

```text
core primitive      Typed directed hypergraph under a stochastic adaptive
                    rewrite kernel with interchangeable exact schedulers.
entry point         osahr.Model / osahr.graph.Hypergraph / osahr.schedulers
observable state    hypergraph nodes and hyperedges, enabled matches, scheduler
                    trajectories, first-passage outcomes
meaningful output   empirical first-passage frequency per scheduler with a
                    confidence radius, checkable against an exact answer
visualization       hypergraph structure; empirical-vs-exact agreement
integration         direct Python import, and through Bough's compare module
adapter needs       none
failure modes       kernel refusals; scheduler disagreement outside radius
```

Verified: `python -m bough c2 --replicates 24` runs `direct_ssa`,
`next_reaction` and `thinning` against the exact jump-chain answer. The C2 race
model yields `exact_reach_a = 2/3` and all three independent kernel schedulers
land within the reported confidence radius.

## Relay

```text
core primitive      An explicit handoff. Bounded context leaves the system, an
                    external assistant drafts, and the result is re-validated
                    against job identity and version before it can be reviewed.
                    Relay owns acceptance; the assistant owns nothing.
entry point         the real lib/*.ts modules, imported under Node 24 native
                    type stripping; integrations/relay.mjs CLI
observable state    canonical job key, packet contents, handoff prompt, returned
                    relay.draft.v1, unsupported claims, version conflicts
user inputs         posting URL, verified facts, draft body, job version
meaningful output   jobKey canonicalization, assistantPrompt (bounded context),
                    assistantResult validation, unsupportedClaims gate,
                    responseRate / selectPortfolio planning
visualization       handoff timeline with trust boundaries, claim-grounding gate
integration         Node 24 sidecar importing the real .ts modules
adapter needs       sidecar process; no database, no credentials, no npm install
failure modes       "Packet job identity does not match its URL",
                    "Download a fresh selected job packet from Relay" (version),
                    unsupported-claim findings, oversized draft rejection
```

Verified directly against the real modules under Node 24:
`jobKey('https://boards.greenhouse.io/acme/jobs/123?utm_source=x&gh_src=abc')`
-> `greenhouse:acme:123` (Greenhouse alias resolved, tracking parameters
stripped). `unsupportedClaims(...)` correctly flags
`"I also led a team of 12 engineers."` as ungrounded while accepting the claim
covered by a cited verified fact. `lib/profile.ts`, `lib/scoring.ts` and
`lib/editor.ts` have **zero** imports; `lib/domain.ts` imports only
`lib/outcomes.ts`; `lib/fit.ts` imports only `lib/profile.ts`. None of the
demonstrated functions touch the database or Cloudflare bindings.

---

## Cross-system seams

Only seams the source systems already define are implemented.

1. **Bough -> OSAHR** — already implemented upstream as `bough c2`
   (`bough/compare.py::agree_first_passage`). Exact jump-chain probability is
   checked against three real OSAHR kernel schedulers. The platform invokes it;
   it does not reimplement it.

2. **Barn -> Bough (advisor)** — specified by the source repository itself in
   `bough_and_barn/docs/INTEGRATION_PLAN.md` sections 5, 7 and 8, which describe
   an additive `barn_bough/` bridge emitting
   `SpawnAdvice {action, value, reach_probability, truncated, repertoire_hash}`
   and state that the advisor is **a suggestion, never an authorization**:
   Barn's engine still enforces every hard invariant, and with the advisor
   disabled behavior is byte-identical to Barn v0. The platform implements this
   bridge in its own adapter layer, never inside either repository, and the UI
   always shows Barn's committed decision alongside — and distinct from — the
   advice.

3. **Relay -> SyberRuntime** — a Relay handoff produces a draft that
   `relay.draft.v1` marks `reviewRequired: true`. That is precisely an
   unverified artifact in SyberRuntime's grammar: recording it as a Feature
   accrues a floor verification obligation, and stabilizing before human review
   is refused by the real `StabilizationBlockedError`. The two systems' review
   semantics compose without either being modified.

Rejected as manufactured: routing Relay text through OSAHR, projecting
SyberRuntime operations into a Bough automaton, and any Neo4j-backed join (no
credentials exist; both repositories' live probes are already fail-closed about
this).
