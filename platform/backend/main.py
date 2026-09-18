"""SyberLabs demonstration platform — orchestration layer.

This process owns no domain logic. It:

  * mounts Barn's real ASGI application at /systems/barn (unmodified, and
    reachable directly so the source system stays independently usable);
  * holds one adapter set per session;
  * streams the shared `SyberEvent` contract to the frontend over SSE;
  * serves the source of any file an event's provenance points at, so a claim
    about where behaviour came from can be checked against the actual bytes.

Every route below delegates to an adapter, and every adapter delegates to a
source system. Refusals propagate as HTTP 409 with the system's own message.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from barn.api import create_app as create_barn_app

import scenarios as scenario_lib
from contract import EventContext, EventSink, SystemRefusal, acting
from adapters.barn_adapter import BarnAdapter
from adapters.bough_adapter import FAMILIES, BoughAdapter
from adapters.bridge_barn_bough import BarnBoughBridge
from adapters.osahr_6g_adapter import Osahr6GAdapter
from adapters.relay_adapter import RelayAdapter, RelayUnavailable
from adapters.syber_runtime_adapter import SyberRuntimeAdapter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SYSTEMS = ROOT / "systems"
FRONTEND = HERE.parent / "frontend"

REPO_ROOTS = {
    "syber_runtime": SYSTEMS / "syber_runtime",
    "barn": SYSTEMS / "bough_and_barn" / "barn",
    "bough": SYSTEMS / "bough_and_barn" / "bough",
    "osahr": SYSTEMS / "osahr",
    "relay": SYSTEMS / "relay",
}

RELAY_SIDECAR_URL = os.environ.get("RELAY_SIDECAR_URL", "http://127.0.0.1:8766")
SCRATCH = Path(os.environ.get("SYBER_DEMO_SCRATCH", Path(tempfile.gettempdir()) / "syberlabs-demo"))

# The real Barn application. Mounted below; its engine is shared with the adapter.
barn_app = create_barn_app()

app = FastAPI(title="SyberLabs Demonstration Platform", version="1.0.0")
app.mount("/systems/barn", barn_app)


class Session:
    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.sink = EventSink()
        self.runtime = SyberRuntimeAdapter(self.sink, session_id, SCRATCH / session_id / "runtime")
        self.bough = BoughAdapter(self.sink, session_id)
        self.barn = BarnAdapter(self.sink, session_id, barn_app.state.engine)
        self.bridge = BarnBoughBridge(self.sink, session_id)
        self.relay = RelayAdapter(self.sink, session_id, RELAY_SIDECAR_URL)
        self.osahr6g = Osahr6GAdapter(self.sink, session_id)


_sessions: dict[str, Session] = {}


def session_for(request: Request) -> Session:
    sid = request.headers.get("x-syber-session") or request.query_params.get("session") or "default"
    if sid not in _sessions:
        _sessions[sid] = Session(sid)
    return _sessions[sid]


@app.middleware("http")
async def _revalidate_assets(request: Request, call_next):
    """Make the browser revalidate the frontend on every load.

    The assets are served from disk and change whenever the platform is edited.
    Without this a browser can hold a styles.css from an earlier version for a
    whole session and render the interface unstyled. ETag still makes the
    revalidation a cheap 304.
    """
    response = await call_next(request)
    if request.url.path.startswith("/assets/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.middleware("http")
async def _attribute_events(request: Request, call_next):
    """Group every event caused by one request under one operation id.

    Scenario steps set their own, narrower context, which takes precedence
    because `acting` is re-entered inside the runner.
    """
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    op = f"req_{uuid.uuid4().hex[:12]}"
    label = f"{request.method} {request.url.path}"
    with acting(EventContext(operation_id=op, label=label, kind="request")):
        return await call_next(request)


@app.exception_handler(SystemRefusal)
async def _refusal_handler(_request: Request, exc: SystemRefusal):
    """A source system refused. That is an outcome, not a server error."""
    return JSONResponse(status_code=409, content=exc.to_dict())


@app.exception_handler(RelayUnavailable)
async def _relay_unavailable(_request: Request, exc: RelayUnavailable):
    return JSONResponse(
        status_code=503,
        content={"unavailable": True, "system": "relay", "message": str(exc)},
    )


# --------------------------------------------------------------------------
# platform
# --------------------------------------------------------------------------


@app.get("/api/systems")
async def systems(request: Request) -> dict[str, Any]:
    s = session_for(request)
    relay_health = await s.relay.health()
    return {
        "sessionId": s.id,
        "systems": [
            {
                "id": "syber_runtime",
                "name": "SyberRuntime",
                "primitive": "Operation",
                "tagline": "Operations are the source of truth. Artifacts are projections.",
                "integration": "in-process Python import",
                "repo": "sykosyber/syber_runtime",
                "available": True,
            },
            {
                "id": "barn",
                "name": "Barn",
                "primitive": "BarnEvent",
                "tagline": "Every organizational mutation is licensed by a transition engine.",
                "integration": "mounted ASGI app, shared engine",
                "repo": "sykosyber/bough-and-barn",
                "available": True,
            },
            {
                "id": "bough",
                "name": "Bough",
                "primitive": "Jump chain",
                "tagline": "Rewrite systems compiled to exact path and reach probabilities.",
                "integration": "in-process Python import",
                "repo": "sykosyber/bough-and-barn",
                "available": True,
            },
            {
                "id": "osahr",
                "name": "OSAHR Cell",
                "primitive": "Typed hypergraph",
                "tagline": "Stochastic rewrite kernel with interchangeable exact schedulers.",
                "integration": "in-process, driven through Bough's comparison",
                "repo": "SyberLabs/OSAHR_Cell",
                "available": True,
            },
            {
                "id": "relay",
                "name": "Relay",
                "primitive": "Explicit handoff",
                "tagline": "Bounded context leaves; the returned draft must survive review.",
                "integration": "Node 24 sidecar importing real .ts",
                "repo": "SyberLabs/relay",
                "available": relay_health.get("available", False),
                "health": relay_health,
            },
        ],
        "liveInference": bool(os.environ.get("GOOGLE_API_KEY")),
    }


@app.get("/api/events")
async def events(request: Request, since: int = 0) -> dict[str, Any]:
    return {"events": session_for(request).sink.events(since)}


@app.get("/api/events/stream")
async def stream(request: Request):
    s = session_for(request)
    queue: asyncio.Queue = asyncio.Queue(maxsize=512)
    s.sink.subscribe(queue)

    async def gen():
        try:
            yield f"data: {json.dumps({'type': 'connected', 'sessionId': s.id})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            s.sink.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/source")
async def source(system: str = Query(...), path: str = Query(...)) -> dict[str, Any]:
    """Serve the real source file an event's provenance names.

    Resolution is confined to the checkout for that system, so a provenance
    record can be checked but the endpoint cannot be used to read the disk.
    """
    root = REPO_ROOTS.get(system)
    if root is None:
        raise HTTPException(404, f"unknown system: {system}")
    target = (root / path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(403, "path escapes the system checkout")
    if not target.is_file():
        raise HTTPException(404, f"no such file: {path}")
    text = target.read_text(encoding="utf-8", errors="replace")
    return {
        "system": system,
        "path": path,
        "lines": text.splitlines(),
        "bytes": len(text.encode("utf-8")),
    }


# --------------------------------------------------------------------------
# SyberRuntime
# --------------------------------------------------------------------------


@app.get("/api/runtime/state")
async def runtime_state(request: Request) -> dict[str, Any]:
    s = session_for(request)
    return {"state": s.runtime.state(), "log": s.runtime.log()}


@app.post("/api/runtime/policy")
async def runtime_policy(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    s = session_for(request)
    return s.runtime.set_policy(
        profile=str(body.get("profile", "production")), max_debt=float(body.get("maxDebt", 10.0))
    )


@app.post("/api/runtime/thread")
async def runtime_thread(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    return session_for(request).runtime.create_thread(str(body.get("intent", "Untitled thread")))


@app.post("/api/runtime/feature")
async def runtime_feature(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    s = session_for(request)
    return s.runtime.record_feature(
        thread_id=str(body["threadId"]),
        artifact_name=str(body.get("artifactName", "artifact.txt")),
        content=str(body.get("content", "")),
        intent=str(body.get("intent", "Add an artifact")),
        generative_mass=float(body.get("generativeMass", 1.0)),
        blast_radius=float(body.get("blastRadius", 1.0)),
        criticality=float(body.get("criticality", 1.0)),
    )


@app.post("/api/runtime/test")
async def runtime_test(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    s = session_for(request)
    return s.runtime.record_test(
        thread_id=str(body["threadId"]),
        artifact_digest=str(body["artifactDigest"]),
        check=dict(body.get("check") or {}),
    )


@app.post("/api/runtime/stabilize")
async def runtime_stabilize(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    s = session_for(request)
    return s.runtime.stabilize(
        thread_id=str(body["threadId"]), artifact_digest=body.get("artifactDigest")
    )


@app.post("/api/runtime/evidence/{kind}")
async def runtime_evidence(request: Request, kind: str, body: dict = Body(default={})) -> dict[str, Any]:
    s = session_for(request)
    if kind == "merkle-root":
        return s.runtime.merkle_root()
    if kind == "inclusion-proof":
        return s.runtime.inclusion_proof(int(body.get("index", 0)))
    if kind == "replay-check":
        return s.runtime.replay_check()
    if kind == "chain-verify":
        return s.runtime.verify_chain()
    if kind == "metrics":
        return s.runtime.metrics()
    if kind == "inspect-artifact":
        return s.runtime.inspect_artifact(str(body["digest"]))
    if kind == "export-prov":
        return s.runtime.export_prov()
    raise HTTPException(404, f"unknown evidence kind: {kind}")


@app.get("/api/runtime/artifact/{digest}")
async def runtime_artifact(request: Request, digest: str) -> dict[str, Any]:
    s = session_for(request)
    try:
        return {"digest": digest, "text": s.runtime.artifact_text(digest)}
    except KeyError:
        raise HTTPException(404, "unknown artifact")


@app.post("/api/runtime/reset")
async def runtime_reset(request: Request) -> dict[str, Any]:
    s = session_for(request)
    s.runtime.reset()
    return {"reset": True, "state": s.runtime.state()}


@app.post("/api/runtime/acceptance")
async def runtime_acceptance() -> dict[str, Any]:
    """Run SyberRuntime's real release-readiness audit as a subprocess.

    This is the fail-closed evidence gate. On a fresh clone it reports `fail`,
    because the evidence corpus those criteria audit lives in gitignored run
    directories. That result is reported exactly as the CLI produced it.
    """
    repo = REPO_ROOTS["syber_runtime"]
    env = dict(os.environ, PYTHONPATH=str(repo / "src"))
    proc = subprocess.run(
        [sys.executable, "-m", "syberruntime.cli", "acceptance-check"],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "exitCode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }
    return {
        "ok": True,
        "exitCode": proc.returncode,
        "report": report,
        "command": "python -m syberruntime.cli acceptance-check",
        "cwd": str(repo),
        "provenance": {
            "system": "syber_runtime",
            "module": "src/syberruntime/cli.py",
            "symbol": "acceptance-check",
            "execution": "subprocess invocation of the repository CLI",
        },
    }


# --------------------------------------------------------------------------
# Bough / OSAHR
# --------------------------------------------------------------------------


@app.get("/api/bough/families")
async def bough_families() -> dict[str, Any]:
    return {"families": FAMILIES}


@app.post("/api/bough/compile")
async def bough_compile(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    s = session_for(request)
    return s.bough.compile(
        str(body.get("family", "bits")),
        dict(body.get("params") or {}),
        max_depth=body.get("maxDepth"),
        max_situations=int(body.get("maxSituations", 5000)),
    )


@app.post("/api/bough/reach")
async def bough_reach(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    return session_for(request).bough.reach(str(body.get("label", "")))


@app.post("/api/bough/policy")
async def bough_policy(request: Request) -> dict[str, Any]:
    return session_for(request).bough.optimal_policy()


@app.post("/api/bough/cypher")
async def bough_cypher(request: Request) -> dict[str, Any]:
    return session_for(request).bough.cypher()


@app.post("/api/bough/path")
async def bough_path(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    return session_for(request).bough.path_probability(list(body.get("trace") or []))


@app.get("/api/osahr/model")
async def osahr_model(request: Request, family: str = "ontology", copies: int = 1, n: int = 4) -> dict[str, Any]:
    """The typed directed hypergraph and rewrite rules the kernel runs over."""
    s = session_for(request)
    params: dict[str, Any] = {}
    if family == "ontology":
        params["copies"] = copies
    elif family == "bits":
        params["n"] = n
    return s.bough.osahr_model(family, params)


@app.post("/api/osahr6g/start")
async def osahr6g_start(request: Request, body: dict = Body(default={})) -> dict[str, Any]:
    """Build the repository's own 6G semantic twin and stand up a live runtime."""
    s = session_for(request)
    return s.osahr6g.start(
        policy=str(body.get("policy", "semantic")),
        seed=int(body.get("seed", 7)),
        horizon=body.get("horizon"),
    )


@app.post("/api/osahr6g/step")
async def osahr6g_step(request: Request, body: dict = Body(default={})) -> dict[str, Any]:
    return session_for(request).osahr6g.step(int(body.get("count", 1)))


@app.post("/api/osahr6g/run-to")
async def osahr6g_run_to(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    return session_for(request).osahr6g.run_to(float(body["time"]))


@app.get("/api/osahr6g/stream")
async def osahr6g_stream(request: Request, to: float = 35.0):
    """Advance the twin to `to`, streaming a frame every few kernel events."""
    s = session_for(request)
    if s.osahr6g.runtime is None:
        raise HTTPException(400, "no 6G twin started in this session")

    async def gen():
        try:
            async for message in s.osahr6g.stream_to(to):
                yield f"data: {json.dumps(message)}\n\n"
        except Exception as exc:
            payload = {"type": "failed", "error": f"{type(exc).__name__}: {exc}"}
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/osahr6g/snapshot")
async def osahr6g_snapshot(request: Request) -> dict[str, Any]:
    s = session_for(request)
    if s.osahr6g.runtime is None:
        return {"started": False}
    return {"started": True, "snapshot": s.osahr6g.snapshot(), "policy": s.osahr6g.policy}


@app.post("/api/osahr6g/reset")
async def osahr6g_reset(request: Request) -> dict[str, Any]:
    return session_for(request).osahr6g.reset()


@app.post("/api/osahr/agreement")
async def osahr_agreement(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    s = session_for(request)
    return s.bough.osahr_agreement(
        str(body.get("family", "race")),
        dict(body.get("params") or {}),
        replicates=int(body.get("replicates", 48)),
        root_seed=int(body.get("rootSeed", 23)),
    )


# --------------------------------------------------------------------------
# Barn
# --------------------------------------------------------------------------


@app.post("/api/barn/run")
async def barn_run(request: Request, body: dict = Body(default={})) -> dict[str, Any]:
    s = session_for(request)
    return await s.barn.create_run(
        goal=str(body.get("goal", "Ship a feature")),
        max_active_agents=int(body.get("maxActiveAgents", 4)),
        chief_capabilities=set(body.get("chiefCapabilities") or ["generalist"]),
    )


@app.get("/api/barn/snapshot")
async def barn_snapshot(request: Request) -> dict[str, Any]:
    s = session_for(request)
    if s.barn.run_id is None:
        return {"run": None}
    return await s.barn.snapshot()


@app.post("/api/barn/work")
async def barn_work(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    s = session_for(request)
    return await s.barn.add_work(
        actor_agent_id=str(body["actorAgentId"]),
        title=str(body.get("title", "Untitled work")),
        description=str(body.get("description", "")),
        required_capabilities=set(body.get("requiredCapabilities") or []),
        parent_work_id=body.get("parentWorkId"),
        dependency_ids=set(body.get("dependencyIds") or []),
        requires_verification=bool(body.get("requiresVerification", False)),
        priority=int(body.get("priority", 0)),
    )


@app.post("/api/barn/specialist")
async def barn_specialist(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    s = session_for(request)
    result = await s.barn.request_specialist(
        requesting_agent_id=str(body["requestingAgentId"]),
        work_id=str(body["workId"]),
        capability=str(body.get("capability", "generalist")),
        role=str(body.get("role", "Specialist")),
        reason=str(body.get("reason", "capability gap")),
    )
    if body.get("withAdvice"):
        snap = await s.barn.snapshot()
        metrics = (await s.barn.metrics())["metrics"]
        try:
            result["advice"] = s.bridge.advise(metrics=metrics, state=snap["state"])
        except SystemRefusal as exc:
            result["advice"] = {"refused": exc.to_dict()}
    return result


@app.post("/api/barn/artifact")
async def barn_artifact(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    s = session_for(request)
    return await s.barn.submit_artifact(
        agent_id=str(body["agentId"]),
        work_id=str(body["workId"]),
        kind=str(body.get("kind", "code")),
        uri=str(body.get("uri", "repo://artifact")),
        content_hash=str(body.get("contentHash", "sha256:unknown")),
    )


@app.post("/api/barn/verification")
async def barn_verification(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    s = session_for(request)
    return await s.barn.record_verification(
        verifier_agent_id=str(body["verifierAgentId"]),
        artifact_id=str(body["artifactId"]),
        passed=bool(body.get("passed", True)),
        evidence=str(body.get("evidence", "")),
    )


@app.post("/api/barn/resolve")
async def barn_resolve(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    s = session_for(request)
    return await s.barn.resolve_work(
        work_id=str(body["workId"]), actor_agent_id=str(body["actorAgentId"])
    )


@app.post("/api/barn/assign")
async def barn_assign(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    s = session_for(request)
    return await s.barn.assign_work(work_id=str(body["workId"]), agent_id=str(body["agentId"]))


@app.post("/api/barn/retire")
async def barn_retire(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    return await session_for(request).barn.retire_agent(agent_id=str(body["agentId"]))


@app.post("/api/barn/audit")
async def barn_audit(request: Request) -> dict[str, Any]:
    return await session_for(request).barn.audit()


@app.get("/api/barn/metrics")
async def barn_metrics(request: Request) -> dict[str, Any]:
    return await session_for(request).barn.metrics()


@app.get("/api/barn/why/{agent_id}")
async def barn_why(request: Request, agent_id: str) -> dict[str, Any]:
    return await session_for(request).barn.why(agent_id)


@app.post("/api/barn/advice")
async def barn_advice(request: Request) -> dict[str, Any]:
    s = session_for(request)
    if s.barn.run_id is None:
        raise HTTPException(400, "no run in this session")
    snap = await s.barn.snapshot()
    metrics = (await s.barn.metrics())["metrics"]
    return s.bridge.advise(metrics=metrics, state=snap["state"])


# --------------------------------------------------------------------------
# Relay
# --------------------------------------------------------------------------


@app.post("/api/relay/{capability}")
async def relay_call(request: Request, capability: str, body: dict = Body(default={})) -> dict[str, Any]:
    s = session_for(request)
    if capability == "job-key":
        return await s.relay.job_key(str(body.get("url", "")), str(body.get("fallback", "fallback")))
    if capability == "requirements":
        return await s.relay.requirements(str(body.get("text", "")))
    if capability == "claim-gate":
        return await s.relay.unsupported_claims(str(body.get("body", "")), list(body.get("facts") or []))
    if capability == "planning":
        return await s.relay.planning(list(body.get("candidates") or []), int(body.get("budgetMinutes", 90)))
    if capability == "validate-packet":
        return await s.relay.validate_packet(dict(body.get("packet") or {}))
    if capability == "handoff":
        return await s.relay.handoff(
            packet=dict(body.get("packet") or {}),
            provider=str(body.get("provider", "chatgpt")),
            context=dict(body.get("context") or {}),
            live=bool(body.get("live", False)),
            draft_override=body.get("draft"),
        )
    raise HTTPException(404, f"unknown relay capability: {capability}")


# --------------------------------------------------------------------------
# Cross-system: Relay handoff -> SyberRuntime obligation
# --------------------------------------------------------------------------


@app.post("/api/cross/relay-to-runtime")
async def relay_to_runtime(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    """Record a Relay draft as a SyberRuntime Feature and try to stabilize it.

    A `relay.draft.v1` carries `reviewRequired: true`. In SyberRuntime's grammar
    that is an unverified artifact: recording it accrues a floor obligation, and
    stabilizing before the review happens is refused by the real kernel.

    Both halves are the source systems. This route only moves the object.
    """
    s = session_for(request)
    draft = dict(body.get("draft") or {})
    text = str(draft.get("draft") or "")
    if not text:
        raise HTTPException(400, "no draft text supplied")

    job = dict(draft.get("job") or {})
    thread = s.runtime.create_thread(
        f"Review Relay draft for {job.get('name') or job.get('key') or 'a posting'}"
    )
    thread_id = thread["entry"]["operation"]["threadId"]

    feature = s.runtime.record_feature(
        thread_id=thread_id,
        artifact_name=f"relay-draft-{job.get('id', 'unknown')}.txt",
        content=text,
        intent=f"Relay handoff draft (provider={draft.get('provider')}, reviewRequired={draft.get('reviewRequired')})",
        generative_mass=float(body.get("generativeMass", 1.0)),
        blast_radius=float(body.get("blastRadius", 1.0)),
        criticality=float(body.get("criticality", 1.0)),
    )
    digest = feature["entry"]["operation"]["outputs"][0]["digest"]

    outcome: dict[str, Any]
    try:
        stabilized = s.runtime.stabilize(thread_id=thread_id, artifact_digest=digest)
        outcome = {"stabilized": True, "entry": stabilized["entry"]}
    except SystemRefusal as exc:
        outcome = {"stabilized": False, "refusal": exc.to_dict()}

    return {
        "threadId": thread_id,
        "artifactDigest": digest,
        "feature": feature["entry"],
        "preReview": outcome,
        "state": s.runtime.state(),
        "explanation": (
            "Relay marked this draft reviewRequired. SyberRuntime recorded it as an "
            "unverified Feature, which accrued a floor verification obligation. "
            "Stabilizing before review is refused by syberruntime/runtime.py."
        ),
    }


@app.post("/api/cross/review-draft")
async def review_draft(request: Request, body: dict = Body(...)) -> dict[str, Any]:
    """Discharge the obligation with a real deterministic check, then stabilize."""
    s = session_for(request)
    thread_id = str(body["threadId"])
    digest = str(body["artifactDigest"])
    check = dict(body.get("check") or {"kind": "text_contains", "expected": ""})

    test = s.runtime.record_test(thread_id=thread_id, artifact_digest=digest, check=check)
    passed = bool(test["verification"].get("passed"))
    try:
        stabilized = s.runtime.stabilize(thread_id=thread_id, artifact_digest=digest)
        return {"verification": test["verification"], "stabilized": True,
                "entry": stabilized["entry"], "state": s.runtime.state()}
    except SystemRefusal as exc:
        return {"verification": test["verification"], "stabilized": False,
                "refusal": exc.to_dict(), "passed": passed, "state": s.runtime.state()}


# --------------------------------------------------------------------------
# scenarios
# --------------------------------------------------------------------------


@app.get("/api/scenarios")
async def list_scenarios(request: Request) -> dict[str, Any]:
    s = session_for(request)
    health = await s.relay.health()
    available = {"relay": bool(health.get("available"))}
    return {
        "scenarios": [
            {**sc, "available": available.get(sc["requires"], True) if sc["requires"] else True}
            for sc in scenario_lib.catalog()
        ]
    }


@app.get("/api/scenarios/{scenario_id}/run")
async def run_scenario(request: Request, scenario_id: str, pace: str = "slow"):
    """Stream a scenario step by step as it really executes."""
    s = session_for(request)
    scenario = scenario_lib.SCENARIOS.get(scenario_id)
    if scenario is None:
        raise HTTPException(404, f"unknown scenario: {scenario_id}")

    async def gen():
        try:
            async for message in scenario_lib.run(scenario, s, pace=pace):
                yield f"data: {json.dumps(message)}\n\n"
        except Exception as exc:
            payload = {"type": "failed", "error": f"{type(exc).__name__}: {exc}"}
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------
# frontend
# --------------------------------------------------------------------------

def _frontend_version() -> str:
    """A short hash over the frontend's file mtimes and sizes.

    Assets are served under /a/<version>/, so editing any frontend file changes
    every asset URL. A browser cannot serve a stale stylesheet from cache
    because it has never seen that URL before. Relative ES module imports
    (`./instruments.js`) inherit the versioned prefix automatically, so the
    whole module graph is versioned without touching the JavaScript.
    """
    parts = []
    for f in sorted(FRONTEND.rglob("*")):
        if f.is_file():
            st = f.stat()
            parts.append(f"{f.name}:{int(st.st_mtime)}:{st.st_size}")
    import hashlib

    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:10]


if FRONTEND.is_dir():
    # Kept so an older bookmark or a direct asset link still resolves.
    app.mount("/assets", StaticFiles(directory=FRONTEND), name="assets")

    @app.get("/")
    async def index():
        version = _frontend_version()
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        html = html.replace("/assets/", f"/a/{version}/")
        return HTMLResponse(
            html,
            headers={"Cache-Control": "no-store, must-revalidate", "X-Frontend-Version": version},
        )

    @app.api_route("/a/{version}/{path:path}", methods=["GET", "HEAD"])
    async def versioned_asset(version: str, path: str):
        target = (FRONTEND / path).resolve()
        try:
            target.relative_to(FRONTEND.resolve())
        except ValueError:
            raise HTTPException(403, "path escapes the frontend directory")
        if not target.is_file():
            raise HTTPException(404, path)
        media = {
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".html": "text/html; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        # Safe to cache hard: the URL changes whenever the file does.
        return FileResponse(
            target, media_type=media,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
