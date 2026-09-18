"""Adapter: Barn.

Invocation: the real `barn.api.create_app()` ASGI application is mounted by the
platform, and this adapter reuses **that application's own** `BarnEngine`
instance (`app.state.engine`). There is only ever one engine, one store and one
set of per-run asyncio locks, so an operation driven from the platform UI and an
operation driven by an HTTP client hitting the mounted API are the same
operation against the same state.

Nothing about Barn's transition semantics is reimplemented here. Every refusal
the UI displays is a `TransitionError` raised by `barn/engine.py`.
"""

from __future__ import annotations

from typing import Any

from barn.audit import audit_run
from barn.causal import why_agent_exists
from barn.demo import bootstrap_demo
from barn.engine import BarnEngine, TransitionError
from barn.metrics import summarize_run
from barn.store import RunNotFoundError

from contract import EventSink, Recorder

SYSTEM = "barn"

REFUSALS = (TransitionError,)


def _cmd(prefix: str) -> str:
    from uuid import uuid4

    return f"{prefix}_{uuid4().hex}"


class BarnAdapter:
    def __init__(self, sink: EventSink, session_id: str, engine: BarnEngine) -> None:
        self.rec = Recorder(sink, SYSTEM, session_id)
        self.engine = engine
        self.run_id: str | None = None

    # -- lifecycle ---------------------------------------------------------

    async def create_run(
        self, *, goal: str, max_active_agents: int = 6, chief_capabilities: set[str] | None = None
    ) -> dict[str, Any]:
        run, event = await self.rec.arun(
            self.engine.create_run,
            event_type="barn.create_run",
            event_label="create run",
            input_payload={"goal": goal, "maxActiveAgents": max_active_agents},
            goal=goal,
            max_active_agents=max_active_agents,
            chief_capabilities=chief_capabilities or {"generalist"},
            command_id=_cmd("cmd"),
            transform=lambda r: {"runId": r.id, "goal": r.goal},
        )
        self.run_id = run.id
        return {"run": run.model_dump(mode="json"), "eventSeq": event.seq}

    async def bootstrap_demo(self) -> dict[str, Any]:
        """Barn's own committed demo fixture — upstream code, not ours."""
        run, event = await self.rec.arun(
            bootstrap_demo,
            self.engine,
            event_type="barn.bootstrap_demo",
            event_label="bootstrap demo run",
            transform=lambda r: {"runId": r.id if hasattr(r, "id") else r.get("id")},
        )
        rid = run.id if hasattr(run, "id") else run.get("id")
        self.run_id = rid
        return {"runId": rid, "eventSeq": event.seq}

    # -- work graph --------------------------------------------------------

    async def add_work(
        self,
        *,
        actor_agent_id: str,
        title: str,
        description: str = "",
        required_capabilities: set[str] | None = None,
        parent_work_id: str | None = None,
        dependency_ids: set[str] | None = None,
        requires_verification: bool = False,
        priority: int = 0,
    ) -> dict[str, Any]:
        work, event = await self.rec.arun(
            self.engine.add_work,
            self._run(),
            event_type="barn.add_work",
            event_label=f"add work: {title}",
            refusals=REFUSALS,
            input_payload={
                "title": title,
                "requiredCapabilities": sorted(required_capabilities or []),
                "requiresVerification": requires_verification,
                "dependencyIds": sorted(dependency_ids or []),
            },
            actor_agent_id=actor_agent_id,
            title=title,
            description=description,
            required_capabilities=required_capabilities or set(),
            parent_work_id=parent_work_id,
            dependency_ids=dependency_ids or set(),
            requires_verification=requires_verification,
            priority=priority,
            command_id=_cmd("cmd"),
            transform=lambda w: w.model_dump(mode="json"),
        )
        return {"work": work.model_dump(mode="json"), "eventSeq": event.seq}

    async def request_specialist(
        self, *, requesting_agent_id: str, work_id: str, capability: str, role: str, reason: str
    ) -> dict[str, Any]:
        """The spawn / reuse / reject licensing decision."""
        before = await self.snapshot()
        decision, event = await self.rec.arun(
            self.engine.request_specialist,
            self._run(),
            event_type="barn.specialist_decision",
            event_label=f"specialist: {capability}",
            refusals=REFUSALS,
            input_payload={"capability": capability, "role": role, "reason": reason, "workId": work_id},
            state_before={"agentCount": len(before["state"]["agents"])},
            requesting_agent_id=requesting_agent_id,
            work_id=work_id,
            capability=capability,
            role=role,
            reason=reason,
            command_id=_cmd("cmd"),
            transform=lambda d: d.model_dump(mode="json"),
        )
        after = await self.snapshot()
        event.stateAfter = {"agentCount": len(after["state"]["agents"])}
        event.evidence = {
            "outcome": decision.outcome.value if hasattr(decision.outcome, "value") else decision.outcome,
            "reason": decision.reason,
        }
        return {"decision": decision.model_dump(mode="json"), "eventSeq": event.seq}

    async def assign_work(self, *, work_id: str, agent_id: str) -> dict[str, Any]:
        work, event = await self.rec.arun(
            self.engine.assign_work,
            self._run(),
            event_type="barn.assign_work",
            event_label="assign work",
            refusals=REFUSALS,
            input_payload={"workId": work_id, "agentId": agent_id},
            work_id=work_id,
            agent_id=agent_id,
            command_id=_cmd("cmd"),
            transform=lambda w: w.model_dump(mode="json"),
        )
        return {"work": work.model_dump(mode="json"), "eventSeq": event.seq}

    async def submit_artifact(
        self, *, agent_id: str, work_id: str, kind: str, uri: str, content_hash: str
    ) -> dict[str, Any]:
        artifact, event = await self.rec.arun(
            self.engine.submit_artifact,
            self._run(),
            event_type="barn.submit_artifact",
            event_label=f"artifact: {kind}",
            refusals=REFUSALS,
            input_payload={"kind": kind, "uri": uri, "contentHash": content_hash, "workId": work_id},
            agent_id=agent_id,
            work_id=work_id,
            kind=kind,
            uri=uri,
            content_hash=content_hash,
            command_id=_cmd("cmd"),
            transform=lambda a: a.model_dump(mode="json"),
        )
        return {"artifact": artifact.model_dump(mode="json"), "eventSeq": event.seq}

    async def record_verification(
        self, *, verifier_agent_id: str, artifact_id: str, passed: bool, evidence: str
    ) -> dict[str, Any]:
        """Independence is enforced here by Barn, not by this adapter."""
        verification, event = await self.rec.arun(
            self.engine.record_verification,
            self._run(),
            event_type="barn.verification",
            event_label="verification",
            refusals=REFUSALS,
            input_payload={
                "verifierAgentId": verifier_agent_id,
                "artifactId": artifact_id,
                "passed": passed,
                "evidence": evidence,
            },
            verifier_agent_id=verifier_agent_id,
            artifact_id=artifact_id,
            passed=passed,
            evidence=evidence,
            command_id=_cmd("cmd"),
            transform=lambda v: v.model_dump(mode="json"),
        )
        return {"verification": verification.model_dump(mode="json"), "eventSeq": event.seq}

    async def resolve_work(self, *, work_id: str, actor_agent_id: str) -> dict[str, Any]:
        work, event = await self.rec.arun(
            self.engine.resolve_work,
            self._run(),
            event_type="barn.resolve_work",
            event_label="resolve work",
            refusals=REFUSALS,
            input_payload={"workId": work_id, "actorAgentId": actor_agent_id},
            work_id=work_id,
            actor_agent_id=actor_agent_id,
            command_id=_cmd("cmd"),
            transform=lambda w: w.model_dump(mode="json"),
        )
        return {"work": work.model_dump(mode="json"), "eventSeq": event.seq}

    async def retire_agent(self, *, agent_id: str) -> dict[str, Any]:
        agent, event = await self.rec.arun(
            self.engine.retire_agent,
            self._run(),
            event_type="barn.retire_agent",
            event_label="retire agent",
            refusals=REFUSALS,
            input_payload={"agentId": agent_id},
            agent_id=agent_id,
            command_id=_cmd("cmd"),
            transform=lambda a: a.model_dump(mode="json"),
        )
        return {"agent": agent.model_dump(mode="json"), "eventSeq": event.seq}

    # -- inspection --------------------------------------------------------

    async def snapshot(self) -> dict[str, Any]:
        state = await self.engine.store.get_run(self._run())
        events = await self.engine.store.list_events(self._run())
        return {
            "state": state.model_dump(mode="json"),
            "events": [e.model_dump(mode="json") for e in events],
        }

    async def audit(self) -> dict[str, Any]:
        """Materialized state hash vs state replayed from the event log."""
        report, event = await self.rec.arun(
            audit_run,
            self.engine.store,
            self._run(),
            event_type="barn.audit",
            event_label="replay audit",
            transform=lambda r: r.model_dump(mode="json"),
        )
        return {"audit": report.model_dump(mode="json"), "eventSeq": event.seq}

    async def metrics(self) -> dict[str, Any]:
        state = await self.engine.store.get_run(self._run())
        events = await self.engine.store.list_events(self._run())
        summary, event = await self.rec.arun(
            _as_async(summarize_run),
            state,
            events,
            event_type="barn.metrics",
            event_label="run metrics",
        )
        return {"metrics": _dump(summary), "eventSeq": event.seq}

    async def why(self, agent_id: str) -> dict[str, Any]:
        """Barn's causal query: why does this agent exist?"""
        explanation, event = await self.rec.arun(
            why_agent_exists,
            self.engine.store,
            self._run(),
            agent_id,
            event_type="barn.why_agent",
            event_label="why does this agent exist?",
            input_payload={"agentId": agent_id},
            transform=lambda e: e.model_dump(mode="json"),
        )
        return {"explanation": explanation.model_dump(mode="json"), "eventSeq": event.seq}

    # -- internals ---------------------------------------------------------

    def _run(self) -> str:
        if self.run_id is None:
            raise RunNotFoundError("no run created in this session")
        return self.run_id


def _as_async(fn):
    """Wrap a sync upstream function so `arun` can record it with real provenance.

    `Provenance.of` unwraps to the original function, so the recorded module and
    line still point at the upstream source, not at this shim.
    """
    import functools

    @functools.wraps(fn)
    async def inner(*args, **kwargs):
        return fn(*args, **kwargs)

    return inner


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value
