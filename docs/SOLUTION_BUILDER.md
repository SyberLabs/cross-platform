# Solution Builder v0 — Cross-platform becomes a compositional environment

## Product shift

Cross-platform is no longer only an instrument panel over SyberLabs systems.

It becomes a **solution-building environment** in which a user starts from an
outcome, composes typed capabilities, runs the real underlying systems, and can
inspect exactly why every transition was accepted, refused, or stabilized.

The source systems remain independent. The builder owns composition,
instrumentation, typed handoff metadata, and interface state — never duplicated
domain logic.

```text
user intent
    ↓
solution graph
    ↓
typed capabilities + explicit seams
    ↓
Relay / Barn / Bough / OSAHR / SyberRuntime
    ↓
events + refusals + evidence + provenance
    ↓
inspectable result
```

## The user-facing abstraction

The primary navigation should progressively move away from repository names.

A solution author should think in verbs:

- **Generate / hand off** — let an external model propose something.
- **Bound** — constrain what context or capabilities may cross a boundary.
- **Model** — represent the relevant state and relationships.
- **Evaluate** — compute reach, policy, risk, or expected consequence.
- **Authorize** — decide whether an actor/action is licensed.
- **Verify** — collect evidence against explicit checks.
- **Commit / stabilize** — move an object into authoritative state.
- **Inspect** — trace the result back through events, evidence and source.

The underlying system name remains visible as provenance, not as the mental model
the user must learn before building anything.

## Non-negotiable rule: no fake composition

The builder must not offer arbitrary wires.

A connection exists only when:

1. an output port has a declared type;
2. an input port accepts that type directly, or a named seam converts it;
3. the seam is implemented by real executable code;
4. the resulting events retain provenance to the source systems that ran.

If two systems do not actually compose, the UI says so.

This preserves the fidelity discipline of the current platform.

## Core data model

### Capability

A capability is a callable operation surfaced by a source system.

```json
{
  "id": "runtime.stabilize",
  "verb": "Commit",
  "system": "syber_runtime",
  "inputs": [{"name": "artifact", "type": "runtime.artifact.v1"}],
  "outputs": [{"name": "result", "type": "runtime.stabilization.v1"}],
  "mayRefuse": true
}
```

A capability does not re-describe or reimplement source behavior.

### Seam

A seam is an explicit composition rule between types owned by different
capabilities or systems.

Example:

```text
relay.draft.v1
    ↓ relay_to_runtime
artifact.text.v1
    ↓ runtime.record_feature
runtime.artifact.v1 + runtime.obligation.v1
```

### Solution

A solution is a graph of capability nodes plus typed edges.

V0 deliberately supports a DAG. Cycles/feedback should be introduced only when
the execution semantics are explicit.

```json
{
  "id": "reviewed-ai-artifact",
  "goal": "Generate an artifact but prevent it becoming authoritative before review",
  "nodes": [
    {"id": "draft", "capability": "relay.handoff"},
    {"id": "record", "capability": "runtime.record_feature"},
    {"id": "verify", "capability": "runtime.verify"},
    {"id": "commit", "capability": "runtime.stabilize"}
  ]
}
```

## V0 capability vocabulary

The initial builder should expose only capabilities already demonstrated by the
instrument panel.

| Verb | Capability | Source |
| --- | --- | --- |
| Bound / Generate | bounded assistant handoff | Relay |
| Ground | unsupported-claim gate | Relay |
| Model | typed hypergraph model | OSAHR |
| Simulate | stochastic kernel step/run | OSAHR |
| Evaluate | exact reach | Bough |
| Decide | backward-induction policy | Bough |
| Authorize | specialist spawn/reuse/reject | Barn |
| Verify | independent artifact verification | Barn |
| Record | evidence-bearing feature operation | SyberRuntime |
| Verify | deterministic artifact check | SyberRuntime |
| Commit | stabilization gate | SyberRuntime |
| Inspect | event/provenance/source chain | cross-platform |

## First three solution templates

### 1. Reviewed AI artifact

**User intent:** "Let AI draft something, but do not let it become settled state
until it passes review."

```text
bounded handoff
    ↓
returned draft
    ↓
Relay identity/version/claim validation
    ↓
Relay→Runtime seam
    ↓
verification obligation
    ↓
deterministic or human-derived check
    ↓
stabilization
```

This is the first executable builder template because the seam already exists.

### 2. Governed delegation

**User intent:** "Let an organization add capability when needed, but keep the
decision licensed and inspectable."

```text
goal/work
    ↓
Barn capability gap
    ↓
Barn decision
      ↘
       Bough advice (suggestion only)
    ↓
artifact
    ↓
independent verification
    ↓
resolve
```

Bough may advise. Barn remains authoritative.

### 3. Exact-versus-stochastic model check

**User intent:** "Show that a stochastic implementation agrees with an exact
model where an exact answer is available."

```text
typed rewrite model
    ├── Bough exact compilation/reach
    └── OSAHR schedulers
            ↓
        agreement check
```

The upstream seam already exists.

## Interface

The first builder UI should have four zones.

### 1. Goal

A plain-language sentence:

> What are you trying to make safe, decidable, verifiable, or controllable?

Do not begin with "Choose a SyberLabs system."

### 2. Recipe / canvas

Show a small set of proven templates and then their node graph.

V0 can use a linear/branching card graph. Do not spend time on a freeform canvas
before the type system and execution semantics are mature.

Each node displays:

- user-facing verb;
- capability name;
- source system as a smaller provenance label;
- typed input/output ports;
- whether it may refuse;
- current run state.

### 3. Run

Running a solution executes the same adapters that the existing instrument
controls call.

Refusal is a normal visible state, not a failed demo.

### 4. Explain

Selecting any node/result shows:

```text
plain-language meaning
→ capability
→ input/output
→ event(s)
→ evidence
→ source file and line
```

The existing event stream and source viewer become the explanation substrate for
the builder.

## Architecture

```text
platform/frontend/builder.js
        ↓
/api/solutions/*
        ↓
platform/backend/solution_builder.py
        ↓
typed capability registry + solution validation
        ↓
existing adapters / explicit seam helpers
        ↓
source repositories
```

`solution_builder.py` may know:

- capability metadata;
- port types;
- legal connections;
- template topology;
- execution ordering.

It may **not** know:

- how Bough computes probability;
- how Barn licenses a transition;
- how Relay decides a claim is supported;
- how SyberRuntime discharges debt;
- how OSAHR schedules an event.

Those remain source-system behavior.

## V0 implementation slice

1. Add a typed capability registry.
2. Add a solution-template registry.
3. Add validation for node ids, capability ids, edges and port-type compatibility.
4. Add APIs:
   - `GET /api/solutions/capabilities`
   - `GET /api/solutions/templates`
   - `POST /api/solutions/validate`
5. Add **Builder** as the first item in the left rail.
6. Render templates as solution graphs with source-system provenance visible.
7. Make the Reviewed AI Artifact template executable through the already-real
   Relay→SyberRuntime seam.
8. Preserve the existing per-system instruments as **Inspect / Advanced** views.

## Next integration work

After V0, add a runtime execution plan with explicit value bindings:

```text
node.output.port → seam → node.input.port
```

Every run should emit a top-level solution-run id so the event stream groups:

```text
solution run
  → node
    → source-system events
```

Then add:

- saved solution manifests;
- user-defined graphs using only legal typed edges;
- schema-derived forms for node inputs;
- branch conditions over structured outcomes/refusals;
- reusable subgraphs;
- import/export of solution manifests;
- environment-specific capability policies;
- human approval nodes;
- model-provider nodes as external/untrusted actors;
- replay of a solution from recorded inputs while recomputing real outputs.

## Product criterion

Cross-platform succeeds as a solution builder when a technically capable user can
open it, describe an outcome, assemble a workflow without knowing the SyberLabs
repo taxonomy, run it, and answer:

1. What happened?
2. Why was this action allowed or refused?
3. Which system made that decision?
4. What evidence licensed the final state?
5. Which exact source produced the behavior?

That is the product: **an environment for building consequential AI workflows
whose state transitions remain inspectable, typed, and licensed.**
