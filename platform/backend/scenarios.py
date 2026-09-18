"""Guided scenarios.

A scenario is **input configuration, not playback**. Each step calls the same
adapter method the interface's own controls call, against the same session, and
the real system decides what happens. Nothing here is recorded, replayed or
stubbed.

Each step declares what it *expects* — usually `ok`, sometimes a specific
refusal code. The runner reports what actually happened and whether it matched.
If a step that should be refused is allowed, the scenario says so and keeps
going; it does not quietly present the wrong outcome as the intended one. That
honesty is the whole reason a scenario is safe to put in front of a visitor.

Steps share a `bag` so that ids produced by one step (a thread, an artifact
digest, an agent) are available to the next.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from contract import EventContext, SystemRefusal, acting

Bag = dict[str, Any]
StepFn = Callable[[Any, Bag], Any | Awaitable[Any]]


@dataclass(frozen=True)
class Step:
    """One real call, explained twice.

    `plain` is for someone who does not know the system: what just happened, in
    ordinary language. `technical` is for someone who does: which function ran,
    what it checked, and why the outcome follows. Neither is a summary of the
    other — they are two readings of the same event.
    """

    title: str
    plain: str
    technical: str
    run: StepFn
    expect: str = "ok"           # "ok" | "refused"
    expect_code: str | None = None
    note: str | None = None      # shown with the result, e.g. what to look at
    headline: str | None = None  # the one result key that carries this step's meaning


@dataclass(frozen=True)
class Scenario:
    id: str
    system: str
    title: str
    thesis: str
    steps: tuple[Step, ...] = field(default_factory=tuple)
    requires: str | None = None  # a system that must be available


# --------------------------------------------------------------------------
# SyberRuntime
# --------------------------------------------------------------------------


def _rt_thread(s, bag):
    r = s.runtime.create_thread("Add a billing guard")
    bag["threadId"] = r["entry"]["operation"]["threadId"]
    return {"threadId": bag["threadId"][:16] + "…"}


def _rt_feature(s, bag):
    r = s.runtime.record_feature(
        thread_id=bag["threadId"],
        artifact_name="billing.py",
        content=(
            "def charge(amount_cents):\n"
            "    if amount_cents <= 0:\n"
            '        raise ValueError("amount must be positive")\n'
            "    return amount_cents\n"
        ),
        intent="Add a billing guard",
        generative_mass=2.0,
        blast_radius=1.5,
        criticality=1.0,
    )
    bag["digest"] = r["entry"]["operation"]["outputs"][0]["digest"]
    obligations = [
        oid for oid, o in (r["state"]["debt"]["obligations"] or {}).items()
        if o.get("status") == "open"
    ]
    return {
        "residualDebt": r["state"]["debt"]["totalResidual"],
        "openObligations": len(obligations),
        "artifactDigest": bag["digest"][:16] + "…",
    }


def _rt_stabilize(s, bag):
    r = s.runtime.stabilize(thread_id=bag["threadId"], artifact_digest=bag["digest"])
    return {"stabilized": True, "residualDebt": r["state"]["debt"]["totalResidual"]}


def _rt_test_failing(s, bag):
    r = s.runtime.record_test(
        thread_id=bag["threadId"], artifact_digest=bag["digest"],
        check={"kind": "text_contains", "expected": "refund"},
    )
    v = r["verification"]
    return {"checkPassed": v["passed"], "details": v["details"],
            "dischargedObligations": len(v["discharged_obligations"])}


def _rt_test_passing(s, bag):
    r = s.runtime.record_test(
        thread_id=bag["threadId"], artifact_digest=bag["digest"],
        check={"kind": "text_contains", "expected": "raise ValueError"},
    )
    v = r["verification"]
    return {"checkPassed": v["passed"], "details": v["details"],
            "dischargedObligations": len(v["discharged_obligations"])}


def _rt_merkle(s, bag):
    root = s.runtime.merkle_root()["root"]
    return {"merkleRoot": root[:24] + "…", "replayDeterministic": s.runtime.replay_check()["deterministic"]}


RUNTIME = Scenario(
    id="runtime-fail-closed",
    system="syber_runtime",
    title="Accrue, then refuse",
    thesis=(
        "Generating an artifact creates a debt the runtime will not let you walk away from. "
        "Stabilization is refused until an obligation is actually discharged - and a check "
        "that fails does not discharge anything."
    ),
    steps=(
        Step(
            "Open a thread",
            "Start a new piece of work. Think of it as opening a fresh page in a logbook: "
            "nothing has been claimed yet, and nothing is owed.",
            "Runtime.create_thread appends a ThreadCreate operation to operations.jsonl. Each "
            "entry stores its own hash and the previous entry's, so the log is a chain running "
            "back to the first record.",
            _rt_thread,
        ),
        Step(
            "Record a Feature",
            "Add some code. Producing something is an implicit promise that it works, so the "
            "runtime immediately writes down a debt you now owe.",
            "record_feature stores the artifact in the blob store and appends a Feature "
            "operation. Debt = generative_mass x blast_radius x criticality x the profile accrual "
            "rate, so 2 x 1.5 x 1 x 1.0 = 3.0. The production profile sets floor_required, which "
            "is what makes the obligation blocking rather than advisory.",
            _rt_feature,
            note="Watch the debt ledger fill.",
            headline="residualDebt",
        ),
        Step(
            "Try to stabilize",
            "Try to mark the code as finished. The runtime refuses, because you never showed "
            "that it works.",
            "stabilize() calls state.debt.open_floor_obligations_for_artifact(digest). The result "
            "is non-empty, so it raises StabilizationBlockedError before appending anything. The "
            "refusal happens ahead of the write: no operation enters the log.",
            _rt_stabilize,
            expect="refused", expect_code="StabilizationBlockedError",
            note="The refusal names the obligation and points at runtime.py.",
        ),
        Step(
            "Verify with a check that fails",
            "Run a test that does not match the code. The attempt is written down, but it proves "
            "nothing, so the debt stays exactly where it was.",
            "record_test runs DeterministicVerifier with kind=text_contains against the artifact. "
            "result.passed is False, so discharged_obligations is empty. The Test operation is "
            "still appended - a failed attempt is part of the history, not erased from it.",
            _rt_test_failing,
            note="dischargedObligations stays 0.",
            headline="dischargedObligations",
        ),
        Step(
            "Try to stabilize again",
            "Try to finish again. Still refused: running a test is not the same as passing one.",
            "An identical call to step 3. The obligation status is still open because only a "
            "passing verification calls obligation.discharge(). Recording an attempt never "
            "changes residual_debt.",
            _rt_stabilize,
            expect="refused", expect_code="StabilizationBlockedError",
        ),
        Step(
            "Verify with a check that passes",
            "Run a test that does match the code. Now there is real evidence, and the debt clears.",
            "The same verifier, with an expected substring the artifact actually contains. "
            "result.passed is True, so the obligation is discharged: residual_debt drops to 0.0 "
            "and status becomes discharged. The exact check payload is recorded verbatim, so the "
            "oracle that discharged it stays reconstructable.",
            _rt_test_passing,
            headline="dischargedObligations",
        ),
        Step(
            "Stabilize",
            "Mark it finished. This is the same request that was refused twice - it works now "
            "only because the evidence exists.",
            "stabilize() re-runs the same open_floor_obligations_for_artifact query, which is now "
            "empty, and appends a Stabilize operation referencing the artifact.",
            _rt_stabilize,
            headline="residualDebt",
        ),
        Step(
            "Take the evidence",
            "Everything above went into a log that cannot be quietly edited. This is the proof it "
            "has not been.",
            "merkle_root_hash builds a MerkleHistoryTree over every entry hash. "
            "replay_is_deterministic folds the operation list twice and compares the resulting "
            "RuntimeState dictionaries for equality.",
            _rt_merkle,
            headline="replayDeterministic",
        ),
    ),
)


# --------------------------------------------------------------------------
# Barn
# --------------------------------------------------------------------------


async def _barn_run(s, bag):
    r = await s.barn.create_run(goal="Ship a payments integration", max_active_agents=3,
                                chief_capabilities={"generalist"})
    run = r["run"]
    bag["chief"] = next(iter(run["agents"]))
    bag["goalWork"] = next(iter(run["work_items"]))
    return {"runId": run["id"], "chief": bag["chief"], "maxActiveAgents": run["max_active_agents"]}


async def _barn_work(s, bag):
    r = await s.barn.add_work(
        actor_agent_id=bag["chief"], title="Integrate Stripe webhooks",
        required_capabilities={"payments"}, parent_work_id=bag["goalWork"],
        requires_verification=True,
    )
    bag["work"] = r["work"]["id"]
    return {"workId": bag["work"], "status": r["work"]["status"],
            "requiredCapabilities": r["work"]["required_capabilities"],
            "requiresVerification": r["work"]["requires_verification"]}


async def _barn_specialist(s, bag):
    r = await s.barn.request_specialist(
        requesting_agent_id=bag["chief"], work_id=bag["work"],
        capability="payments", role="Payments specialist",
        reason="chief lacks the payments capability",
    )
    d = r["decision"]
    bag["specialist"] = d["agent_id"]
    return {"outcome": d["outcome"], "reason": d["reason"], "agentId": d["agent_id"]}


async def _barn_resolve(s, bag):
    r = await s.barn.resolve_work(work_id=bag["work"], actor_agent_id=bag["specialist"])
    return {"status": r["work"]["status"]}


async def _barn_artifact(s, bag):
    r = await s.barn.submit_artifact(
        agent_id=bag["specialist"], work_id=bag["work"], kind="code",
        uri="repo://payments/webhooks.py", content_hash="sha256:ab12cd34",
    )
    bag["artifact"] = r["artifact"]["id"]
    return {"artifactId": bag["artifact"], "kind": r["artifact"]["kind"]}


async def _barn_self_verify(s, bag):
    r = await s.barn.record_verification(
        verifier_agent_id=bag["specialist"], artifact_id=bag["artifact"],
        passed=True, evidence="I reviewed my own work and it is fine",
    )
    return {"passed": r["verification"]["passed"]}


async def _barn_independent_verify(s, bag):
    r = await s.barn.record_verification(
        verifier_agent_id=bag["chief"], artifact_id=bag["artifact"],
        passed=True, evidence="reviewed signature handling and retry semantics",
    )
    return {"passed": r["verification"]["passed"], "verifier": bag["chief"]}


async def _barn_audit(s, bag):
    r = await s.barn.audit()
    a = r["audit"]
    return {"events": a["event_count"], "matches": a["matches"],
            "materialized": a["materialized_hash"][:16] + "…",
            "replayed": (a["replayed_hash"] or "")[:16] + "…"}


async def _barn_why(s, bag):
    r = await s.barn.why(bag["specialist"])
    return {"chain": [f"{st['kind']}: {st['label']}" for st in r["explanation"]["steps"]]}


BARN = Scenario(
    id="barn-independence",
    system="barn",
    title="Independence is enforced",
    thesis=(
        "Barn licenses every organizational mutation through a deterministic transition engine. "
        "An agent cannot close its own work, cannot verify its own artifact, and every refusal "
        "has a name."
    ),
    steps=(
        Step(
            "Create a run",
            "Start a project with one lead agent and room for three agents in total.",
            "BarnEngine.create_run appends a run.created BarnEvent and materializes a RunState "
            "holding a Chief agent and a goal WorkItem. max_active_agents caps how many "
            "non-retired agents may exist at once.",
            _barn_run,
        ),
        Step(
            "Add work that needs verification",
            "Add a task needing a skill the lead does not have, and which somebody else has to "
            "check before it can count as done.",
            "add_work appends work.added with required_capabilities={'payments'} and "
            "requires_verification=True. That flag is what later makes "
            "passing_verification_required enforceable rather than advisory.",
            _barn_work,
            headline="requiresVerification",
        ),
        Step(
            "Request a specialist",
            "Ask for someone who can do the job. Nobody suitable exists and there is budget left, "
            "so a new specialist is created.",
            "request_specialist first scans for a non-retired agent holding the capability with "
            "no conflicting work - reuse is attempted before spawn. None matches, and "
            "active_count is below max_active_agents, so it emits specialist.spawned with reason "
            "capability_gap_licensed.",
            _barn_specialist,
            headline="outcome",
        ),
        Step(
            "Try to resolve the work",
            "The specialist tries to declare the task finished. It cannot: it has not actually "
            "produced anything yet.",
            "resolve_work looks for an artifact produced for this work item. There is none, so it "
            "raises TransitionError('artifact_required') before any event is appended.",
            _barn_resolve,
            expect="refused", expect_code="artifact_required",
        ),
        Step(
            "Submit an artifact",
            "The specialist hands in real work.",
            "submit_artifact appends artifact.submitted carrying a uri and content_hash, linked "
            "to both the work item and the producing agent. That producer link is exactly what "
            "the next step checks against.",
            _barn_artifact,
        ),
        Step(
            "Let the producer verify its own artifact",
            "The specialist tries to sign off on its own work. Refused - that would make checking "
            "meaningless.",
            "record_verification compares verifier_agent_id against the artifact producer. They "
            "are the same agent, so it raises TransitionError('independent_verifier_required'). "
            "Independence is a hard invariant of the engine, not a configurable policy.",
            _barn_self_verify,
            expect="refused", expect_code="independent_verifier_required",
        ),
        Step(
            "Try to resolve again",
            "Try to finish again. There is something to show now, but nobody has checked it.",
            "resolve_work finds the artifact but no passing Verification from a different agent, "
            "so it raises TransitionError('passing_verification_required').",
            _barn_resolve,
            expect="refused", expect_code="passing_verification_required",
        ),
        Step(
            "Have the chief verify it",
            "A different agent reviews the work and signs off on it.",
            "record_verification with verifier_agent_id set to the chief. Producer and verifier "
            "differ, so the independence check passes and verification.recorded is appended with "
            "passed=True.",
            _barn_independent_verify,
            headline="passed",
        ),
        Step(
            "Resolve the work",
            "Finish the task. Same request as step 4, and this time it goes through.",
            "resolve_work re-runs the identical preconditions, now satisfied, and appends "
            "work.resolved. The WorkItem status becomes resolved.",
            _barn_resolve,
            headline="status",
        ),
        Step(
            "Audit by replay",
            "Check that the running state matches the recorded history - that nothing changed "
            "behind the log's back.",
            "audit_run hashes the materialized RunState, then calls replay_run(events) to rebuild "
            "state from zero and hashes that. Store version counters are excluded and collections "
            "are order-normalized, so the comparison is over semantics rather than storage order.",
            _barn_audit,
            headline="matches",
        ),
        Step(
            "Ask why the specialist exists",
            "Ask the system to justify a decision it made earlier. It works the answer out from "
            "the record rather than reading back a stored note.",
            "why_agent_exists walks agent.spawned_because_work_id up the parent_work_id chain, "
            "then scans the event ledger for the specialist.spawned event naming that agent. No "
            "explanation is persisted anywhere; the chain is derived on demand.",
            _barn_why,
        ),
    ),
)


# --------------------------------------------------------------------------
# Bough
# --------------------------------------------------------------------------


def _bough_bits(s, bag):
    r = s.bough.compile("bits", {"n": 4})
    rep = r["report"]
    return {"situations": rep["situation_count"], "uncoalesced": rep["uncoalesced_node_count"],
            "compressionRatio": rep["compression_ratio"], "edges": rep["edge_count"],
            "truncated": rep["truncated"]}


def _bough_reach(s, bag):
    r = s.bough.reach("all-on")
    return {"reach": r["mass"], "distinctPaths": r["paths"]}


def _bough_ontology(s, bag):
    r = s.bough.compile("ontology", {"copies": 1})
    rep = r["report"]
    return {"situations": rep["situation_count"], "uncoalesced": rep["uncoalesced_node_count"],
            "compressionRatio": rep["compression_ratio"]}


def _bough_reach_cyclic(s, bag):
    r = s.bough.reach("up")
    return {"reach": r["mass"]}


def _bough_machine(s, bag):
    s.bough.compile("machine")
    r = s.bough.optimal_policy()
    return {"rootAction": r["rootAction"][0] if r["rootAction"] else None,
            "rootValue": r["rootValue"]}


BOUGH = Scenario(
    id="bough-exact-or-refuse",
    system="bough",
    title="Exact, or refuse",
    thesis=(
        "Bough compiles a rewrite system into a coalesced jump chain and answers questions about "
        "it exactly. When the structure does not support an exact answer, it refuses instead of "
        "approximating - which is the more interesting half."
    ),
    steps=(
        Step(
            "Compile four irreversible bits",
            "Four switches, each of which can be flipped once. The order you flip them in does "
            "not matter, so many different histories end up being the same situation.",
            "expand() does a breadth-first walk of the embedded jump chain, coalescing states by "
            "situation_signature over the graph, the boundary and the rule repertoire hash. 33 "
            "uncoalesced nodes collapse into 16 situations: a ratio of 2.0625.",
            _bough_bits,
            note="compressionRatio is 33/16 = 2.0625.",
            headline="compressionRatio",
        ),
        Step(
            "Ask for reach(all-on)",
            "What is the chance every switch ends up on, and how many different routes get there?",
            "reach() first asserts the automaton is neither truncated nor cyclic, then folds "
            "probability mass backwards from the labelled terminals. Every bit eventually flips, "
            "so arrival is certain: mass 1.0 over 24 distinct paths.",
            _bough_reach,
            headline="reach",
        ),
        Step(
            "Compile the ontology fragment",
            "Routes between sites that can fail and then be repaired. Because repair undoes a "
            "failure, the system can come back to a state it was already in.",
            "The same expand() call over a different rule repertoire. fail deletes an Available "
            "hyperedge; repair recreates it, returning to an earlier signature. That returning "
            "edge is what makes the automaton cyclic rather than a DAG.",
            _bough_ontology,
            headline="compressionRatio",
        ),
        Step(
            "Ask the same question of it",
            "Ask the same question as before. Because the system can loop indefinitely there is "
            "no finite answer, so it refuses rather than guessing.",
            "reach() runs _assert_dag, finds a back edge during the walk and raises "
            "BoughRefusal('CYCLIC_AUTOMATON'). It does not truncate the expansion and report a "
            "partial mass as though it were exact.",
            _bough_reach_cyclic,
            expect="refused", expect_code="CYCLIC_AUTOMATON",
            note="This refusal is the claim: exact mode never approximates.",
        ),
        Step(
            "Solve a decision problem",
            "A choice between protecting a machine or ignoring it. Work out which is worth more, "
            "given what might happen afterwards.",
            "optimal_policy walks the automaton in postorder, taking a maximum over decision edges "
            "and an expectation over chance edges. protect is worth 1.0 against 0.5 for ignore, "
            "so it is selected at the root.",
            _bough_machine,
            note="protect is worth 1.0 against 0.5 for ignore.",
            headline="rootAction",
        ),
    ),
)


# --------------------------------------------------------------------------
# OSAHR
# --------------------------------------------------------------------------


def _osahr_model(s, bag):
    m = s.bough.osahr_model("ontology", {"copies": 1})
    return {"schema": m["schemaId"], "vertexTypes": m["vertexTypes"],
            "hyperedgeTypes": m["edgeTypes"], "vertices": len(m["vertices"]),
            "hyperedges": len(m["edges"]), "rules": len(m["rules"])}


def _osahr_rules(s, bag):
    m = s.bough.osahr_model("ontology", {"copies": 1})
    return {"rules": [
        {"id": r["eventId"], "kind": r["kind"], "hazard": r["hazard"],
         "deletesHyperedges": len(r["left"]["edges"]) - len(r["right"]["edges"])}
        for r in m["rules"]
    ]}


def _osahr_agree(s, bag):
    r = s.bough.osahr_agreement("race", {"rate_a": 2.0, "rate_b": 1.0}, replicates=96)
    return {"exact": r["exact"],
            "schedulers": [
                {"scheduler": x["scheduler"], "empirical": round(x["empirical"], 4),
                 "withinRadius": x["within_radius"]}
                for x in r["schedulers"]
            ]}


OSAHR = Scenario(
    id="osahr-two-ways",
    system="osahr",
    title="Two ways to the same number",
    thesis=(
        "OSAHR is a stochastic rewrite kernel over a typed directed hypergraph. Bough derives a "
        "first-passage probability analytically; OSAHR reaches it by simulation, three "
        "independent ways. Agreement is evidence the compiler and the kernel mean the same thing "
        "by 'probability'."
    ),
    steps=(
        Step(
            "Load the hypergraph",
            "Look at the structure the simulation runs over: things, and connections between them "
            "that can join more than two at a time.",
            "Read directly off osahr.Model: Site and Route vertices typed by a Schema, plus "
            "Available hyperedges whose tail and head carry named role incidences rather than a "
            "plain pair of endpoints.",
            _osahr_model,
            headline="hyperedges",
        ),
        Step(
            "Read the rewrite rules",
            "Each rule is a find-and-replace on the structure: match this shape, swap it for that "
            "one, at some rate.",
            "Rule.left is a PatternGraph, Rule.right a TemplateGraph, and hazard is the rate "
            "expression. fail matches Route{up=true} together with its Available edge and "
            "produces Route{up=false} without it; repair is the inverse.",
            _osahr_rules,
            note="deletesHyperedges is +1 for fail, -1 for repair.",
        ),
        Step(
            "Run the cross-check",
            "One method works the answer out exactly. Another rolls dice many times. If they "
            "agree, both are probably right.",
            "agree_first_passage drives osahr.analysis.run_ensemble under direct_ssa, "
            "next_reaction and thinning for 96 replicates each, comparing empirical first-passage "
            "frequency against Bough's exact 2/3 within a Hoeffding radius at alpha 1e-6.",
            _osahr_agree,
            note="direct_ssa, next_reaction and thinning are independent implementations.",
            headline="exact",
        ),
    ),
)


# --------------------------------------------------------------------------
# Relay
# --------------------------------------------------------------------------

_OVERCLAIM = (
    "I shipped 4 production services at Acme. I also led a team of 12 engineers "
    "and hold a PhD in distributed systems."
)

_PACKET = {
    "schema": "relay.packet.v1",
    "job": {
        "id": "job_demo_001", "key": "greenhouse:acme:4455",
        "name": "Senior Platform Engineer",
        "url": "https://job-boards.greenhouse.io/acme/jobs/4455",
        "version": 3, "status": "Held",
    },
    "facts": "Shipped 4 production services at Acme.\nLed the migration to Kubernetes across 3 teams.",
    "draft": "",
}


async def _relay_identity(s, bag):
    r = await s.relay.job_key(
        "https://job-boards.greenhouse.io/acme/jobs/4455?utm_campaign=spring&gh_src=abc"
    )
    return {"canonicalKey": r["result"]["key"]}


async def _relay_mismatch(s, bag):
    bad = {**_PACKET, "job": {**_PACKET["job"], "key": "greenhouse:other:9999"}}
    r = await s.relay.handoff_prompt(bad, "chatgpt")
    return {"promptChars": len(r["result"]["prompt"])}


async def _relay_prompt(s, bag):
    r = await s.relay.handoff_prompt(_PACKET, "chatgpt")
    prompt = r["result"]["prompt"]
    bag["prompt"] = prompt
    return {"promptChars": len(prompt),
            "mentionsUntrusted": "untrusted source data" in prompt,
            "containsOnlySelectedJob": _PACKET["job"]["key"] in prompt}


async def _relay_handoff(s, bag):
    r = await s.relay.handoff(packet=_PACKET, provider="chatgpt", draft_override=_OVERCLAIM)
    bag["draft"] = r["draft"]
    return {"schema": r["draft"]["schema"], "jobVersion": r["draft"]["job"]["version"],
            "reviewRequired": r["reviewRequired"],
            "unsupportedClaims": r["gate"]["unsupported"]}


async def _relay_stale(s, bag):
    stale = {**_PACKET, "job": {**_PACKET["job"], "version": 0}}
    r = await s.relay.handoff_prompt(stale, "chatgpt")
    return {"promptChars": len(r["result"]["prompt"])}


RELAY = Scenario(
    id="relay-handoff",
    system="relay",
    title="The handoff is the object",
    thesis=(
        "The interesting thing is not the text a model writes - it is the structure around it. "
        "Bounded context leaves, and whatever comes back must survive identity, version and "
        "claim-grounding checks before a human is even asked to look at it."
    ),
    requires="relay",
    steps=(
        Step(
            "Canonicalize the posting",
            "Two links to the same job should count as the same job, even when one of them has "
            "tracking junk stuck on the end.",
            "lib/domain.ts jobKey resolves known Greenhouse aliases and strips tracking "
            "parameters, returning a stable identity. Postings on different job boards are "
            "deliberately not deduplicated against one another.",
            _relay_identity,
            headline="canonicalKey",
        ),
        Step(
            "Try a packet whose key does not match its URL",
            "Before anything is sent anywhere, check the request is internally consistent. This "
            "one is not.",
            "validatePacket runs packetKeyMatches(job.url, job.key) and throws, because the "
            "canonical key derived from the URL differs from the key the packet declares.",
            _relay_mismatch,
            expect="refused",
        ),
        Step(
            "Build the packet that would leave",
            "Assemble exactly what an outside assistant is given - and nothing else.",
            "assistantPrompt serializes only the selected job, the cited facts and the current "
            "draft, and states that the JSON is untrusted source data rather than instructions. "
            "This string is the entire trust boundary.",
            _relay_prompt,
            note="This is the entire trust boundary, in one string.",
            headline="promptChars",
        ),
        Step(
            "Hand off a draft that over-claims",
            "A draft comes back containing things nobody ever verified. The system finds them.",
            "assistantResult validates schema, job identity and version first. Then "
            "unsupportedClaims splits the body into sentences, keeps the ones that read as "
            "claims, and reports any whose vocabulary and numbers are not covered by a cited "
            "verified fact.",
            _relay_handoff,
            note="The PhD and the team of 12 appear in no verified fact.",
            headline="reviewRequired",
        ),
        Step(
            "Try to hand off against a stale version",
            "Use an out-of-date copy of the job. Refused, so an old draft cannot be applied to a "
            "job that has since moved on.",
            "selectedPacket requires job.version to be at least 1 and the identity to be "
            "consistent. The stale packet fails that gate before any content is produced at all.",
            _relay_stale,
            expect="refused",
        ),
    ),
)


# --------------------------------------------------------------------------
# Cross-system seam
# --------------------------------------------------------------------------


async def _cross_handoff(s, bag):
    r = await s.relay.handoff(packet=_PACKET, provider="chatgpt", draft_override=_OVERCLAIM)
    bag["draft"] = r["draft"]
    return {"schema": r["draft"]["schema"], "reviewRequired": r["reviewRequired"],
            "unsupportedClaims": r["gate"]["unsupported"]}


def _cross_record(s, bag):
    draft = bag["draft"]
    job = draft.get("job") or {}
    t = s.runtime.create_thread(f"Review Relay draft for {job.get('name')}")
    bag["threadId"] = t["entry"]["operation"]["threadId"]
    f = s.runtime.record_feature(
        thread_id=bag["threadId"],
        artifact_name=f"relay-draft-{job.get('id')}.txt",
        content=draft["draft"],
        intent=f"Relay handoff draft (reviewRequired={draft.get('reviewRequired')})",
        generative_mass=1.0, blast_radius=1.0, criticality=1.0,
    )
    bag["digest"] = f["entry"]["operation"]["outputs"][0]["digest"]
    return {"threadId": bag["threadId"][:16] + "…",
            "artifactDigest": bag["digest"][:16] + "…",
            "residualDebt": f["state"]["debt"]["totalResidual"]}


def _cross_stabilize(s, bag):
    r = s.runtime.stabilize(thread_id=bag["threadId"], artifact_digest=bag["digest"])
    return {"stabilized": True, "residualDebt": r["state"]["debt"]["totalResidual"]}


def _cross_review(s, bag):
    r = s.runtime.record_test(
        thread_id=bag["threadId"], artifact_digest=bag["digest"],
        check={"kind": "text_contains", "expected": "Acme"},
    )
    v = r["verification"]
    return {"checkPassed": v["passed"], "dischargedObligations": len(v["discharged_obligations"])}


CROSS = Scenario(
    id="cross-relay-runtime",
    system="cross",
    title="A draft becomes an obligation",
    thesis=(
        "Relay marks a draft reviewRequired. In SyberRuntime's grammar that is exactly an "
        "unverified artifact. Neither system was modified to make this fit - their review "
        "semantics already compose, so one system produces an object the other already knows "
        "how to refuse."
    ),
    requires="relay",
    steps=(
        Step(
            "Produce a draft in Relay",
            "Generate the same draft as before. The claim gate flags the same unsupported claims.",
            "assistantResult returns a relay.draft.v1 marked reviewRequired=true, and "
            "unsupportedClaims reports the sentences the cited facts do not cover.",
            _cross_handoff,
            headline="reviewRequired",
        ),
        Step(
            "Record it in SyberRuntime as a Feature",
            "Hand that draft to a completely different system, which has never heard of Relay.",
            "The draft text becomes an artifact via record_feature. It accrues verification debt "
            "and opens a floor-rigor obligation, exactly as any other generated artifact would - "
            "there is no special case for drafts.",
            _cross_record,
            headline="residualDebt",
        ),
        Step(
            "Try to stabilize it before review",
            "Relay said this needs a human review. The other system refuses to finalize it - "
            "for its own, unrelated reasons.",
            "stabilize() raises StabilizationBlockedError because the floor obligation is open. "
            "SyberRuntime is not reading Relay's reviewRequired flag; the two systems arrive at "
            "the same answer through independent rules.",
            _cross_stabilize,
            expect="refused", expect_code="StabilizationBlockedError",
            note="Two systems, one consistent answer, no shared code.",
        ),
        Step(
            "Perform the review as a deterministic check",
            "Carry out the review as an actual check against the draft.",
            "record_test runs the verifier against the artifact. It passes, so the obligation is "
            "discharged and residual debt falls to zero.",
            _cross_review,
            headline="dischargedObligations",
        ),
        Step(
            "Stabilize",
            "Now the draft can be committed - and the log records why it was allowed to be.",
            "The same stabilize() call as step 3, now succeeding, appending a Stabilize operation "
            "whose provenance chain leads back to the discharging Test.",
            _cross_stabilize,
            headline="residualDebt",
        ),
    ),
)


SCENARIOS: dict[str, Scenario] = {
    sc.id: sc for sc in (RUNTIME, BARN, BOUGH, OSAHR, RELAY, CROSS)
}


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": sc.id, "system": sc.system, "title": sc.title, "thesis": sc.thesis,
            "stepCount": len(sc.steps), "requires": sc.requires,
            "steps": [{"title": st.title, "expect": st.expect,
                       "expectCode": st.expect_code, "headline": st.headline,
                       "plain": st.plain, "technical": st.technical}
                      for st in sc.steps],
        }
        for sc in SCENARIOS.values()
    ]


PACE = {           # (reading multiplier, pause after a result)
    "slow": (1.0, 2.6),
    "normal": (0.55, 1.4),
    "fast": (0.12, 0.25),
}


def _reading_seconds(step: Step, multiplier: float) -> float:
    """Time to read a step's two explanations before its call runs.

    Scaled to the actual text rather than a flat delay, so a dense step is not
    gone before it can be read and a short one does not stall.
    """
    chars = len(step.plain) + len(step.technical)
    return max(2.0, min(9.0, chars / 48.0)) * multiplier


async def run(scenario: Scenario, session: Any, pace: str = "slow"):
    """Execute a scenario step by step, yielding a record per step.

    Every step runs inside an `acting(...)` context, so the events the adapters
    emit are attributed to that step and to the scenario run.

    The pauses are here rather than in the transport because they are part of
    the presentation: a step is shown, given time to be read, and only then
    executed — so what appears on screen is still the moment it happened.
    """
    multiplier, result_pause = PACE.get(pace, PACE["slow"])
    run_id = f"scn_{uuid.uuid4().hex[:12]}"
    bag: Bag = {}

    yield {"type": "start", "runId": run_id, "scenario": scenario.id,
           "title": scenario.title, "thesis": scenario.thesis,
           "stepCount": len(scenario.steps)}

    for index, step in enumerate(scenario.steps):
        step_id = f"{run_id}.{index + 1}"
        yield {"type": "step_start", "runId": run_id, "index": index,
               "stepId": step_id, "title": step.title,
               "plain": step.plain, "technical": step.technical,
               "expect": step.expect, "expectCode": step.expect_code, "note": step.note}
        await asyncio.sleep(_reading_seconds(step, multiplier))

        record: dict[str, Any] = {
            "type": "step_end", "runId": run_id, "index": index, "stepId": step_id,
            "title": step.title, "expect": step.expect, "expectCode": step.expect_code,
            "headline": step.headline,
        }

        with acting(EventContext(operation_id=step_id, label=step.title,
                                 parent_id=run_id, kind="scenario_step")):
            try:
                result = step.run(session, bag)
                if inspect.isawaitable(result):
                    result = await result
                record["outcome"] = "ok"
                record["result"] = result
            except SystemRefusal as refusal:
                record["outcome"] = "refused"
                record["refusal"] = refusal.to_dict()
            except Exception as exc:  # a genuine failure, shown as one
                record["outcome"] = "error"
                record["error"] = {"type": type(exc).__name__, "message": str(exc)}

        record["matched"] = _matched(step, record)
        record["verdict"] = _verdict(step, record)
        yield record
        await asyncio.sleep(result_pause)

        if record["outcome"] == "error":
            yield {"type": "aborted", "runId": run_id, "index": index,
                   "reason": "a step failed outright; the remaining steps were not run"}
            return

    yield {"type": "end", "runId": run_id, "scenario": scenario.id}


def _matched(step: Step, record: dict[str, Any]) -> bool:
    if record["outcome"] == "error":
        return False
    if step.expect == "refused":
        if record["outcome"] != "refused":
            return False
        if step.expect_code is None:
            return True
        refusal = record.get("refusal") or {}
        return step.expect_code in {refusal.get("code"), refusal.get("kind")}
    return record["outcome"] == "ok"


def _verdict(step: Step, record: dict[str, Any]) -> str:
    """Plain language about whether the system did what the scenario said it would."""
    if record["matched"]:
        if step.expect == "refused":
            return "Refused, as the scenario said it would be."
        return "Completed."
    if record["outcome"] == "error":
        return "This step failed outright. The scenario stopped here rather than continuing."
    if step.expect == "refused" and record["outcome"] == "ok":
        return (
            "UNEXPECTED: the scenario expected a refusal and the system allowed it. "
            "The scenario is wrong, or the system changed."
        )
    if step.expect == "ok" and record["outcome"] == "refused":
        return (
            "UNEXPECTED: the scenario expected this to succeed and the system refused it. "
            "The refusal is shown as-is."
        )
    refusal = (record.get("refusal") or {}).get("code")
    return f"UNEXPECTED: expected refusal {step.expect_code}, got {refusal}."
