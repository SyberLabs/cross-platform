# Architecture

## The one rule

The platform is an instrumentation and interaction layer. It contains
orchestration, adaptation, observability and UI. It contains no reimplementation
of any source system's behaviour.

```text
SyberLabs platform
        ↓
    adapters
        ↓
existing systems          ← never the other way round
```

Concretely, this means the platform can be deleted and every repository under
`systems/` still runs exactly as it did before. Barn's own FastAPI application
is mounted unmodified and remains reachable at `/systems/barn`, which is the
clearest possible demonstration of that property: the source system's real
interface is right there, unwrapped.

## Layers

```text
platform/frontend            instrument panel (vanilla ES modules, no build step)
        │  fetch + Server-Sent Events
platform/backend/main.py     routes, session registry, SSE fan-out, source server
        │
platform/backend/contract.py SyberEvent, Recorder, derived Provenance
        │
platform/backend/adapters/   one module per system, thin and replaceable
        │
systems/                     the source repositories
```

### Why a build-free frontend

The frontend has no bundler, no framework and no `node_modules`. This is not
minimalism for its own sake: it keeps the only Node dependency in the whole
project the Node 24 runtime that Relay itself requires. A visitor can read
`instruments.js` and see, directly, that no system logic lives there.

## Choosing an integration mechanism

For each system the least invasive mechanism that preserves its semantics was
chosen, in this order of preference: in-process import → mounted application →
sidecar process → subprocess.

| System | Mechanism | Why not something lighter |
| --- | --- | --- |
| SyberRuntime | in-process import | Nothing lighter exists. Zero third-party dependencies, so the real kernel simply runs in the platform process. |
| Bough | in-process import | Same. The compiled `MarkovAutomaton` object is serialized for the graph inspector; no value is recomputed. |
| OSAHR | in-process import | Driven through Bough's own `compare` module, which is the upstream cross-check. |
| Barn | mounted ASGI app | Barn's engine is async and holds per-run locks. Mounting `create_app()` and reusing **its** `app.state.engine` guarantees one engine, one store and one lock set for both the UI and the raw API. |
| Relay | Node 24 sidecar | Relay is TypeScript and requires Node ≥ 24. A sidecar using native type stripping runs the real `.ts` files with no transpile, no vendoring and no npm install. |
| SyberRuntime acceptance gate | subprocess | The gate is a CLI audit over the repository's own working tree. Running it any other way would change what it audits. |

## The observability contract

Every adapter emits `SyberEvent`s into a per-session `EventSink`, which fans out
over SSE. The contract is deliberately thin:

```python
SyberEvent(
    system, eventType, timestamp, seq, status,      # ok | refused | error
    label, durationMs,
    input, output, stateBefore, stateAfter, evidence,
    provenance, error, metadata,
)
```

It is an *observability language*, not a model of the systems. Anything
system-specific stays intact inside `output` / `evidence` and is shown raw in
the inspector, so nothing is flattened into a lowest common denominator.

### Provenance is derived, not declared

This is the part that makes the whole thing checkable.

`Provenance.of(system, fn)` runs `inspect.unwrap(fn)` and reads the module file
and line number **off the function object that is about to be called**:

```python
source_file = inspect.getsourcefile(target)
module_path = resolved.relative_to(_REPO_ROOTS[system])
_, line     = inspect.getsourcelines(target)
```

An adapter therefore cannot claim that Bough computed something while calling
its own code. If it did, the recorded path would be
`platform/backend/adapters/...`, not `src/bough/...`, and the path is rendered
in the UI on every event.

`GET /api/source` then serves that exact file from that system's checkout,
confined to it, so a visitor can go:

```text
visual representation → structured event → raw payload → the source that ran
```

The Relay sidecar is outside this process, so it resolves and reports its own
module paths with `import.meta.resolve`; the value is still observed rather than
asserted by the Python side.

### Refusals are first-class

`Recorder.run` takes a `refusals=` tuple naming the exception types that are
*meaningful system behaviour* rather than adapter bugs:

- `StabilizationBlockedError`, `BudgetExceededError`, `LogIntegrityError` (SyberRuntime)
- `TransitionError` (Barn)
- `BoughRefusal` (Bough)
- plain `Error` with a user-facing message (Relay)

Those are recorded with `status: "refused"`, re-raised as a structured
`SystemRefusal`, and returned to the browser as **HTTP 409** carrying the
system's own message, its own refusal code and its provenance. They are never
swallowed and never rewritten. Each system spells its code differently — Bough
uses `reason`, Barn's message *is* the code, SyberRuntime uses the exception
class — so `refusal_code()` reads each idiom and returns `None` rather than
inventing one when a system offers none.

Genuine bugs are separate: they are recorded with `status: "error"` and a
traceback, and still shown.

### Causal attribution

`SyberEvent` carries `operationId` (the action that caused it) and `parentId`
(the enclosing scenario run, if any). Neither is threaded through the adapters.
A `contextvars.ContextVar` holds an `EventContext`, set in two places:

- an HTTP middleware, so every event caused by one request shares an id;
- the scenario runner, per step, which also sets `parentId` to the run.

`EventSink.emit` fills the fields from that context. Putting it at the single
point every event passes through means an adapter cannot emit an unattributed
event, and adding a sixth system needs no work to participate.

## Scenarios

`scenarios.py` declares, per system, a list of
`Step(title, plain, technical, run, expect, expect_code, note, headline)`.
`run` is a plain callable taking `(session, bag)` and calling the same adapter
method the UI's controls call; `bag` carries ids between steps.

`plain` and `technical` are two readings of the same event — ordinary language
and the mechanism — rendered side by side rather than one summarizing the other.
`headline` names the single result key that carries the step's meaning, so the
interface can lead with `RESIDUAL DEBT 3` instead of a uniform field dump.

The runner is an async generator streamed over SSE, so the interface narrates a
step, shows its real result, and moves on — while the underlying adapter calls
emit their ordinary events to the ordinary stream.

Pacing lives in the runner rather than the transport, because it is part of the
presentation: a step is shown, given `_reading_seconds()` scaled to its own text,
and only *then* executed. The pause sits ahead of the call, so the narration and
the execution still coincide — the viewer is not reading a buffered replay. Three
paces are offered (`slow`, `normal`, `fast`) and passed as a query parameter.

The important property is that a scenario **cannot lie about an outcome**. It
declares an expectation and reports reality separately:

```python
record["matched"] = _matched(step, record)
record["verdict"] = _verdict(step, record)
```

A step expecting `StabilizationBlockedError` that instead succeeds is rendered
as `UNEXPECTED: the scenario expected a refusal and the system allowed it. The
scenario is wrong, or the system changed.` That is what makes a narrated demo
safe to put in front of someone: the narration is a prediction, and the
prediction is checked.

## Sessions

One `Session` per `x-syber-session` header holds an `EventSink` and one adapter
of each kind. SyberRuntime gets a scratch-directory root per session; the
repository checkout is never written to. Appending `?session=<name>` to the URL
starts a clean bench, which is how the browser tests get reproducible state.

## Adding a sixth system

Implement one adapter module that:

1. imports (or reaches) the real system;
2. wraps each call in `Recorder.run` / `Recorder.arun` with the system's own
   refusal types;
3. returns the system's real objects, projected to JSON without recomputation.

Then add routes in `main.py` and one `render()` in `instruments.js`. Nothing in
the contract, the stream, the inspector or the source viewer needs to change.
