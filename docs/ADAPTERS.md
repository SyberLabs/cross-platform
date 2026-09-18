# Per-system adapter contract

For each adapter: how it is invoked, its lifecycle, what goes in and out, how
events propagate, what it persists, how it fails, how it cleans up, and what it
lets you observe.

---

## SyberRuntime — `adapters/syber_runtime_adapter.py`

**Invocation.** Direct in-process import of `syberruntime`. The package has no
third-party dependencies, so the real kernel runs inside the platform process.

**Lifecycle.** One `Runtime` per platform session, rooted at
`<scratch>/<session>/runtime`. `set_policy()` rebuilds the `Runtime` with a new
`FixedPolicy`; the operation log on disk is untouched, so only future accrual
changes. `reset()` deletes the session root and starts a fresh log.

**Inputs.** Thread intent; artifact name and content; `generative_mass`,
`blast_radius`, `criticality`; rigor profile and center debt budget;
deterministic check payloads (`text_contains`, `text_equals`, `sha256_equals`,
`python_tests`).

**Outputs.** `LogEntry` projections (index, entry hash, `operation.prev_hash`,
full operation record), `RuntimeState` (threads, artifacts, debt ledger),
verification results with attempted and discharged obligation ids, Merkle root,
inclusion proofs, replay determinism, runtime metrics, W3C PROV export.

**Event propagation.** Every call goes through `Recorder.run`. Feature and Test
events additionally carry `stateBefore` / `stateAfter` (total debt, open
obligation ids) so a change is legible as a change rather than as two unrelated
snapshots.

**Persistence.** `operations.jsonl` plus a blob store under the session scratch
root. Append-only and hash-chained. The repository checkout is read-only to this
adapter.

**Error behaviour.** `StabilizationBlockedError`, `BudgetExceededError` and
`LogIntegrityError` are declared refusals → `status: refused`, HTTP 409, with
the kernel's own message and a line-accurate source pointer. Anything else
propagates as an error with a traceback.

**Cleanup.** Session roots live under the OS temp directory and are disposable.
`POST /api/runtime/reset` removes one on demand.

**Observability.** The hash chain, the debt ledger with per-obligation
`incurred_debt` / `residual_debt` / `floor_required` / `status`, the exact check
that discharged an obligation (recorded verbatim in the operation log), and the
acceptance criteria list.

**Note on the acceptance gate.** `POST /api/runtime/acceptance` shells out to
`python -m syberruntime.cli acceptance-check` in the repository working tree and
returns what it printed. It is a subprocess precisely because the gate audits
that tree; running it in-process against a different root would audit the wrong
thing.

---

## Barn — `adapters/barn_adapter.py`

**Invocation.** `barn.api.create_app()` is mounted at `/systems/barn`, and the
adapter reuses **that application's own** `app.state.engine`.

There is therefore exactly one `BarnEngine`, one `InMemoryGraphStore` and one
set of per-run `asyncio.Lock`s. An operation driven from the platform UI and one
driven by an HTTP client hitting the mounted API are the same operation against
the same state. Two engines over one store would have had independent locks and
raced.

**Lifecycle.** `run_id` is held per session. The store is in-memory and lives as
long as the backend process.

**Inputs.** Run goal, `max_active_agents`, chief capabilities; work items with
required capabilities, dependencies, and a `requires_verification` flag;
specialist requests; artifacts; verifications; resolutions; retirements. Every
mutation carries a generated `command_id`, which is how Barn's idempotency works.

**Outputs.** `RunState` and the `BarnEvent` ledger as Barn serializes them,
`SpecialistDecision` (`spawned` / `reused` / `rejected` plus a reason),
`AuditReport`, `AgentExplanation`, `RunMetrics`.

**Event propagation.** `Recorder.arun` (async twin of `run`). The specialist
decision additionally records `agentCount` before and after and lifts
`outcome` / `reason` into the event's `evidence` field.

`summarize_run` is synchronous upstream; it is wrapped with `functools.wraps`
so `inspect.unwrap` still resolves provenance to `src/barn/metrics.py`, not to
the wrapper.

**Persistence.** In-memory, append-only events. Nothing is written to disk.

**Error behaviour.** `TransitionError` is the declared refusal type. Its message
is a bare snake_case token, which `refusal_code()` recognises and surfaces
directly: `artifact_required`, `passing_verification_required`,
`independent_verifier_required`, `agent_busy`, `work_terminal`,
`agent_missing_required_capability`, `work_dependencies_unresolved`,
`active_agent_budget_exhausted`, `capability_not_required`.

Note that a *rejected* specialist request is not an exception — Barn records it
as a committed `specialist.rejected` event with a reason. The UI shows it as a
decision, not as a refusal, because that is what Barn did.

**Cleanup.** None required; the store dies with the process.

**Observability.** The organization graph (assignment and `spawned_because`
edges), the event ledger, the materialized-vs-replayed hash comparison, and the
causal chain answering "why does this agent exist?".

---

## Bough — `adapters/bough_adapter.py`

**Invocation.** Direct in-process import of `bough`, over the `osahr` checkout
pinned by Bough's own `pyproject.toml`.

**Lifecycle.** The most recently compiled `MarkovAutomaton` is held per session
so that `reach`, `optimal_policy`, `path_probability` and `cypher` query the
same object the user just compiled.

**Inputs.** Family (`bits`, `ontology`, `machine`, `race`, `token_attach`,
`preempt`) with its real parameters, a `Horizon(max_depth, max_situations)`, and
a terminal label for `reach`.

**Outputs.** `CompilationReport` (situation count, uncoalesced count, compression
ratio, edge count, truncation, expand/refresh timings, derived stage count), a
serialized automaton, exact reach mass with distinct path count, per-situation
policy value and action, Cypher text.

**Event propagation.** `expand` and `refresh_probabilities` are recorded
separately, because they are separate passes: expansion is structural, refresh
is the incremental re-rate that populates edge probabilities.

**Persistence.** None. Compilation is deterministic and re-runnable.

**Error behaviour.** `BoughRefusal` is the declared refusal type and carries a
`reason` code: `TRUNCATED`, `CYCLIC_AUTOMATON`, `NOT_CHANCE`, `AMBIGUOUS_TRACE`,
plus the compile-time refusals `NON_EMPTY_Z`, `META_REWRITING`,
`DUPLICATE_EVENT`, `UNKNOWN_RULE`, `DECISION_WITH_HAZARD`.

**Cleanup.** None.

**Observability.** `_automaton_view` reads `edge.probability`, `situation.kind`,
`depth` and `label` off the compiled object. It computes nothing. Clicking a
situation shows its signature, kind, depth, label, out-degree, underlying
hypergraph size, and its raw outgoing edges.

---

## OSAHR Cell — inside `adapters/bough_adapter.py`

**Invocation.** In-process, through `bough.compare.agree_first_passage` — which
is upstream code. It drives OSAHR's `direct_ssa`, `next_reaction` and `thinning`
schedulers for real replicates and compares their empirical first-passage
frequency to Bough's exact answer.

**Attribution.** Both halves are recorded separately, because they belong to
different repositories. The comparison harness is Bough's code, so it is emitted
under `system: "bough"` with provenance `src/bough/compare.py`. The kernel work
is OSAHR's, so one event per scheduler is emitted under `system: "osahr"` with
provenance derived from `osahr.analysis.run_ensemble` — the function that
actually ran.

This matters: recording the harness under `"osahr"` would make
`Provenance.of` fall back to an absolute path, because `compare.py` is not in
the OSAHR checkout. The derivation refuses to produce a repo-relative path it
cannot justify, which is how the mis-attribution was caught.

**Inputs.** Family (`race` or `bits` — the only two with an upstream
first-passage predicate), replicate count, root seed.

**Outputs.** Per scheduler: empirical frequency, the exact value, a Hoeffding
radius at alpha 1e-6, and a `within_radius` verdict.

**Error behaviour.** Requesting a family with no upstream predicate raises
`KeyError` rather than inventing one.

**Observability.** The bar chart plots each scheduler's empirical frequency with
a tick at Bough's exact answer. Disagreement outside the radius would be shown
as such; it is not styled as success.

**Hypergraph inspector.** `osahr_model()` returns the kernel's own primitive for
any family: vertices with declared types and attributes, hyperedges with their
tail/head incidences and roles, and each `Rule` as declared — `left` graph,
`right` graph, hazard expression, guard, and chance/decision kind. Nothing is
summarized into a different shape. The only presentational change is that a
pattern variable renders as `?name` rather than `Var(name='name')`; the binding
is untouched.

This makes a rewrite legible as a rewrite: in the ontology fragment, `fail`
matches a `Route{up=true}` plus its `Available[2→1]` hyperedge and produces
`Route{up=false}` with the hyperedge deleted; `repair` puts it back.

---

## OSAHR 6G twin — `adapters/osahr_6g_adapter.py`

**Invocation.** Direct import of the repository's own
`osahr-6g/osahr_6g_experiment_release/semantic_6g_twin_experiment.py`. That
module builds the schema, rules and topology; the adapter calls `build_model`,
constructs the real `osahr.Runtime`, and injects the same `ExternalEvent`
outage pair and `ScheduledAdaptation` arrival-stop that the experiment's own
`run_one` injects. It defines no vertex type, rule or hazard.

**Lifecycle.** One live twin per session, held across requests so it can be
stepped interactively. `reset()` rebuilds from the same policy and seed.

**Inputs.** Routing policy (`semantic` / `qos` / `throughput`), root seed, and
how far to advance — one event, a batch, or a target simulated time.

**Outputs.** A snapshot of the live typed hypergraph (vertices with attributes,
hyperedges with role incidences), per-event records carrying the rule id, the
hazard it fired on, the total activity it was competing against, the match
bindings and the graph delta, plus `runtime.memory` and four derived ratios.

**Event propagation.** `start` goes through `Recorder.run` so `build_model`'s
provenance is derived. Stepping emits one summary `SyberEvent` per request
rather than one per kernel event, because a single run is ~285 events and the
stream is for user actions, not for the twin's internal clock.

**Streaming.** The kernel runs at roughly 25 events a second with full event
records, so advancing 35 simulated seconds is a ten-second wait.
`stream_to()` yields a frame every 8 events over SSE, which turns that from a
frozen request into the thing worth watching. The per-request event budget is
bounded so a request cannot hang.

**Persistence.** None; the twin lives in memory with the session.

**Error behaviour.** No twin started is a plain 400. A kernel `StepResult` with
no event is surfaced as a `stopped` reason rather than an empty success.

**Observability.** The visualization draws only what the snapshot contains.
Node positions are the one thing the frontend invents — the topology is fixed at
four UEs, two gNBs and two MEC nodes, so they are laid out in columns. Every
edge, attribute, load bar, availability flag and statistic is read from the
live runtime.

The `Transit` hyperedge is drawn as a junction with three spokes rather than a
line, because it binds four entities — source robot, task, gNB and edge node —
in one typed relation. That is the structure a pairwise graph cannot hold, and
it is the reason the model is a hypergraph.

---

## Relay — `adapters/relay_adapter.py` + `platform/relay-sidecar/server.mjs`

**Invocation.** A Node 24 sidecar imports the real `lib/*.ts` modules using
Node's native type stripping and exposes them over loopback JSON HTTP. Relay
requires Node ≥ 24 and is TypeScript, so this runs its actual code with no
transpile step, no vendoring and no reimplementation.

The demonstrated modules need nothing else: `lib/profile.ts`, `lib/scoring.ts`
and `lib/editor.ts` have **zero** imports, `lib/domain.ts` imports only
`lib/outcomes.ts`, and `lib/fit.ts` imports only `lib/profile.ts`. No database,
no Cloudflare bindings, no credentials, no `npm install`.

**Lifecycle.** The sidecar is started by `run.py` and dies with it. The adapter
holds one `httpx.AsyncClient`. `health()` is polled by `/api/systems`, so an
absent sidecar shows as an unavailable system rather than a broken page.

**Inputs.** Posting URLs; `relay.packet.v1` packets (schema, job identity and
version, cited facts, current draft); draft bodies; planning candidates with
`u`, `effort` and observed sent/response counts; an attention budget in minutes.

**Outputs.** Canonical job keys, extracted requirements, `unsupportedClaims`
findings with per-sentence claim classification, the bounded handoff prompt,
validated `relay.draft.v1` results, and portfolio selection with each
candidate's Beta-prior rate, freshness, tier and Relay's own one-line reason.

**Event propagation.** The sidecar returns a `provenance` block it resolved
itself with `import.meta.resolve`; the adapter passes it through unchanged and
never substitutes its own.

**Persistence.** None.

**Error behaviour.** Two distinct failures, kept distinct:

- Relay threw → the sidecar answers `{ok: false, refused: true, error}` and the
  adapter raises `SystemRefusal` → HTTP 409 with Relay's own message
  (`"Packet job identity does not match its URL."`,
  `"Add verified facts before requesting a draft."`,
  `"Download a fresh selected job packet from Relay."`).
- The sidecar is unreachable, or the assistant call failed → `RelayUnavailable`
  → HTTP 503 marked `unavailable`. This is a dependency failure, not a Relay
  decision, and the UI says so.

**Cleanup.** The sidecar terminates with the launcher.

**The one model call.** `handoff()` is the only path that touches an external
model:

1. Relay bounds the context and writes the prompt (`assistantPrompt`).
2. An external assistant drafts — a live HTTPS call, or an operator-supplied
   draft. This is the only step outside Relay.
3. Relay re-validates the result against job identity and version
   (`assistantResult`).
4. Relay's claim gate reports which sentences the cited facts do not support
   (`unsupportedClaims`).

Steps 1, 3 and 4 are upstream Relay code. The assistant cannot write Relay
state, change job identity or grant acceptance. Live inference is off by
default, is explicitly triggered, never polls, and emits its own boundary event
so the moment context leaves the system is visible in the stream.

`_extract_draft` reads the `draft` field out of a compliant JSON reply and
otherwise passes the raw text straight through, so Relay's own validator — not
this adapter — decides whether a malformed response is acceptable.

`_facts_from_packet` splits the packet's free-text facts block into `Fact` rows.
That is a transport detail; the grounding decision itself is entirely
`lib/profile.ts`.

---

## Bridge: Barn → Bough — `adapters/bridge_barn_bough.py`

**Status.** This is the only module in the platform that contains code the
source repositories do not already have, and it exists because one of them asks
for it: `bough_and_barn/docs/INTEGRATION_PLAN.md` §8 specifies an additive
`barn_bough/` package (`twin.py`, `calibrate.py`, `advise.py`) and states that
Barn and Bough remain independently installable because nothing in it changes
their public surfaces. It lives in the adapter layer, never inside either repo.

**What it does.** Per §7: project the current `RunState` into a Bough twin,
`expand` it, run `optimal_policy` for the root action and value, and `reach` for
each branch's success probability. It emits
`SpawnAdvice {action, value, reach_probability, truncated, repertoire_hash}`.

**What it does not do.** Authorize anything. `authoritative` is hard-coded
`False`. Barn's engine still makes and enforces every decision, and the UI shows
the committed decision next to the advice, flagging disagreement rather than
resolving it.

**Twin design.** §6.1 requires abstracting away identity and counters or nothing
coalesces, so a capability gap is one `Org` vertex in phase `decide`, with two
decision rules (`spawn`, `reuse`) leading to two chance sub-problems. Decision
rules carry `Expr("0")` because `bough.kinds.validate_event` refuses a decision
with a real hazard.

**Calibration.** `calibrate()` derives hazards from the run's own
`RunMetrics` and `max_active_agents` with Laplace smoothing, and returns a
`basis` dict naming every input it used. The UI displays that basis, so the
number is never shown as better evidenced than it is.

**A real constraint, respected.** `reach()` from the twin's root is refused with
`NOT_CHANCE` — correctly, because a decision node has no probability. §7 asks
for the probability "for that action versus the alternative", which is per
branch. Each branch target is a chance node, so the query is re-rooted there
with `dataclasses.replace(automaton, root=edge.target)`. That re-points the root
of the same compiled automaton; nothing is rebuilt or recomputed.

**Error behaviour.** Any `BoughRefusal` propagates as a refusal and is rendered
in place of the advice.
