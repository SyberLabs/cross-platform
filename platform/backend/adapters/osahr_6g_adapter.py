"""Adapter: the OSAHR 6G semantic twin.

Invocation: direct in-process import of the repository's own experiment module,
`osahr-6g/osahr_6g_experiment_release/semantic_6g_twin_experiment.py`. That file
builds the schema, the rule repertoire and the RAN/MEC topology; this adapter
builds nothing. It creates the real `osahr.Runtime` over that model, injects the
same outage and arrival-stop events the experiment's own `run_one` injects, and
then drives `runtime.step()` one event at a time so the network can be watched
rewriting itself.

Everything the interface draws is read off the live runtime:

  * vertices and their attributes from `runtime.graph.vertices`
  * hyperedges and their role incidences from `runtime.graph.edges`
  * the rule that fired, its hazard at firing, and the total activity it was
    competing against, from `EventRecord.cause`
  * what appeared and disappeared from `EventRecord.graph_delta`
  * the sufficient statistics from `runtime.memory`

No position, probability or metric is computed here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from contract import EventSink, Provenance, Recorder, SyberEvent

SYSTEM = "osahr"

_EXPERIMENT_DIR = (
    Path(__file__).resolve().parents[3]
    / "systems" / "osahr" / "osahr-6g" / "osahr_6g_experiment_release"
)
if str(_EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_EXPERIMENT_DIR))

import semantic_6g_twin_experiment as g6  # noqa: E402  (path must be set first)
from osahr import ExternalEvent, Runtime, RuntimeConfig, ScheduledAdaptation  # noqa: E402
from osahr import SchedulerKind, StateAssignment  # noqa: E402
from osahr.rng import derive_seed  # noqa: E402


POLICY_NOTES = {
    "throughput": "Routes on service rate, link quality, load and energy alone. "
                  "It cannot see what a task is for.",
    "qos": "Adds link reliability and semantic fidelity to the same preference. "
           "Still blind to which task is carrying the value.",
    "semantic": "Adds utility/deadline x reliability x fidelity, so an urgent, "
                "valuable task pulls toward the node most likely to deliver it in time.",
}

RULE_NOTES = {
    "generate-critical": "A robot emits a critical task: high utility, tight deadline.",
    "generate-background": "A robot emits a background task: low utility, loose deadline.",
    "route-task": "A queued task is bound into a Transit hyperedge over "
                  "(source, task, gNB, edge node). Competing embeddings are sampled "
                  "in proportion to hazard, which is what makes routing a policy.",
    "complete-task": "A task in transit is delivered; the Transit edge dissolves.",
    "reroute-failed-edge": "The chosen edge node became unavailable, so the binding "
                           "is torn down and the task requeued.",
    "handover": "A robot moves: its Association edge is rewired to a neighbouring gNB.",
    "external_input": "Not a rule firing. The physical twin pushed a value in through an "
                      "open boundary handle - this is the MEC outage arriving from outside "
                      "the model, which is what `open` means in 'open stochastic'.",
    "scheduled_adaptation": "A scheduled parameter change: task arrivals are switched off so "
                            "the run can drain.",
}


class Osahr6GAdapter:
    """One live 6G twin per platform session."""

    def __init__(self, sink: EventSink, session_id: str) -> None:
        self.sink = sink
        self.session_id = session_id
        self.rec = Recorder(sink, SYSTEM, session_id)
        self.runtime: Runtime | None = None
        self.policy: str | None = None
        self.cfg = g6.ExperimentConfig()
        self.seed: int | None = None
        self._recent: list[dict[str, Any]] = []

    # -- lifecycle ---------------------------------------------------------

    def start(self, *, policy: str = "semantic", seed: int = 7, horizon: float | None = None) -> dict[str, Any]:
        if policy not in g6.POLICIES:
            raise ValueError(f"policy must be one of {g6.POLICIES}")
        cfg = g6.ExperimentConfig()
        if horizon is not None:
            cfg = g6.ExperimentConfig(**{**vars(cfg), "horizon": float(horizon)})
        self.cfg = cfg
        self.policy = policy

        (model, repertoire), event = self.rec.run(
            g6.build_model,
            policy,
            cfg,
            event_type="osahr6g.build_model",
            event_label=f"build 6G twin ({policy})",
            input_payload={"policy": policy, "horizon": cfg.horizon,
                           "outage": [cfg.fast_outage_start, cfg.fast_outage_end]},
            transform=lambda r: {"repertoireId": str(r[1])[:24]},
        )

        self.seed = derive_seed(seed, "6g:interactive")
        self.runtime = Runtime(
            model,
            root_seed=self.seed,
            config=RuntimeConfig(
                scheduler=SchedulerKind.NEXT_REACTION,
                matcher_backend="incremental",
                incremental_verify=False,
                max_events=200_000,
            ),
        )

        # The same disruption the committed experiment injects: MEC-fast is taken
        # down through a boundary handle, then restored.
        self.runtime.inject(ExternalEvent(
            cfg.fast_outage_start, "physical-twin", 1, "fast-down",
            "fast-edge-control", {"available": False}))
        self.runtime.inject(ExternalEvent(
            cfg.fast_outage_end, "physical-twin", 2, "fast-up",
            "fast-edge-control", {"available": True}))
        self.runtime.schedule_adaptation(ScheduledAdaptation(
            cfg.arrivals_stop, 1, "stop-arrivals",
            (StateAssignment("parameters.arrival_scale", 0.0),)))

        self._recent = []
        return {
            "policy": policy,
            "policyNote": POLICY_NOTES[policy],
            "seed": self.seed,
            "config": {
                "horizon": cfg.horizon, "arrivalsStop": cfg.arrivals_stop,
                "outageStart": cfg.fast_outage_start, "outageEnd": cfg.fast_outage_end,
                "nUes": cfg.n_ues,
                "criticalDeadline": cfg.critical_deadline,
                "backgroundDeadline": cfg.background_deadline,
                "criticalUtility": cfg.critical_utility,
                "backgroundUtility": cfg.background_utility,
            },
            "snapshot": self.snapshot(),
            "eventSeq": event.seq,
        }

    # -- stepping ----------------------------------------------------------

    def step(self, count: int = 1) -> dict[str, Any]:
        """Advance the twin by up to `count` real kernel events."""
        rt = self._require()
        records: list[dict[str, Any]] = []
        stopped: str | None = None

        for _ in range(max(1, min(int(count), 500))):
            if rt.time >= self.cfg.horizon:
                stopped = "horizon reached"
                break
            nxt = rt.peek_next_event_time()
            if nxt is None or nxt > self.cfg.horizon:
                stopped = "no further event before the horizon"
                break
            result = rt.step()
            if result.event is None:
                stopped = result.reason or str(result.status)
                break
            records.append(_event_view(result.event))

        self._recent = (records + self._recent)[:60]

        if records:
            last = records[-1]
            self.sink.emit(SyberEvent(
                system=SYSTEM,
                sessionId=self.session_id,
                eventType="osahr6g.step",
                label=f"{len(records)} kernel event(s) -> t={last['time']:.3f}s",
                status="ok",
                input={"requested": count, "policy": self.policy},
                output={"fired": [r["rule"] for r in records][:12],
                        "time": last["time"], "eventIndex": last["index"]},
                evidence={"stateHash": rt.state_hash[:24], "totalActivity": last.get("totalActivity")},
                provenance=Provenance.of(SYSTEM, Runtime.step).to_dict(),
                metadata={"model": "osahr-6g semantic twin"},
            ))

        return {
            "events": records,
            "stopped": stopped,
            "snapshot": self.snapshot(),
        }

    def run_to(self, time: float) -> dict[str, Any]:
        """Step until the twin passes `time`, bounded so a request cannot hang."""
        rt = self._require()
        target = min(float(time), self.cfg.horizon)
        records: list[dict[str, Any]] = []
        stopped = None
        budget = 4000
        while rt.time < target and budget > 0:
            budget -= 1
            nxt = rt.peek_next_event_time()
            if nxt is None or nxt > target:
                stopped = "no further event before the target"
                break
            result = rt.step()
            if result.event is None:
                stopped = result.reason or str(result.status)
                break
            records.append(_event_view(result.event))
        if budget == 0:
            stopped = "event budget for one request exhausted"

        self._recent = (records[::-1] + self._recent)[:60]
        if records:
            self.sink.emit(SyberEvent(
                system=SYSTEM,
                sessionId=self.session_id,
                eventType="osahr6g.run_to",
                label=f"advance to t={rt.time:.2f}s ({len(records)} events)",
                status="ok",
                input={"target": target, "policy": self.policy},
                output={"events": len(records), "time": rt.time},
                evidence={"stateHash": rt.state_hash[:24]},
                provenance=Provenance.of(SYSTEM, Runtime.step).to_dict(),
            ))
        return {"events": records[-40:], "stopped": stopped, "snapshot": self.snapshot()}

    async def stream_to(self, time: float, *, frame_events: int = 8):
        """Advance to `time`, yielding a frame every few events.

        The kernel runs at roughly 25 events a second with full event records,
        so a 35-second horizon is a ten-second wait. Streaming turns that from a
        frozen request into the thing actually worth watching: the network
        rewiring itself as tasks arrive, route, complete and reroute.
        """
        import asyncio

        rt = self._require()
        target = min(float(time), self.cfg.horizon)
        frame: list[dict[str, Any]] = []
        total = 0
        budget = 6000

        yield {"type": "start", "target": target, "from": rt.time}

        while rt.time < target and budget > 0:
            budget -= 1
            nxt = rt.peek_next_event_time()
            if nxt is None or nxt > target:
                break
            result = rt.step()
            if result.event is None:
                yield {"type": "stopped", "reason": result.reason or str(result.status)}
                break
            record = _event_view(result.event)
            frame.append(record)
            self._recent = ([record] + self._recent)[:60]
            total += 1

            if len(frame) >= frame_events:
                yield {"type": "frame", "events": frame, "snapshot": self.snapshot()}
                frame = []
                await asyncio.sleep(0)  # let the response flush

        if frame:
            yield {"type": "frame", "events": frame, "snapshot": self.snapshot()}

        self.sink.emit(SyberEvent(
            system=SYSTEM,
            sessionId=self.session_id,
            eventType="osahr6g.run_to",
            label=f"advance to t={rt.time:.2f}s ({total} events)",
            status="ok",
            input={"target": target, "policy": self.policy},
            output={"events": total, "time": rt.time},
            evidence={"stateHash": rt.state_hash[:24]},
            provenance=Provenance.of(SYSTEM, Runtime.step).to_dict(),
        ))
        yield {"type": "end", "events": total, "snapshot": self.snapshot()}

    # -- observation -------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        rt = self._require()
        g = rt.graph

        vertices: dict[str, dict[str, Any]] = {}
        for vid, v in g.vertices.items():
            vertices[str(vid)] = {
                "id": str(vid),
                "type": v.type_id,
                "attributes": {k: _plain(x) for k, x in (v.attributes or {}).items()},
            }

        edges = []
        for eid, e in g.edges.items():
            edges.append({
                "id": str(eid),
                "type": e.type_id,
                "tail": [{"role": i.role, "vertex": str(i.vertex_id)} for i in e.tail],
                "head": [{"role": i.role, "vertex": str(i.vertex_id)} for i in e.head],
                "attributes": {k: _plain(x) for k, x in (e.attributes or {}).items()},
                "arity": len(e.tail) + len(e.head),
            })

        counts: dict[str, int] = {}
        for e in edges:
            counts[e["type"]] = counts.get(e["type"], 0) + 1
        for v in vertices.values():
            counts[v["type"]] = counts.get(v["type"], 0) + 1

        z = {k: _plain(v) for k, v in rt.memory.items()}
        generated = float(z.get("generated") or 0)
        gen_utility = float(z.get("generated_utility") or 0)
        timely_utility = float(z.get("timely_semantic_utility") or 0)
        gen_crit = float(z.get("generated_critical") or 0)
        timely_crit = float(z.get("timely_critical") or 0)
        energy = float(z.get("energy") or 0)

        return {
            "time": rt.time,
            "eventIndex": rt.event_index,
            "stateHash": rt.state_hash,
            "horizon": self.cfg.horizon,
            "outage": {
                "start": self.cfg.fast_outage_start,
                "end": self.cfg.fast_outage_end,
                "active": self.cfg.fast_outage_start <= rt.time < self.cfg.fast_outage_end,
            },
            "arrivalsStop": self.cfg.arrivals_stop,
            "vertices": vertices,
            "edges": edges,
            "counts": counts,
            "memory": z,
            "derived": {
                "goalUtilityRatio": (timely_utility / gen_utility) if gen_utility else None,
                "criticalSuccessRate": (timely_crit / gen_crit) if gen_crit else None,
                "timelyTaskRate": (float(z.get("timely") or 0) / generated) if generated else None,
                "semanticEfficiency": (timely_utility / energy) if energy > 0 else None,
            },
            "recentEvents": self._recent[:24],
        }

    def reset(self) -> dict[str, Any]:
        policy = self.policy or "semantic"
        return self.start(policy=policy, seed=(self.seed or 7))

    def _require(self) -> Runtime:
        if self.runtime is None:
            raise ValueError("No 6G twin started in this session.")
        return self.runtime


# -- projections ----------------------------------------------------------


def _event_view(ev: Any) -> dict[str, Any]:
    """Serialize one EventRecord. Reads only; computes nothing."""
    cause = ev.cause or {}
    delta = ev.graph_delta
    kind = ev.kind.value if hasattr(ev.kind, "value") else str(ev.kind)
    # Not every event is a rule firing: boundary input and scheduled adaptations
    # are real events too, and the outage is the most consequential one in the run.
    rule = str(cause.get("rule_id") or "") or kind
    return {
        "index": ev.event_index,
        "kind": kind,
        "time": ev.post_time,
        "deltaTime": ev.delta_time,
        "rule": rule,
        "ruleNote": RULE_NOTES.get(rule),
        "hazard": _num(cause.get("hazard")),
        "totalActivity": _num(cause.get("pre_total_activity")),
        "scheduler": str(cause.get("scheduler") or ""),
        "matchId": str(cause.get("match_id") or "")[:16],
        "bindings": {
            "vertices": {k: str(v) for k, v in (cause.get("vertex_map") or {}).items()},
            "edges": {k: str(v) for k, v in (cause.get("edge_map") or {}).items()},
        },
        "created": {
            "vertices": [{"id": str(i), "type": v.type_id,
                          "attributes": {k: _plain(x) for k, x in (v.attributes or {}).items()}}
                         for i, v in delta.created_vertices.items()],
            "edges": [{"id": str(i), "type": e.type_id, "arity": len(e.tail) + len(e.head)}
                      for i, e in delta.created_edges.items()],
        },
        "deleted": {
            "vertices": [{"id": str(i), "type": v.type_id} for i, v in delta.deleted_vertices.items()],
            "edges": [{"id": str(i), "type": e.type_id} for i, e in delta.deleted_edges.items()],
        },
        "draws": len(ev.random_draws or ()),
        "isRule": bool(cause.get("rule_id")),
        "cause": {k: _plain(v) for k, v in cause.items()},
        "stateHash": ev.post_state_hash[:16],
    }


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)
