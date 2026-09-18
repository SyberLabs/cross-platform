"""Adapter: Bough (and OSAHR, through Bough's own comparison module).

Invocation: direct in-process import of `bough`. The compiler is pure Python
over `osahr`, so the real `expand` / `reach` / `optimal_policy` run inside the
platform process and the resulting `MarkovAutomaton` object is serialized for
the graph inspector. No probability is computed here — `_automaton_view` only
reads `edge.probability` and `Situation.kind` off the compiled object.

The OSAHR cross-check is `bough.compare.agree_first_passage`, which is upstream
code: it drives OSAHR's `direct_ssa`, `next_reaction` and `thinning` schedulers
for real replicates and compares their empirical first-passage frequency to
Bough's exact answer. The platform invokes it; it does not reimplement it.
"""

from __future__ import annotations

from typing import Any

from bough.compare import KERNEL_SCHEDULERS, agree_first_passage, bits_all_on, race_winner_a
from bough.cypher import automaton_to_cypher
from bough.errors import BoughRefusal
from bough.expand import expand
from bough.families import (
    bits_all_on_label,
    bits_model,
    machine_model,
    ontology_model,
    preempt_model,
    race_model,
    race_terminal_label,
    token_attach_model,
)
from bough.incrementality import refresh_probabilities
from bough.infer import path_probability, reach
from bough.ir import Horizon, MarkovAutomaton
from bough.policy import machine_terminal_value, optimal_policy
from bough.report import report
from bough.staging import stage

from osahr.analysis import run_ensemble

from contract import EventSink, Provenance, Recorder, SyberEvent

SYSTEM = "bough"

# Families exactly as the repository defines them. `label` is the terminal
# labeller the family ships with, or None when the family has no labelled goal.
FAMILIES: dict[str, dict[str, Any]] = {
    "bits": {
        "title": "Irreversible bits",
        "description": "n independent bits, each flippable once. Coalescing collapses order.",
        "params": {"n": {"type": "int", "default": 4, "min": 1, "max": 7}},
        "goal": "all-on",
        "cyclic": False,
    },
    "ontology": {
        "title": "Ontology fragment",
        "description": "Cyclic fail/repair routes. Exact reach refuses on a cyclic automaton.",
        "params": {"copies": {"type": "int", "default": 1, "min": 1, "max": 3}},
        "goal": None,
        "cyclic": True,
    },
    "machine": {
        "title": "Protect / ignore MDP",
        "description": "Hand-solvable decision problem; backward induction picks the action.",
        "params": {},
        "goal": None,
        "cyclic": False,
    },
    "race": {
        "title": "C2 race",
        "description": "Two competing rules. Exact reach(a) is checkable against OSAHR.",
        "params": {
            "rate_a": {"type": "float", "default": 2.0, "min": 0.1, "max": 10.0},
            "rate_b": {"type": "float", "default": 1.0, "min": 0.1, "max": 10.0},
        },
        "goal": "a",
        "cyclic": False,
    },
    "token_attach": {
        "title": "Token attach",
        "description": "Attachment rewrites over a typed hypergraph.",
        "params": {},
        "goal": None,
        "cyclic": False,
    },
    "preempt": {
        "title": "Preemption",
        "description": "Decision layer with a preemption rule.",
        "params": {},
        "goal": None,
        "cyclic": False,
    },
}


def _build(family: str, params: dict[str, Any]):
    """Return (bough_model, terminal_labeller) from the real family constructors."""
    if family == "bits":
        n = int(params.get("n", 4))
        return bits_model(n), bits_all_on_label(n)
    if family == "ontology":
        return ontology_model(int(params.get("copies", 1))), None
    if family == "machine":
        return machine_model(), None
    if family == "race":
        return race_model(float(params.get("rate_a", 2.0)), float(params.get("rate_b", 1.0))), race_terminal_label
    if family == "token_attach":
        return token_attach_model(), None
    if family == "preempt":
        return preempt_model(), None
    raise KeyError(f"Unknown family: {family}")


class BoughAdapter:
    def __init__(self, sink: EventSink, session_id: str) -> None:
        self.rec = Recorder(sink, SYSTEM, session_id)
        self.osahr_rec = Recorder(sink, "osahr", session_id)
        self._last: MarkovAutomaton | None = None
        self._last_key: str | None = None

    # -- compile -----------------------------------------------------------

    def compile(
        self,
        family: str,
        params: dict[str, Any] | None = None,
        *,
        max_depth: int | None = None,
        max_situations: int = 5000,
    ) -> dict[str, Any]:
        params = params or {}
        model, label = _build(family, params)
        horizon = Horizon(max_depth=max_depth, max_situations=max_situations)

        automaton, event = self.rec.run(
            expand,
            model,
            event_type="bough.expand",
            event_label=f"expand({family})",
            input_payload={"family": family, "params": params,
                           "horizon": {"maxDepth": max_depth, "maxSituations": max_situations}},
            horizon=horizon,
            label=label,
            transform=lambda a: report(a).to_dict(),
        )
        self._last = automaton
        self._last_key = f"{family}:{sorted(params.items())}"

        # `refresh_probabilities` is the incremental re-rate pass; it is the
        # step that populates edge probabilities after a structural expand.
        self.rec.run(
            refresh_probabilities,
            automaton,
            model,
            event_type="bough.refresh_probabilities",
            event_label="refresh probabilities",
            transform=lambda _: {"refreshSeconds": automaton.refresh_seconds},
        )

        rpt = report(automaton).to_dict()
        try:
            derived = stage(automaton, "derived")
            rpt["stage_count"] = derived.stage_count
            rpt["staging_mode"] = "derived"
        except Exception as exc:  # staging is not defined for every family
            rpt["staging_error"] = f"{type(exc).__name__}: {exc}"

        return {
            "family": family,
            "params": params,
            "report": rpt,
            "automaton": _automaton_view(automaton),
            "goal": FAMILIES.get(family, {}).get("goal"),
            "eventSeq": event.seq,
        }

    # -- exact queries -----------------------------------------------------

    def reach(self, label: str) -> dict[str, Any]:
        """Exact probability mass and distinct path count to labelled terminals."""
        automaton = self._require()
        (mass, paths), event = self.rec.run(
            reach,
            automaton,
            label,
            event_type="bough.reach",
            event_label=f"reach({label})",
            refusals=(BoughRefusal,),
            input_payload={"label": label},
            transform=lambda r: {"mass": r[0], "paths": r[1]},
        )
        return {"label": label, "mass": mass, "paths": paths, "eventSeq": event.seq}

    def path_probability(self, trace: list[list[str]]) -> dict[str, Any]:
        automaton = self._require()
        steps = [(str(a), str(b)) for a, b in trace]
        prob, event = self.rec.run(
            path_probability,
            automaton,
            steps,
            event_type="bough.path_probability",
            event_label="path probability",
            refusals=(BoughRefusal,),
            input_payload={"trace": steps},
        )
        return {"probability": prob, "trace": steps, "eventSeq": event.seq}

    def optimal_policy(self) -> dict[str, Any]:
        """Backward induction over the compiled automaton."""
        automaton = self._require()
        policy, event = self.rec.run(
            optimal_policy,
            automaton,
            machine_terminal_value,
            event_type="bough.optimal_policy",
            event_label="optimal policy",
            refusals=(BoughRefusal,),
            transform=lambda p: {
                "rootValue": p.value.get(automaton.root),
                "rootAction": list(p.action.get(automaton.root) or ()),
            },
        )
        return {
            "rootValue": policy.value.get(automaton.root),
            "rootAction": list(policy.action.get(automaton.root) or ()),
            "value": {k: v for k, v in policy.value.items()},
            "action": {k: list(v or ()) for k, v in policy.action.items()},
            "eventSeq": event.seq,
        }

    def cypher(self) -> dict[str, Any]:
        automaton = self._require()
        text, event = self.rec.run(
            automaton_to_cypher,
            automaton,
            event_type="bough.cypher",
            event_label="Neo4j Cypher export",
            transform=lambda t: {"lines": t.count("\n"), "bytes": len(t)},
        )
        return {"cypher": text, "eventSeq": event.seq}

    # -- OSAHR cross-check -------------------------------------------------

    def osahr_agreement(
        self, family: str, params: dict[str, Any] | None = None, *, replicates: int = 48, root_seed: int = 23
    ) -> dict[str, Any]:
        """Drive the real OSAHR schedulers and compare to Bough's exact answer.

        Only families with a first-passage predicate defined upstream are
        supported: `race` (race_winner_a) and `bits` (bits_all_on).
        """
        params = params or {}
        if family == "race":
            model, labeller = _build("race", params)
            predicate, goal, event_count = race_winner_a, "a", 1
        elif family == "bits":
            n = int(params.get("n", 2))
            model, labeller = _build("bits", {"n": n})
            predicate, goal, event_count = bits_all_on, "all-on", n
        else:
            raise KeyError(f"No upstream first-passage predicate for family: {family}")

        automaton = expand(model, label=labeller)
        mass, paths = reach(automaton, goal)

        # Attribute both halves honestly. The comparison harness is Bough's
        # code; the schedulers it drives are OSAHR's. Recording the harness
        # under "osahr" would make Provenance.of fall back to an absolute path,
        # because compare.py does not live in the OSAHR checkout.
        rows, event = self.rec.run(
            agree_first_passage,
            model.model,
            predicate,
            mass,
            event_type="bough.scheduler_agreement",
            event_label=f"compare exact vs kernel x{replicates}",
            input_payload={
                "family": family,
                "params": params,
                "replicates": replicates,
                "rootSeed": root_seed,
                "exact": mass,
                "schedulers": [k.value for k in KERNEL_SCHEDULERS],
            },
            event_count=event_count,
            replicates=replicates,
            root_seed=root_seed,
            transform=lambda rs: [r.to_dict() for r in rs],
        )

        # The kernel work itself: one event per scheduler, with provenance
        # derived from OSAHR's own `run_ensemble`, which is what actually ran.
        osahr_prov = Provenance.of("osahr", run_ensemble).to_dict()
        for row in rows:
            self.osahr_rec.sink.emit(
                SyberEvent(
                    system="osahr",
                    sessionId=self.osahr_rec.session_id,
                    eventType="osahr.first_passage",
                    label=f"{row.scheduler} x{replicates}",
                    status="ok" if row.within_radius else "error",
                    input={"scheduler": row.scheduler, "replicates": replicates,
                           "rootSeed": root_seed, "eventCount": event_count},
                    output=row.to_dict(),
                    evidence={"exact": row.exact, "empirical": row.empirical,
                              "radius": row.radius, "withinRadius": row.within_radius},
                    provenance=osahr_prov,
                    metadata={"drivenBy": "bough.compare.agree_first_passage"},
                )
            )

        return {
            "family": family,
            "goal": goal,
            "exact": mass,
            "paths": paths,
            "replicates": replicates,
            "schedulers": [r.to_dict() for r in rows],
            "eventSeq": event.seq,
        }


    def osahr_model(self, family: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """The typed directed hypergraph and rewrite rules the kernel runs over.

        This is OSAHR's core primitive. Everything below is read off the real
        `osahr.Model`: vertices with their declared types and attributes,
        hyperedges with their tail/head incidences and roles, and each rule's
        pattern, template and hazard expression exactly as the family declared
        them. Nothing is summarized into a different shape.
        """
        model, _ = _build(family, params or {})
        kernel = model.model
        graph = kernel.graph

        vertices = [
            {
                "id": str(vid),
                "type": v.type_id,
                "attributes": {str(k): _plain(x) for k, x in (v.attributes or {}).items()},
            }
            for vid, v in graph.vertices.items()
        ]
        edges = [
            {
                "id": str(eid),
                "type": e.type_id,
                "tail": [{"role": i.role, "ordinal": i.ordinal, "vertex": str(i.vertex_id)} for i in e.tail],
                "head": [{"role": i.role, "ordinal": i.ordinal, "vertex": str(i.vertex_id)} for i in e.head],
                "attributes": {str(k): _plain(x) for k, x in (e.attributes or {}).items()},
            }
            for eid, e in graph.edges.items()
        ]

        rules = []
        for spec in model.events:
            rule = spec.rule
            rules.append(
                {
                    "eventId": spec.event_id,
                    "kind": spec.kind.value,
                    "ruleId": rule.rule_id,
                    "hazard": rule.hazard.source,
                    "guard": rule.guard.source if rule.guard is not None else None,
                    "hash": rule.hash,
                    "left": _pattern_view(rule.left),
                    "right": _pattern_view(rule.right),
                    "adaptation": len(rule.adaptation),
                    "conditions": len(rule.conditions),
                }
            )

        return {
            "family": family,
            "params": params or {},
            "schemaId": getattr(graph.schema, "schema_id", None),
            "vertexTypes": sorted(graph.vertices_by_type),
            "edgeTypes": sorted(graph.edges_by_type),
            "vertices": vertices,
            "edges": edges,
            "rules": rules,
            "repertoireHash": model.repertoire_hash,
            "provenance": Provenance.of("osahr", type(graph)).to_dict(),
        }

    # -- internals ---------------------------------------------------------

    def _require(self) -> MarkovAutomaton:
        if self._last is None:
            raise ValueError("No automaton compiled yet. Run a compile first.")
        return self._last

    def last_automaton(self) -> MarkovAutomaton | None:
        return self._last


def _plain(value: Any) -> Any:
    """Render an attribute term.

    Concrete values pass through. A pattern variable is rendered `?name`, the
    conventional notation for one — the binding is unchanged, only its
    repr is made readable instead of showing `Var(name='src')`.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    name = getattr(value, "name", None)
    if name is not None and type(value).__name__ == "Var":
        return f"?{name}"
    return str(value)


def _pattern_view(side: Any) -> dict[str, Any]:
    """Vertices and edges of a rule's pattern or template graph, as declared."""
    out: dict[str, Any] = {"vertices": [], "edges": []}
    for v in getattr(side, "vertices", ()) or ():
        out["vertices"].append(
            {
                "key": getattr(v, "key", None),
                "type": getattr(v, "type_id", None),
                "attributes": {str(k): _plain(x) for k, x in (getattr(v, "attributes", None) or {}).items()},
            }
        )
    for e in getattr(side, "edges", ()) or ():
        out["edges"].append(
            {
                "key": getattr(e, "key", None),
                "type": getattr(e, "type_id", None),
                "tail": [str(t) for t in (getattr(e, "tail", ()) or ())],
                "head": [str(h) for h in (getattr(e, "head", ()) or ())],
            }
        )
    return out


def _automaton_view(automaton: MarkovAutomaton) -> dict[str, Any]:
    """Serialize the compiled object. Reads only; computes nothing."""
    situations = []
    edges = []
    for sig, situation in automaton.situations.items():
        situations.append(
            {
                "signature": sig,
                "short": sig[:10],
                "kind": situation.kind.value,
                "depth": situation.depth,
                "label": situation.label,
                "isRoot": sig == automaton.root,
                "outDegree": len(situation.outgoing),
                "graph": _graph_view(situation.graph),
            }
        )
        for edge in situation.outgoing:
            edges.append(
                {
                    "source": edge.source,
                    "target": edge.target,
                    "ruleId": edge.rule_id,
                    "matchId": edge.match_id,
                    "kind": edge.kind.value,
                    "probability": edge.probability,
                    "bindings": {str(k): str(v) for k, v in (edge.bindings or {}).items()},
                }
            )
    situations.sort(key=lambda s: (s["depth"], s["signature"]))
    return {
        "root": automaton.root,
        "situations": situations,
        "edges": edges,
        "truncated": automaton.truncated,
        "maxDepth": max((s["depth"] for s in situations), default=0),
    }


def _graph_view(graph: Any) -> dict[str, Any]:
    """A small structural summary of the underlying OSAHR hypergraph."""
    try:
        nodes = list(getattr(graph, "nodes", ()) or ())
        edges = list(getattr(graph, "edges", ()) or ())
        return {"nodeCount": len(nodes), "edgeCount": len(edges)}
    except Exception:
        return {}
