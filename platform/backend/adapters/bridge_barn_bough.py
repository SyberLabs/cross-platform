"""Bridge: Barn -> Bough (the advisor seam).

This is the `barn_bough/` bridge that `bough_and_barn/docs/INTEGRATION_PLAN.md`
sections 5, 7 and 8 specify but deliberately leave unbuilt in that snapshot. It
lives here, in the platform's adapter layer, so neither repository changes and
both remain independently installable.

What it does, per section 7:

  1. Project the current Barn `RunState` into a Bough twin (section 6.1: ids and
     counters are abstracted away, or nothing coalesces).
  2. `expand` the twin, then `optimal_policy` for the root action and value and
     `reach` for the success probability of each branch.
  3. Emit `SpawnAdvice {action, value, reach_probability, truncated,
     repertoire_hash}`.

What it explicitly does NOT do, per the same section: authorize anything. Barn's
engine still makes and enforces the decision. The advice is computed *beside*
the committed decision and the UI shows both. If the two disagree, that
disagreement is displayed rather than resolved — Barn's heuristic remains the
baseline until a matched-budget experiment says otherwise.

Everything probabilistic here is computed by Bough. This module builds the
twin's graph and rules and supplies a terminal value function; it does not
compute a single probability itself.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from typing import Any

from osahr import (
    AttributeSpec,
    BoundaryState,
    Expr,
    Hypergraph,
    Model,
    PatternGraph,
    PatternVertex,
    Rule,
    Schema,
    TemplateGraph,
    TemplateVertex,
    ValueKind,
    VertexType,
)

from bough.errors import BoughRefusal
from bough.expand import expand
from bough.infer import reach
from bough.ir import Horizon, Situation
from bough.kinds import EventKind, EventSpec
from bough.policy import optimal_policy
from bough.spec import compile_model

from contract import EventSink, Recorder

SYSTEM = "bough"


@dataclass(frozen=True)
class SpawnAdvice:
    """Exactly the payload INTEGRATION_PLAN section 7 step 3 names."""

    action: str | None
    value: float | None
    reach_probability: float | None
    truncated: bool
    repertoire_hash: str
    authoritative: bool = False  # never true: advice is not authorization

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _twin(*, spawn_rate: float, reuse_rate: float, exhaust_rate: float):
    """Project an organizational shape into a Bough model.

    Per section 6.1 the twin carries no agent ids and no counters: a capability
    gap is one `Org` vertex in phase `decide`. Two decision rules (spawn, reuse)
    lead to two chance sub-problems whose hazards are calibrated from the real
    run. This is the *shape* of the decision, not a replay of the run.
    """
    schema = Schema(
        [
            VertexType(
                "Org",
                {
                    "phase": AttributeSpec(ValueKind.STRING, required=True),
                    "outcome": AttributeSpec(ValueKind.STRING, required=True),
                },
            )
        ],
        [],
        schema_id="barn-twin",
    )
    graph = Hypergraph(schema, namespace=0xBA57)
    graph.add_vertex("Org", {"phase": "decide", "outcome": "pending"})

    def decision(rule_id: str, to_phase: str) -> Rule:
        return Rule(
            rule_id,
            PatternGraph((PatternVertex("o", "Org", {"phase": "decide"}),)),
            TemplateGraph((TemplateVertex("o", "Org", {"phase": to_phase, "outcome": "pending"}),)),
            Expr("0"),  # decisions must carry no hazard (bough.kinds.validate_event)
        )

    def chance(rule_id: str, from_phase: str, outcome: str, rate: float) -> Rule:
        return Rule(
            rule_id,
            PatternGraph((PatternVertex("o", "Org", {"phase": from_phase}),)),
            TemplateGraph((TemplateVertex("o", "Org", {"phase": "done", "outcome": outcome}),)),
            Expr(repr(float(rate))),
        )

    spawn = decision("spawn", "spawned")
    reuse = decision("reuse", "reused")
    spawn_ok = chance("spawn_resolved", "spawned", "resolved", spawn_rate)
    spawn_no = chance("spawn_exhausted", "spawned", "exhausted", exhaust_rate)
    reuse_ok = chance("reuse_resolved", "reused", "resolved", reuse_rate)
    reuse_no = chance("reuse_exhausted", "reused", "exhausted", exhaust_rate)

    model = Model(
        graph,
        BoundaryState({}),
        (spawn, reuse, spawn_ok, spawn_no, reuse_ok, reuse_no),
        {},
        {},
        model_id="barn-org-twin",
    )
    return compile_model(
        model,
        (
            EventSpec("spawn", EventKind.DECISION, spawn),
            EventSpec("reuse", EventKind.DECISION, reuse),
            EventSpec("spawn_resolved", EventKind.CHANCE, spawn_ok),
            EventSpec("spawn_exhausted", EventKind.CHANCE, spawn_no),
            EventSpec("reuse_resolved", EventKind.CHANCE, reuse_ok),
            EventSpec("reuse_exhausted", EventKind.CHANCE, reuse_no),
        ),
    )


def _label(situation: Situation) -> str | None:
    for vertex in situation.graph.vertices.values():
        if vertex.type_id == "Org" and vertex.attributes.get("phase") == "done":
            return str(vertex.attributes.get("outcome"))
    return None


def _terminal_value(situation: Situation) -> float:
    """Resolving within budget is worth 1; exhausting the budget is worth 0.

    Section 5 maps Barn's budget/credits onto "the horizon and the failure
    label", and terminal cost weights onto execution records. This is the
    bridge's value function, supplied to Bough's `optimal_policy`; the backward
    induction itself is entirely `bough/policy.py`.
    """
    for vertex in situation.graph.vertices.values():
        if vertex.type_id != "Org":
            continue
        return 1.0 if vertex.attributes.get("outcome") == "resolved" else 0.0
    return 0.0


def calibrate(metrics: dict[str, Any], state: dict[str, Any]) -> dict[str, float]:
    """Derive twin hazards from the run's own observed record.

    Section 6.4 calls for hazards calibrated from `RunMetrics` and
    `ExecutionRecord`. With a short run there is very little to calibrate from,
    so the rates below are explicit and the `basis` field says exactly what they
    were computed from. A caller can show that basis rather than implying more
    evidence than exists.
    """
    verifications = int(metrics.get("verification_count", 0) or 0)
    artifacts = int(metrics.get("artifact_count", 0) or 0)
    spawned = int(metrics.get("specialist_spawned", 0) or 0)
    reused = int(metrics.get("specialist_reused", 0) or 0)
    rejected = int(metrics.get("specialist_rejected", 0) or 0)

    agents = int(metrics.get("agent_total", 0) or 0)
    cap = int(state.get("max_active_agents", 0) or 0)
    retired = int(metrics.get("agent_retired", 0) or 0)
    headroom = max(cap - (agents - retired), 0)

    # A fresh specialist is modelled as more likely to carry its own work to a
    # verified artifact; a reused agent already has other work attached.
    evidence_rate = (verifications + 1) / (artifacts + 2)  # Laplace-smoothed
    spawn_rate = 1.0 + evidence_rate
    reuse_rate = 1.0 + evidence_rate * 0.5
    # Budget pressure is the only thing that makes exhaustion likely.
    exhaust_rate = 2.0 if headroom == 0 else 1.0 / (1 + headroom)

    return {
        "spawn_rate": round(spawn_rate, 6),
        "reuse_rate": round(reuse_rate, 6),
        "exhaust_rate": round(exhaust_rate, 6),
        "basis": {
            "artifacts": artifacts,
            "verifications": verifications,
            "specialistSpawned": spawned,
            "specialistReused": reused,
            "specialistRejected": rejected,
            "agentTotal": agents,
            "agentRetired": retired,
            "maxActiveAgents": cap,
            "budgetHeadroom": headroom,
            "evidenceRate": round(evidence_rate, 6),
            "note": "Laplace-smoothed from this run only; not a fitted model.",
        },
    }


class BarnBoughBridge:
    def __init__(self, sink: EventSink, session_id: str) -> None:
        self.rec = Recorder(sink, SYSTEM, session_id)

    def advise(self, *, metrics: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        rates = calibrate(metrics, state)
        twin = _twin(
            spawn_rate=rates["spawn_rate"],
            reuse_rate=rates["reuse_rate"],
            exhaust_rate=rates["exhaust_rate"],
        )

        automaton, expand_event = self.rec.run(
            expand,
            twin,
            event_type="bridge.twin_expand",
            event_label="compile Barn organization twin",
            refusals=(BoughRefusal,),
            input_payload={"rates": rates},
            horizon=Horizon(max_depth=8, max_situations=512),
            label=_label,
            transform=lambda a: {
                "situations": a.situation_count,
                "edges": a.edge_count,
                "uncoalesced": a.uncoalesced_node_count,
                "truncated": a.truncated,
            },
        )

        policy, policy_event = self.rec.run(
            optimal_policy,
            automaton,
            _terminal_value,
            event_type="bridge.optimal_policy",
            event_label="backward induction over the twin",
            refusals=(BoughRefusal,),
            transform=lambda p: {
                "rootValue": p.value.get(automaton.root),
                "rootAction": list(p.action.get(automaton.root) or ()),
            },
        )

        # `reach` is undefined from a decision root — Bough refuses it with
        # NOT_CHANCE, correctly, because a decision has no probability. Section
        # 7 step 2 asks for the success probability "for that action versus the
        # alternative", i.e. per branch. Each branch target IS a chance node, so
        # the query is re-rooted there. `dataclasses.replace` re-points the root
        # of the same compiled automaton; no structure is rebuilt or recomputed.
        root = automaton.situations[automaton.root]
        branches: dict[str, dict[str, Any]] = {}
        reach_seqs: list[int] = []
        for edge in root.outgoing:
            sub = replace(automaton, root=edge.target)
            (mass, paths), ev = self.rec.run(
                reach,
                sub,
                "resolved",
                event_type="bridge.reach",
                event_label=f"reach(resolved | {edge.rule_id})",
                refusals=(BoughRefusal,),
                input_payload={"branch": edge.rule_id},
                transform=lambda r: {"mass": r[0], "paths": r[1]},
            )
            reach_seqs.append(ev.seq)
            branches[edge.rule_id] = {
                "value": policy.value.get(edge.target),
                "reachProbability": mass,
                "paths": paths,
                "target": edge.target[:12],
            }

        root_action = policy.action.get(automaton.root) or ()
        chosen = root_action[0] if root_action else None
        advice = SpawnAdvice(
            action=chosen,
            value=policy.value.get(automaton.root),
            reach_probability=(branches.get(chosen, {}) or {}).get("reachProbability"),
            truncated=automaton.truncated,
            repertoire_hash=twin.repertoire_hash,
        )

        return {
            "advice": advice.to_dict(),
            "branches": branches,
            "calibration": rates,
            "automaton": {
                "root": automaton.root,
                "situationCount": automaton.situation_count,
                "edgeCount": automaton.edge_count,
                "uncoalescedNodeCount": automaton.uncoalesced_node_count,
                "compressionRatio": automaton.compression_ratio,
                "truncated": automaton.truncated,
            },
            "eventSeqs": [expand_event.seq, policy_event.seq, *reach_seqs],
            "disclaimer": (
                "Advisory only. Barn's engine made and enforced the committed decision; "
                "this value was computed beside it and changed nothing."
            ),
        }
