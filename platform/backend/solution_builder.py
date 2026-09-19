"""Typed composition metadata for the SyberLabs solution builder.

This module describes *how existing capabilities may be composed*. It contains
no source-system domain logic. Execution still goes through the existing
adapters and explicit seam helpers in main.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Port:
    name: str
    type: str
    required: bool = True
    description: str = ""


@dataclass(frozen=True)
class Capability:
    id: str
    label: str
    verb: str
    system: str
    description: str
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Port, ...] = ()
    may_refuse: bool = False
    execution: str = "source-system adapter"
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mayRefuse"] = value.pop("may_refuse")
        return value


@dataclass(frozen=True)
class Edge:
    source: str
    source_port: str
    target: str
    target_port: str
    seam: str | None = None


@dataclass(frozen=True)
class Node:
    id: str
    capability: str
    label: str | None = None


@dataclass(frozen=True)
class SolutionTemplate:
    id: str
    name: str
    goal: str
    description: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    executable: bool = False
    runner: str | None = None
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return value


CAPABILITIES: dict[str, Capability] = {
    "relay.handoff": Capability(
        id="relay.handoff",
        label="Bounded assistant handoff",
        verb="Generate",
        system="relay",
        description=(
            "Send bounded context to an external assistant and re-validate the "
            "returned draft against job identity and version."
        ),
        inputs=(
            Port("packet", "relay.packet.v1"),
            Port("context", "relay.context.v1", required=False),
        ),
        outputs=(Port("draft", "relay.draft.v1"),),
        may_refuse=True,
        tags=("boundary", "generation", "identity"),
    ),
    "relay.claim_gate": Capability(
        id="relay.claim_gate",
        label="Ground returned claims",
        verb="Ground",
        system="relay",
        description="Flag claim sentences unsupported by verified cited facts.",
        inputs=(
            Port("draft", "text.v1"),
            Port("facts", "relay.verified_facts.v1"),
        ),
        outputs=(Port("findings", "relay.claim_findings.v1"),),
        tags=("grounding", "evidence"),
    ),
    "seam.relay_to_runtime": Capability(
        id="seam.relay_to_runtime",
        label="Treat draft as an unverified artifact",
        verb="Bind",
        system="cross",
        description=(
            "Move a Relay draft into SyberRuntime without granting it authority; "
            "recording the draft creates a verification obligation."
        ),
        inputs=(Port("draft", "relay.draft.v1"),),
        outputs=(
            Port("artifact", "runtime.artifact.v1"),
            Port("obligation", "runtime.obligation.v1"),
        ),
        may_refuse=True,
        execution="explicit cross-system seam",
        tags=("seam", "review", "authority"),
    ),
    "runtime.record_feature": Capability(
        id="runtime.record_feature",
        label="Record an evidence-bearing artifact",
        verb="Record",
        system="syber_runtime",
        description="Record a feature/artifact and accrue verification debt.",
        inputs=(Port("artifact", "artifact.text.v1"),),
        outputs=(
            Port("artifact", "runtime.artifact.v1"),
            Port("obligation", "runtime.obligation.v1"),
        ),
        may_refuse=True,
        tags=("evidence", "state"),
    ),
    "runtime.verify": Capability(
        id="runtime.verify",
        label="Verify artifact",
        verb="Verify",
        system="syber_runtime",
        description="Run a deterministic check that may discharge obligations.",
        inputs=(
            Port("artifact", "runtime.artifact.v1"),
            Port("check", "verification.check.v1"),
        ),
        outputs=(Port("verification", "runtime.verification.v1"),),
        may_refuse=True,
        tags=("verification", "evidence"),
    ),
    "runtime.stabilize": Capability(
        id="runtime.stabilize",
        label="Stabilize authoritative state",
        verb="Commit",
        system="syber_runtime",
        description=(
            "Attempt to stabilize an artifact. Open floor obligations cause a "
            "first-class refusal."
        ),
        inputs=(Port("artifact", "runtime.artifact.v1"),),
        outputs=(Port("result", "runtime.stabilization.v1"),),
        may_refuse=True,
        tags=("authority", "commit", "fail-closed"),
    ),
    "barn.specialist_decision": Capability(
        id="barn.specialist_decision",
        label="License specialist allocation",
        verb="Authorize",
        system="barn",
        description="Spawn, reuse, or reject a specialist under Barn invariants.",
        inputs=(Port("work", "barn.work_item.v1"),),
        outputs=(Port("decision", "barn.specialist_decision.v1"),),
        may_refuse=True,
        tags=("authority", "delegation", "capability"),
    ),
    "barn.verify_artifact": Capability(
        id="barn.verify_artifact",
        label="Independently verify artifact",
        verb="Verify",
        system="barn",
        description="Record independent verification before work may resolve.",
        inputs=(
            Port("artifact", "barn.artifact.v1"),
            Port("verifier", "barn.agent.v1"),
        ),
        outputs=(Port("verification", "barn.verification.v1"),),
        may_refuse=True,
        tags=("verification", "independence"),
    ),
    "bough.reach": Capability(
        id="bough.reach",
        label="Compute exact reach",
        verb="Evaluate",
        system="bough",
        description="Compute exact reachability mass when the automaton licenses it.",
        inputs=(Port("automaton", "bough.automaton.v1"),),
        outputs=(Port("reach", "bough.reach.v1"),),
        may_refuse=True,
        tags=("exact", "probability"),
    ),
    "bough.policy": Capability(
        id="bough.policy",
        label="Choose value-optimal policy",
        verb="Decide",
        system="bough",
        description="Run backward induction over a compiled decision model.",
        inputs=(Port("automaton", "bough.automaton.v1"),),
        outputs=(Port("policy", "bough.policy.v1"),),
        may_refuse=True,
        tags=("decision", "exact"),
    ),
    "osahr.model": Capability(
        id="osahr.model",
        label="Represent typed evolving state",
        verb="Model",
        system="osahr",
        description="Build/inspect the typed hypergraph and rewrite repertoire.",
        outputs=(Port("model", "osahr.model.v1"),),
        tags=("state", "semantics", "hypergraph"),
    ),
    "osahr.simulate": Capability(
        id="osahr.simulate",
        label="Run stochastic evolution",
        verb="Simulate",
        system="osahr",
        description="Advance the OSAHR runtime under a selected scheduler/policy.",
        inputs=(Port("model", "osahr.model.v1"),),
        outputs=(Port("trajectory", "osahr.trajectory.v1"),),
        may_refuse=True,
        tags=("simulation", "rewrite"),
    ),
    "cross.explain": Capability(
        id="cross.explain",
        label="Inspect execution and provenance",
        verb="Inspect",
        system="cross",
        description=(
            "Trace solution events through inputs, outputs, evidence, refusals "
            "and the exact source that executed."
        ),
        inputs=(Port("events", "syber.events.v1"),),
        outputs=(Port("explanation", "syber.explanation.v1"),),
        tags=("observability", "provenance"),
    ),
}


TEMPLATES: dict[str, SolutionTemplate] = {
    "reviewed-ai-artifact": SolutionTemplate(
        id="reviewed-ai-artifact",
        name="Reviewed AI artifact",
        goal="Let AI propose an artifact without allowing it to become settled state before review.",
        description=(
            "Relay bounds and re-validates the handoff; the explicit seam turns "
            "the returned draft into an unverified SyberRuntime artifact; a check "
            "must discharge the obligation before stabilization can succeed."
        ),
        nodes=(
            Node("draft", "relay.handoff", "Bounded handoff"),
            Node("bind", "seam.relay_to_runtime", "Create review obligation"),
            Node("verify", "runtime.verify", "Verify"),
            Node("commit", "runtime.stabilize", "Stabilize"),
        ),
        edges=(
            Edge("draft", "draft", "bind", "draft", "relay_to_runtime"),
            Edge("bind", "artifact", "verify", "artifact"),
            Edge("bind", "artifact", "commit", "artifact"),
        ),
        executable=True,
        runner="reviewed-ai-artifact",
        tags=("ai", "review", "authority"),
    ),
    "governed-delegation": SolutionTemplate(
        id="governed-delegation",
        name="Governed delegation",
        goal="Add specialist capability when needed while keeping authorization deterministic and inspectable.",
        description=(
            "Barn remains authoritative over spawn/reuse/reject decisions while "
            "Bough may provide decision-theoretic advice without acquiring commit authority."
        ),
        nodes=(
            Node("authorize", "barn.specialist_decision", "License delegation"),
            Node("advise", "bough.policy", "Optional policy advice"),
            Node("verify", "barn.verify_artifact", "Independent verification"),
        ),
        edges=(),
        executable=False,
        tags=("agents", "delegation", "authority"),
    ),
    "exact-vs-stochastic": SolutionTemplate(
        id="exact-vs-stochastic",
        name="Exact versus stochastic check",
        goal="Check that stochastic execution agrees with an exact model where an exact answer is licensed.",
        description=(
            "Bough supplies the analytic answer and OSAHR supplies independent "
            "scheduler trajectories; the existing upstream comparison checks agreement."
        ),
        nodes=(
            Node("model", "osahr.model", "Typed model"),
            Node("simulate", "osahr.simulate", "Kernel trajectories"),
            Node("exact", "bough.reach", "Exact reach"),
        ),
        edges=(Edge("model", "model", "simulate", "model"),),
        executable=False,
        tags=("verification", "simulation", "exact"),
    ),
}


def capability_catalog() -> list[dict[str, Any]]:
    return [CAPABILITIES[key].to_dict() for key in sorted(CAPABILITIES)]


def template_catalog() -> list[dict[str, Any]]:
    return [TEMPLATES[key].to_dict() for key in TEMPLATES]


def _port(capability: Capability, name: str, *, output: bool) -> Port | None:
    ports = capability.outputs if output else capability.inputs
    return next((p for p in ports if p.name == name), None)


def validate_solution(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a solution graph without executing any system.

    V0 intentionally validates a DAG and exact port-type matches only. A future
    compiler may introduce registered converters, but it must never infer an
    implicit cross-system conversion.
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    raw_nodes = list(payload.get("nodes") or [])
    raw_edges = list(payload.get("edges") or [])

    ids: set[str] = set()
    node_caps: dict[str, Capability] = {}
    for idx, raw in enumerate(raw_nodes):
        node_id = str(raw.get("id") or "").strip()
        cap_id = str(raw.get("capability") or "").strip()
        if not node_id:
            errors.append({"kind": "node", "index": idx, "message": "node id is required"})
            continue
        if node_id in ids:
            errors.append({"kind": "node", "node": node_id, "message": "duplicate node id"})
            continue
        ids.add(node_id)
        cap = CAPABILITIES.get(cap_id)
        if cap is None:
            errors.append({
                "kind": "capability",
                "node": node_id,
                "message": f"unknown capability: {cap_id}",
            })
            continue
        node_caps[node_id] = cap

    adjacency: dict[str, list[str]] = {node_id: [] for node_id in ids}

    for idx, raw in enumerate(raw_edges):
        source = str(raw.get("source") or "")
        target = str(raw.get("target") or "")
        source_port = str(raw.get("source_port") or raw.get("sourcePort") or "")
        target_port = str(raw.get("target_port") or raw.get("targetPort") or "")

        if source not in ids or target not in ids:
            errors.append({
                "kind": "edge",
                "index": idx,
                "message": "edge references an unknown node",
                "source": source,
                "target": target,
            })
            continue

        source_cap = node_caps.get(source)
        target_cap = node_caps.get(target)
        if source_cap is None or target_cap is None:
            continue

        out_port = _port(source_cap, source_port, output=True)
        in_port = _port(target_cap, target_port, output=False)
        if out_port is None:
            errors.append({
                "kind": "edge",
                "index": idx,
                "message": f"{source_cap.id} has no output port {source_port!r}",
            })
            continue
        if in_port is None:
            errors.append({
                "kind": "edge",
                "index": idx,
                "message": f"{target_cap.id} has no input port {target_port!r}",
            })
            continue
        if out_port.type != in_port.type:
            errors.append({
                "kind": "type",
                "index": idx,
                "message": "port types do not match",
                "sourceType": out_port.type,
                "targetType": in_port.type,
                "hint": "add an explicit registered seam; implicit conversion is forbidden",
            })
            continue
        adjacency[source].append(target)

    # DAG check. Cyclic solution execution semantics are intentionally not part
    # of v0; a feedback loop must become an explicit future primitive.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return False
        if node_id in visited:
            return True
        visiting.add(node_id)
        for nxt in adjacency.get(node_id, []):
            if not visit(nxt):
                return False
        visiting.remove(node_id)
        visited.add(node_id)
        return True

    for node_id in ids:
        if node_id not in visited and not visit(node_id):
            errors.append({
                "kind": "graph",
                "message": "cycles are not executable in solution-builder v0",
            })
            break

    # Missing required inputs are warnings rather than errors because they may
    # be bound from user-supplied run inputs rather than another node.
    incoming = {
        (str(e.get("target") or ""), str(e.get("target_port") or e.get("targetPort") or ""))
        for e in raw_edges
    }
    for node_id, cap in node_caps.items():
        for port in cap.inputs:
            if port.required and (node_id, port.name) not in incoming:
                warnings.append({
                    "kind": "unbound_input",
                    "node": node_id,
                    "port": port.name,
                    "type": port.type,
                    "message": "must be supplied by the user/run context",
                })

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "nodeCount": len(raw_nodes),
        "edgeCount": len(raw_edges),
    }
