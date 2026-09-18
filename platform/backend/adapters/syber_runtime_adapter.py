"""Adapter: SyberRuntime.

Invocation: direct in-process import of `syberruntime`. The package has no
third-party dependencies, so the real kernel simply runs inside the platform
process. This adapter creates and folds nothing itself — every state value it
returns comes from `Runtime.rebuild_state()`, which replays the real
hash-chained operation log.

Lifecycle: one `Runtime` per platform session, rooted at a scratch directory.
The repository checkout is never written to.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from syberruntime import (
    BudgetExceededError,
    FixedPolicy,
    Runtime,
    StabilizationBlockedError,
)
from syberruntime.operation_log import LogIntegrityError
from syberruntime.policy import CenterPolicy

from contract import EventSink, Recorder

SYSTEM = "syber_runtime"


class SyberRuntimeAdapter:
    def __init__(self, sink: EventSink, session_id: str, root: Path) -> None:
        self.sink = sink
        self.session_id = session_id
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.rec = Recorder(sink, SYSTEM, session_id)
        self._profile = "production"
        self._max_debt = 10.0
        self.runtime = self._build_runtime()

    # -- lifecycle ---------------------------------------------------------

    def _build_runtime(self) -> Runtime:
        policy = FixedPolicy(
            default_profile=self._profile,
            default_max_debt=self._max_debt,
            center_policies={"root": CenterPolicy(profile_name=self._profile, max_debt=self._max_debt)},
        )
        return Runtime(self.root, policy=policy)

    def set_policy(self, *, profile: str, max_debt: float) -> dict[str, Any]:
        """Re-bind the policy. The log is untouched; only future accrual changes."""
        self._profile = profile
        self._max_debt = float(max_debt)
        self.runtime = self._build_runtime()
        prof = self.runtime.policy.profile_for("root")
        return {
            "profile": prof.name,
            "accrualRate": prof.accrual_rate,
            "floorRequired": prof.floor_required,
            "maxDebt": self.runtime.policy.max_debt_for("root"),
        }

    def reset(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.runtime = self._build_runtime()

    # -- operations --------------------------------------------------------

    def create_thread(self, intent: str) -> dict[str, Any]:
        entry, event = self.rec.run(
            self.runtime.create_thread,
            event_type="operation.append",
            event_label="ThreadCreate",
            intent=intent,
            input_payload={"intent": intent},
            transform=_entry_view,
        )
        return {"entry": _entry_view(entry), "eventSeq": event.seq, "state": self.state()}

    def record_feature(
        self,
        *,
        thread_id: str,
        artifact_name: str,
        content: str,
        intent: str,
        generative_mass: float,
        blast_radius: float,
        criticality: float,
    ) -> dict[str, Any]:
        before = self.state()
        entry, event = self.rec.run(
            self.runtime.record_feature,
            thread_id,
            event_type="operation.append",
            event_label="Feature",
            refusals=(BudgetExceededError,),
            input_payload={
                "intent": intent,
                "artifactName": artifact_name,
                "generativeMass": generative_mass,
                "blastRadius": blast_radius,
                "criticality": criticality,
                "contentBytes": len(content.encode("utf-8")),
            },
            state_before={"totalDebt": before["debt"]["totalResidual"]},
            artifact_name=artifact_name,
            content=content,
            intent=intent,
            generative_mass=generative_mass,
            blast_radius=blast_radius,
            criticality=criticality,
            transform=_entry_view,
        )
        after = self.state()
        event.stateAfter = {"totalDebt": after["debt"]["totalResidual"]}
        return {"entry": _entry_view(entry), "eventSeq": event.seq, "state": after}

    def record_test(self, *, thread_id: str, artifact_digest: str, check: dict) -> dict[str, Any]:
        before = self.state()
        entry, event = self.rec.run(
            self.runtime.record_test,
            thread_id,
            event_type="operation.append",
            event_label="Test",
            input_payload={"artifactDigest": artifact_digest, "check": check},
            state_before={"openObligations": _open_ids(before, artifact_digest)},
            artifact_digest=artifact_digest,
            check=check,
            transform=_entry_view,
        )
        after = self.state()
        event.stateAfter = {"openObligations": _open_ids(after, artifact_digest)}
        verification = entry.operation.params.get("verification", {})
        event.evidence = {
            "checkKind": verification.get("kind"),
            "passed": verification.get("passed"),
            "details": verification.get("details"),
            "attemptedObligations": verification.get("attempted_obligations"),
            "dischargedObligations": verification.get("discharged_obligations"),
        }
        return {
            "entry": _entry_view(entry),
            "verification": verification,
            "eventSeq": event.seq,
            "state": after,
        }

    def stabilize(self, *, thread_id: str, artifact_digest: str | None) -> dict[str, Any]:
        """Real fail-closed path: open floor obligations refuse stabilization."""
        before = self.state()
        entry, event = self.rec.run(
            self.runtime.stabilize,
            thread_id,
            event_type="operation.stabilize",
            event_label="Stabilize",
            refusals=(StabilizationBlockedError,),
            input_payload={"artifactDigest": artifact_digest},
            state_before={
                "openFloorObligations": _open_ids(before, artifact_digest, floor_only=True)
                if artifact_digest
                else None
            },
            artifact_digest=artifact_digest,
            transform=_entry_view,
        )
        return {"entry": _entry_view(entry), "eventSeq": event.seq, "state": self.state()}

    # -- evidence ----------------------------------------------------------

    def merkle_root(self) -> dict[str, Any]:
        root, event = self.rec.run(
            self.runtime.merkle_root_hash,
            event_type="evidence.merkle_root",
            event_label="Merkle root",
        )
        return {"root": root, "eventSeq": event.seq}

    def inclusion_proof(self, index: int) -> dict[str, Any]:
        proof, event = self.rec.run(
            self.runtime.inclusion_proof,
            index,
            event_type="evidence.inclusion_proof",
            event_label=f"Inclusion proof #{index}",
            input_payload={"index": index},
            transform=lambda p: p.to_dict() if hasattr(p, "to_dict") else _obj(p),
        )
        return {"proof": _obj(proof), "eventSeq": event.seq}

    def replay_check(self) -> dict[str, Any]:
        ok, event = self.rec.run(
            self.runtime.replay_is_deterministic,
            event_type="evidence.replay_check",
            event_label="Deterministic replay",
        )
        return {"deterministic": ok, "eventSeq": event.seq}

    def verify_chain(self) -> dict[str, Any]:
        """Force full hash-chain revalidation; surfaces LogIntegrityError for real."""
        entries, event = self.rec.run(
            self.runtime.log.entries,
            event_type="evidence.chain_verify",
            event_label="Hash-chain verification",
            refusals=(LogIntegrityError,),
            validate=True,
            transform=lambda es: {"entryCount": len(es)},
        )
        return {
            "entryCount": len(entries),
            "head": entries[-1].entry_hash if entries else None,
            "eventSeq": event.seq,
        }

    def metrics(self) -> dict[str, Any]:
        m, event = self.rec.run(
            self.runtime.metrics,
            event_type="evidence.metrics",
            event_label="Runtime metrics",
        )
        return {"metrics": _obj(m), "eventSeq": event.seq}

    def inspect_artifact(self, digest: str) -> dict[str, Any]:
        report, event = self.rec.run(
            self.runtime.inspect_artifact,
            digest,
            event_type="evidence.inspect_artifact",
            event_label="Inspect artifact",
            input_payload={"digest": digest},
        )
        return {"report": _obj(report), "eventSeq": event.seq}

    def export_prov(self) -> dict[str, Any]:
        doc, event = self.rec.run(
            self.runtime.export_prov,
            event_type="evidence.export_prov",
            event_label="W3C PROV export",
        )
        return {"prov": _obj(doc), "eventSeq": event.seq}

    # -- read-only views ---------------------------------------------------

    def state(self) -> dict[str, Any]:
        st = self.runtime.rebuild_state()
        raw = st.to_dict()
        debt = raw.get("debt", {})
        obligations = debt.get("obligations", {})
        if isinstance(obligations, list):
            obligations = {o.get("id"): o for o in obligations}
        return {
            "threads": raw.get("threads", {}),
            "artifacts": raw.get("artifacts", {}),
            "operationCount": len(raw.get("operations", {})),
            "debt": {
                "totalResidual": st.debt.total_residual_debt(),
                "obligations": obligations,
                "raw": debt,
            },
            "policy": {
                "profile": self.runtime.policy.profile_for("root").name,
                "accrualRate": self.runtime.policy.profile_for("root").accrual_rate,
                "floorRequired": self.runtime.policy.profile_for("root").floor_required,
                "maxDebt": self.runtime.policy.max_debt_for("root"),
            },
        }

    def log(self) -> list[dict[str, Any]]:
        return [_entry_view(e) for e in self.runtime.log.entries(validate=True)]

    def artifact_text(self, digest: str) -> str:
        state = self.runtime.rebuild_state()
        ref = state.artifacts[digest].ref
        return self.runtime.blobs.get_text(ref)


# -- projections ----------------------------------------------------------


def _entry_view(entry: Any) -> dict[str, Any]:
    op = entry.operation
    return {
        "index": getattr(entry, "index", None),
        "entryHash": entry.entry_hash,
        "prevHash": op.prev_hash,
        "operation": {
            "id": op.id,
            "type": op.type,
            "prevHash": op.prev_hash,
            "threadId": op.thread_id,
            "centerId": op.center_id,
            "parents": list(op.parents),
            "params": op.params,
            "inputs": [i.to_dict() for i in op.inputs],
            "outputs": [o.to_dict() for o in op.outputs],
            "evaluation": op.evaluation.to_dict(),
            "provenance": op.provenance.to_dict(),
        },
    }


def _open_ids(state: dict, artifact_digest: str | None, *, floor_only: bool = False) -> list[str]:
    if not artifact_digest:
        return []
    out = []
    for oid, ob in (state.get("debt", {}).get("obligations") or {}).items():
        if not isinstance(ob, dict):
            continue
        if ob.get("artifact_digest") != artifact_digest:
            continue
        if ob.get("status") != "open":
            continue
        if floor_only and not ob.get("floor_required"):
            continue
        out.append(oid)
    return out


def _obj(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return value
