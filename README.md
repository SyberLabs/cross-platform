# SyberLabs — Instrument Panel

A single platform through which five real SyberLabs systems can be run,
inspected and understood interactively.

Nothing here simulates those systems. Every number, refusal, hash and graph the
interface shows was produced by the source repository named next to it, and any
event in the stream can be opened to read the exact source file and line that
produced it.

```text
                    ┌───────────────────────────┐
                    │  Instrument panel (SPA)   │
                    └─────────────┬─────────────┘
                     interaction / instrumentation
                    ┌─────────────▼─────────────┐
                    │      adapter layer        │
                    └──┬────┬────┬────┬────┬────┘
                       │    │    │    │    │
             SyberRuntime  Barn Bough OSAHR Relay
              (import)  (mounted (import)(import)(node 24
                          ASGI)                   sidecar)
```

---

## Run it

```bash
python run.py --check     # verify prerequisites
python run.py             # start the sidecar and the backend
```

Then open **http://127.0.0.1:8765/**.

Barn's own API stays reachable, unmodified, at
**http://127.0.0.1:8765/systems/barn/docs**.

### First-time setup

```bash
# 1. source systems
mkdir -p systems && cd systems
git clone https://github.com/sykosyber/bough-and-barn.git bough_and_barn
git clone https://github.com/SyberLabs/relay.git relay
git clone https://github.com/SyberLabs/OSAHR_Cell.git osahr
git -c core.autocrlf=false clone https://github.com/sykosyber/syber_runtime.git syber_runtime
cd ..

# 2. python environment
python -m venv .venv
.venv/Scripts/python -m pip install -e ./systems/osahr
.venv/Scripts/python -m pip install --no-deps -e ./systems/bough_and_barn/bough
.venv/Scripts/python -m pip install --no-deps -e ./systems/syber_runtime
.venv/Scripts/python -m pip install -e "./systems/bough_and_barn/barn[dev]"

# 3. Node 24 for Relay (TypeScript, native type stripping)
#    Put a Node >= 24 on PATH, or unpack one under .tooling/
```

`syber_runtime` **must** be cloned with `core.autocrlf=false`. Git's CRLF
conversion rewrites `docs/rq0_rq6_preregistration.md`, changing its sha256 and
breaking an evidence binding the acceptance gate checks.

`--no-deps` on Bough is deliberate: it pins
`osahr @ git+...@59cbe0c`, and the `systems/osahr` checkout is already at
exactly that commit, so one editable install serves both with no version skew.

Optional: set `GOOGLE_API_KEY` to enable the single live model call in Relay's
handoff. Everything else works without it.

---

## Start here: guided scenarios

Each instrument carries a **Guided** strip. One click runs a scripted sequence
against the real systems and narrates it as it happens — so the revealing path
is not something you have to guess at.

A scenario is **input configuration, not playback**. Every step calls the same
adapter method the instrument's own controls call; the system decides the
outcome. Each step also declares what it *expects* — usually success, sometimes
a specific refusal code — and the runner reports what actually happened. If a
step that should be refused is allowed, the scenario says
**"Not what the scenario predicted"** and keeps going rather than presenting the
wrong outcome as the intended one.

Every step is explained twice, side by side:

- **In plain terms** — what just happened, for someone who does not know the
  system.
- **What actually ran** — which function was called, what it checked, and why
  the outcome follows.

Neither is a summary of the other. A **Pace** control (Slow, Normal, Fast) sets
how long each step is held before its call runs; the delay scales with how much
there is to read. Slow is the default, because the point is to be followed, not
to finish. The pauses sit ahead of execution, so what appears on screen is still
the moment it happened.

| Scenario | System | Steps | What it shows |
| --- | --- | --: | --- |
| Accrue, then refuse | SyberRuntime | 8 | Debt opens an obligation; stabilization is refused; a *failing* check discharges nothing; a passing one unblocks it |
| Independence is enforced | Barn | 11 | `artifact_required`, then `independent_verifier_required`, then `passing_verification_required` — then resolve, audit by replay, and ask why the agent exists |
| Exact, or refuse | Bough | 5 | 33 states coalesce to 16 and reach is exact; the cyclic fragment is **refused** instead of approximated |
| Two ways to the same number | OSAHR | 3 | The typed hypergraph and its rewrite rules, then exact 2/3 against three kernel schedulers |
| The handoff is the object | Relay | 5 | Identity mismatch refused, bounded packet, over-claiming draft caught by the claim gate, stale version refused |
| A draft becomes an obligation | seam | 5 | Relay marks a draft `reviewRequired`; SyberRuntime refuses to stabilize it, for its own reasons |

The controls stay live throughout. When a scenario finishes, **Show me the
resulting state** returns you to the instrument with that state in place.

## What each instrument shows

| Instrument | Primitive | The thing worth seeing |
| --- | --- | --- |
| **SyberRuntime** | Operation | Record a Feature, then try to stabilize it. The kernel refuses, names the open floor obligation, and points at the line that refused. Verify, and the same action succeeds. |
| **Barn** | BarnEvent | Resolve work with no artifact → `artifact_required`. Verify an artifact with the agent that produced it → `independent_verifier_required`. Then audit: materialized state hash vs state replayed from the event log. |
| **Bough** | Jump chain | Compile the bits family: 33 uncoalesced states collapse to 16, `reach(all-on) = 1.0` over 24 paths. Compile the ontology fragment and ask the same question — it is cyclic, and Bough refuses rather than approximating. |
| **OSAHR Cell** | Typed hypergraph | A live **6G RAN/MEC digital twin** from the repository's own experiment: watch tasks arrive, bind into 4-ary `Transit` hyperedges, route under a chosen policy, and survive a mid-run edge outage. Plus Bough's exact 2/3 checked against three kernel schedulers. |
| **Relay** | Explicit handoff | The bounded packet that leaves, the external assistant, the identity/version re-validation on the way back, and the claim gate that flags sentences the cited facts do not support. |

### The event stream

Events are grouped by the action that caused them, using an `operationId` the
backend attributes at the edge — one HTTP request, or one scenario step. During
a scenario the stream shows two levels (scenario → step → events), so "what just
happened?" is answerable without reading 30 flat rows. Click any event for its
payload and the source file and line that produced it.

Three seams are also wired, and only ones the source systems already define:

- **Bough → OSAHR** — upstream code (`bough/compare.py`), invoked, not rebuilt.
- **Barn → Bough** — the advisor the source repo specifies in
  `docs/INTEGRATION_PLAN.md` §7: a suggestion, never an authorization. Barn's
  committed decision is always shown next to, and distinct from, the advice.
- **Relay → SyberRuntime** — a `relay.draft.v1` marked `reviewRequired` is an
  unverified artifact in SyberRuntime's grammar. Recording it accrues a floor
  obligation; stabilizing before review is refused by the real kernel.

---

## Layout

```text
run.py                    launcher + prerequisite check
platform/
  backend/                orchestration only, no domain logic
    contract.py           SyberEvent, derived provenance, causal context
    scenarios.py          guided scenarios: steps + expectations, no playback
    main.py               routes, SSE streams, mounted Barn app, source server
    adapters/
      syber_runtime_adapter.py
      barn_adapter.py
      bough_adapter.py
      relay_adapter.py
      osahr_6g_adapter.py       the committed 6G twin, stepped live
      bridge_barn_bough.py
  relay-sidecar/          Node 24 process importing Relay's real lib/*.ts
  frontend/               the instrument panel
    scenario.js           the guided-scenario runner
    osahr6g.js            the 6G network visualization
systems/                  the source repositories, unmodified
docs/
  INTEGRATION_MAP.md      Phase 1 archaeology: what each system actually is
  ARCHITECTURE.md         how the layers fit and why
  ADAPTERS.md             per-system adapter contract
  FIDELITY.md             the fidelity matrix and the stated limits
```

Dependency direction is one way: **platform → adapters → systems**. No source
repository depends on anything here, and each stays independently runnable.

---

## Honest limits

These are stated here rather than discovered later:

- SyberRuntime's acceptance gate reports **fail** on a fresh clone. The evidence
  corpus those criteria audit lives in gitignored run directories. That is the
  fail-closed gate working, and the UI shows the real criterion list.
- Two of Barn's benchmark tests fail upstream; its README already documents that
  comparison as intentionally negative for Barn. The platform does not use the
  benchmark harness.
- No Neo4j credentials exist here, so Bough's Cypher is generated and displayed
  but never pushed.
- The Barn→Bough twin is calibrated from a single short run with Laplace
  smoothing. It is a shape, not a fitted model, and its calibration basis is
  displayed with every number it produces.
- Relay's Obsidian, database and Cloudflare paths are not exercised — only its
  pure domain modules, which need no credentials and no npm install.
- Live inference is off by default, is a single explicit call, and never polls.

See [docs/FIDELITY.md](docs/FIDELITY.md) for the capability-by-capability matrix.
