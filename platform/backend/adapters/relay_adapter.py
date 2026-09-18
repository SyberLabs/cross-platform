"""Adapter: Relay.

Invocation: a Node 24 sidecar (`platform/relay-sidecar/server.mjs`) imports the
real `lib/*.ts` modules using Node's native type stripping and exposes them over
loopback JSON HTTP. Relay requires Node >= 24 and is written in TypeScript, so
this is the least invasive way to run its actual code: no transpile step, no
vendoring, no reimplementation.

Provenance is reported by the sidecar, which resolves each module's real path
before answering. This adapter passes that through unchanged.

The one place a model is involved is `handoff`: Relay builds the bounded prompt,
an external assistant drafts, and Relay then re-validates the returned draft.
The model never writes Relay state and never decides acceptance.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from contract import EventSink, Provenance, SyberEvent, SystemRefusal

SYSTEM = "relay"


class RelayUnavailable(RuntimeError):
    """The sidecar is not reachable. Surfaced to the UI as a real dependency failure."""


class RelayAdapter:
    def __init__(self, sink: EventSink, session_id: str, base_url: str) -> None:
        self.sink = sink
        self.session_id = session_id
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30.0)

    async def health(self) -> dict[str, Any]:
        try:
            r = await self._client.get(f"{self.base_url}/health")
            r.raise_for_status()
            return {"available": True, **r.json()}
        except Exception as exc:
            return {"available": False, "error": f"{type(exc).__name__}: {exc}"}

    async def call(
        self,
        handler: str,
        payload: dict[str, Any],
        *,
        event_type: str,
        label: str,
        evidence: Any = None,
    ) -> dict[str, Any]:
        """Invoke one upstream Relay symbol through the sidecar and record it."""
        try:
            response = await self._client.post(f"{self.base_url}/{handler}", json=payload)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            prov = Provenance.external(
                SYSTEM, module="platform/relay-sidecar", symbol=handler, execution="node 24 sidecar"
            ).to_dict()
            self.sink.emit(
                SyberEvent(
                    system=SYSTEM,
                    sessionId=self.session_id,
                    eventType=event_type,
                    label=label,
                    status="error",
                    input=_trim(payload),
                    provenance=prov,
                    error={"type": type(exc).__name__, "message": str(exc)},
                )
            )
            raise RelayUnavailable(
                f"Relay sidecar unreachable at {self.base_url}: {type(exc).__name__}: {exc}"
            ) from exc

        prov = dict(body.get("provenance") or {})
        prov.setdefault("system", SYSTEM)

        if not body.get("ok", False):
            err = body.get("error") or {}
            event = self.sink.emit(
                SyberEvent(
                    system=SYSTEM,
                    sessionId=self.session_id,
                    eventType=event_type,
                    label=label,
                    status="refused",
                    durationMs=body.get("durationMs"),
                    input=_trim(payload),
                    provenance=prov,
                    error={
                        "type": err.get("type", "Error"),
                        "message": err.get("message", "refused"),
                        "refusalCode": None,
                    },
                )
            )
            raise SystemRefusal(
                system=SYSTEM,
                kind=err.get("type", "Error"),
                message=err.get("message", "refused"),
                code=None,
                provenance=prov,
                event=event,
            )

        result = body.get("result")
        event = self.sink.emit(
            SyberEvent(
                system=SYSTEM,
                sessionId=self.session_id,
                eventType=event_type,
                label=label,
                status="ok",
                durationMs=body.get("durationMs"),
                input=_trim(payload),
                output=_trim(result),
                evidence=evidence,
                provenance=prov,
            )
        )
        return {"result": result, "provenance": prov, "eventSeq": event.seq}

    # -- individual capabilities -------------------------------------------

    async def job_key(self, url: str, fallback: str = "fallback") -> dict[str, Any]:
        return await self.call(
            "job-key",
            {"url": url, "fallback": fallback},
            event_type="relay.job_key",
            label="canonicalize posting identity",
        )

    async def requirements(self, text: str) -> dict[str, Any]:
        return await self.call(
            "requirements",
            {"text": text},
            event_type="relay.requirements",
            label="extract requirements",
        )

    async def unsupported_claims(self, body: str, facts: list[dict]) -> dict[str, Any]:
        return await self.call(
            "unsupported-claims",
            {"body": body, "facts": facts},
            event_type="relay.claim_gate",
            label="draft-log claim gate",
        )

    async def planning(self, candidates: list[dict], budget_minutes: int = 90) -> dict[str, Any]:
        return await self.call(
            "planning",
            {"candidates": candidates, "budgetMinutes": budget_minutes},
            event_type="relay.planning",
            label="portfolio selection",
        )

    async def validate_packet(self, packet: dict) -> dict[str, Any]:
        return await self.call(
            "validate-packet",
            {"packet": packet},
            event_type="relay.validate_packet",
            label="validate relay.packet.v1",
        )

    async def handoff_prompt(
        self, packet: dict, provider: str = "chatgpt", draft_only: bool = False, context: dict | None = None
    ) -> dict[str, Any]:
        return await self.call(
            "handoff-prompt",
            {"packet": packet, "provider": provider, "draftOnly": draft_only, "context": context or {}},
            event_type="relay.handoff_prompt",
            label="build bounded handoff prompt",
        )

    async def handoff_result(self, packet: dict, draft: str, provider: str = "chatgpt") -> dict[str, Any]:
        return await self.call(
            "handoff-result",
            {"packet": packet, "draft": draft, "provider": provider},
            event_type="relay.handoff_result",
            label="validate returned draft",
        )

    # -- the full handoff, including the one model call --------------------

    async def handoff(
        self,
        *,
        packet: dict,
        provider: str = "chatgpt",
        context: dict | None = None,
        live: bool = False,
        draft_override: str | None = None,
    ) -> dict[str, Any]:
        """Relay's explicit handoff, end to end.

        1. Relay bounds the context and writes the prompt.
        2. An external assistant drafts (live model call, or a supplied draft).
        3. Relay re-validates the draft against job identity and version.
        4. Relay's claim gate reports which sentences are not grounded.

        Steps 1, 3 and 4 are upstream Relay code. Step 2 is the only external
        actor, and it is not permitted to write state or grant acceptance.
        """
        prompt_res = await self.handoff_prompt(packet, provider, False, context)
        prompt = prompt_res["result"]["prompt"]

        if draft_override is not None:
            draft = draft_override
            source = {"kind": "supplied", "detail": "draft supplied by operator"}
        elif live:
            draft, source = await self._infer(prompt)
        else:
            return {
                "stage": "prompt",
                "prompt": prompt,
                "promptProvenance": prompt_res["provenance"],
                "note": "No draft requested. Enable live inference or supply a draft to continue.",
            }

        result_res = await self.handoff_result(packet, draft, provider)
        relay_draft = result_res["result"]["result"]

        facts = _facts_from_packet(packet)
        gate = await self.unsupported_claims(relay_draft["draft"], facts)

        return {
            "stage": "reviewed",
            "prompt": prompt,
            "promptProvenance": prompt_res["provenance"],
            "assistant": source,
            "draft": relay_draft,
            "draftProvenance": result_res["provenance"],
            "gate": gate["result"],
            "gateProvenance": gate["provenance"],
            "reviewRequired": relay_draft.get("reviewRequired", True),
        }

    async def _infer(self, prompt: str) -> tuple[str, dict[str, Any]]:
        """One deliberate model call. Bounded, non-polling, explicitly triggered."""
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RelayUnavailable(
                "GOOGLE_API_KEY is not set. Live inference is unavailable; "
                "supply a draft instead to exercise the rest of the handoff."
            )
        model = os.environ.get("RELAY_DEMO_MODEL", "gemini-3.6-flash")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={api_key}"
        )
        event = self.sink.emit(
            SyberEvent(
                system=SYSTEM,
                sessionId=self.session_id,
                eventType="relay.assistant_call",
                label=f"external assistant ({model})",
                status="ok",
                input={"promptChars": len(prompt), "model": model},
                provenance=Provenance.external(
                    SYSTEM,
                    module="(external)",
                    symbol=model,
                    execution="live HTTPS call to Google Generative Language API",
                ).to_dict(),
                metadata={"boundary": "context leaves Relay here"},
            )
        )
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                url,
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1200},
                },
            )
        if response.status_code != 200:
            raise RelayUnavailable(
                f"Assistant returned HTTP {response.status_code}. No draft was produced. "
                f"{response.text[:200]}"
            )
        data = response.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise RelayUnavailable(f"Assistant returned no usable candidate: {data}") from exc

        draft = _extract_draft(text)
        event.output = {"responseChars": len(text), "extractedDraftChars": len(draft)}
        return draft, {"kind": "live", "model": model, "raw": text[:4000]}

    async def aclose(self) -> None:
        await self._client.aclose()


def _extract_draft(text: str) -> str:
    """Pull the draft out of the assistant's reply.

    Relay's prompt demands a single JSON object. If the assistant complies we
    read `draft` from it; if it does not, the raw text is passed through so that
    Relay's own validator is the thing that accepts or rejects it — this adapter
    does not silently repair a malformed response.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = [ln for ln in stripped.splitlines() if not ln.strip().startswith("```")]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(parsed, dict):
        if isinstance(parsed.get("draft"), str):
            return parsed["draft"].strip()
        inner = parsed.get("result")
        if isinstance(inner, dict) and isinstance(inner.get("draft"), str):
            return inner["draft"].strip()
    return stripped


def _facts_from_packet(packet: dict) -> list[dict]:
    """Turn the packet's free-text facts block into the Fact rows the gate takes.

    Relay stores cited facts as text in a packet; `unsupportedClaims` wants Fact
    objects. Splitting on lines is a transport detail, not domain logic: the
    grounding decision itself is entirely `lib/profile.ts`.
    """
    raw = str(packet.get("facts") or "")
    rows = []
    for i, line in enumerate(raw.splitlines()):
        claim = line.strip().lstrip("-*").strip()
        if not claim:
            continue
        rows.append(
            {
                "id": f"packet-fact-{i}",
                "claim": claim,
                "status": "Verified",
                "tag": "detail",
                "confidence": "high",
                "expires": None,
            }
        )
    return rows


def _trim(value: Any, limit: int = 6000) -> Any:
    try:
        encoded = json.dumps(value)
    except Exception:
        return repr(value)[:limit]
    if len(encoded) <= limit:
        return value
    return {"_truncated": True, "preview": encoded[:limit]}
