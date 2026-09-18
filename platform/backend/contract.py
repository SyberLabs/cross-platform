"""The shared observability contract.

Every adapter emits `SyberEvent`s. The contract is deliberately thin: it carries
enough structure for a common timeline and inspector, and keeps the untouched
system-specific payload in `output` / `raw` so nothing is flattened away.

Provenance is *derived*, not declared. `Provenance.of()` introspects the real
callable an adapter is about to invoke and reads its module file and line number
off the function object itself. An adapter cannot therefore claim that Bough
computed something while actually calling its own code: the recorded path is
whatever `inspect` says the executed function's source file is, resolved
relative to the repository checkout it lives in.
"""

from __future__ import annotations

import contextlib
import contextvars
import inspect
import itertools
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

SYSTEMS_ROOT = Path(__file__).resolve().parents[2] / "systems"

# Which checkout each system's code lives in. Used only to turn an absolute
# source path back into a repo-relative one for display.
_REPO_ROOTS: dict[str, Path] = {
    "syber_runtime": SYSTEMS_ROOT / "syber_runtime",
    "barn": SYSTEMS_ROOT / "bough_and_barn" / "barn",
    "bough": SYSTEMS_ROOT / "bough_and_barn" / "bough",
    "osahr": SYSTEMS_ROOT / "osahr",
    "relay": SYSTEMS_ROOT / "relay",
}

_seq = itertools.count(1)


@dataclass(frozen=True)
class EventContext:
    """The user-initiated action an event belongs to.

    `operation_id` groups every event caused by one action — one HTTP request,
    or one scenario step. `parent_id` is the enclosing scenario run when there
    is one, giving the stream two levels: scenario -> step -> events.

    This is set once, at the edge, and read by `EventSink.emit`. Adapters do not
    have to thread it through, and no adapter can forget to.
    """

    operation_id: str
    label: str
    parent_id: str | None = None
    kind: str = "request"  # request | scenario_step


_context: contextvars.ContextVar[EventContext | None] = contextvars.ContextVar(
    "syber_event_context", default=None
)


def current_context() -> EventContext | None:
    return _context.get()


@contextlib.contextmanager
def acting(context: EventContext):
    """Attribute every event emitted inside this block to one action."""
    token = _context.set(context)
    try:
        yield context
    finally:
        _context.reset(token)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class Provenance:
    """Where a demonstrated behaviour actually came from."""

    system: str
    module: str | None = None
    symbol: str | None = None
    line: int | None = None
    execution: str = "in-process import"
    repo_relative: bool = True

    @classmethod
    def of(cls, system: str, fn: Callable[..., Any], *, execution: str = "in-process import") -> "Provenance":
        """Derive provenance by introspecting the callable that will run."""
        target = inspect.unwrap(fn)
        module_path: str | None = None
        line: int | None = None
        repo_relative = False
        try:
            source_file = inspect.getsourcefile(target) or inspect.getfile(target)
        except TypeError:
            source_file = None
        if source_file:
            resolved = Path(source_file).resolve()
            root = _REPO_ROOTS.get(system)
            if root is not None:
                try:
                    module_path = resolved.relative_to(root.resolve()).as_posix()
                    repo_relative = True
                except ValueError:
                    module_path = resolved.as_posix()
            else:
                module_path = resolved.as_posix()
        try:
            _, line = inspect.getsourcelines(target)
        except (OSError, TypeError):
            line = None
        symbol = getattr(target, "__qualname__", getattr(target, "__name__", None))
        return cls(
            system=system,
            module=module_path,
            symbol=symbol,
            line=line,
            execution=execution,
            repo_relative=repo_relative,
        )

    @classmethod
    def external(cls, system: str, *, module: str, symbol: str, execution: str) -> "Provenance":
        """Provenance for code running outside this Python process.

        Used by the Relay adapter, whose real modules execute in a Node 24
        sidecar. The sidecar reports its own resolved source path back, so the
        value is still observed rather than asserted here.
        """
        return cls(
            system=system,
            module=module,
            symbol=symbol,
            line=None,
            execution=execution,
            repo_relative=not module.startswith("/") and ":" not in module[:3],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SyberEvent:
    system: str
    eventType: str
    timestamp: str = field(default_factory=utc_now)
    seq: int = field(default_factory=lambda: next(_seq))
    sessionId: str | None = None
    operationId: str | None = None
    parentId: str | None = None
    actionLabel: str | None = None
    actionKind: str | None = None
    label: str | None = None
    status: str = "ok"          # ok | refused | error
    durationMs: float | None = None
    input: Any = None
    output: Any = None
    stateBefore: Any = None
    stateAfter: Any = None
    evidence: Any = None
    provenance: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventSink:
    """Per-session ring of emitted events, with subscriber fan-out."""

    def __init__(self, limit: int = 2000) -> None:
        self._events: list[SyberEvent] = []
        self._limit = limit
        self._subscribers: list[Any] = []

    def emit(self, event: SyberEvent) -> SyberEvent:
        # Fill causal attribution here rather than in every adapter, so an
        # event cannot be emitted without it.
        ctx = current_context()
        if ctx is not None:
            if event.operationId is None:
                event.operationId = ctx.operation_id
            if event.parentId is None:
                event.parentId = ctx.parent_id
            if event.actionLabel is None:
                event.actionLabel = ctx.label
            if event.actionKind is None:
                event.actionKind = ctx.kind
        self._events.append(event)
        if len(self._events) > self._limit:
            del self._events[: len(self._events) - self._limit]
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event.to_dict())
            except Exception:
                pass
        return event

    def subscribe(self, queue: Any) -> None:
        self._subscribers.append(queue)

    def unsubscribe(self, queue: Any) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def events(self, since: int = 0) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events if e.seq > since]

    def clear(self) -> None:
        self._events.clear()


class Recorder:
    """Wraps a real call so that its outcome — including its refusal — is an event.

    `refusals` names the exception types that are *meaningful system behaviour*
    rather than adapter bugs. Those are recorded with status `refused` and are
    re-raised to the caller as a structured refusal, never swallowed.
    """

    def __init__(self, sink: EventSink, system: str, session_id: str | None = None) -> None:
        self.sink = sink
        self.system = system
        self.session_id = session_id

    def run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        event_type: str,
        event_label: str | None = None,
        refusals: Iterable[type[BaseException]] = (),
        input_payload: Any = None,
        state_before: Any = None,
        operation_id: str | None = None,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        execution: str = "in-process import",
        transform: Callable[[Any], Any] | None = None,
        **kwargs: Any,
    ) -> tuple[Any, SyberEvent]:
        prov = Provenance.of(self.system, fn, execution=execution)
        started = time.perf_counter()
        refusal_types = tuple(refusals)
        try:
            result = fn(*args, **kwargs)
        except refusal_types as exc:  # real, expected system refusal
            duration = (time.perf_counter() - started) * 1000
            event = self.sink.emit(
                SyberEvent(
                    system=self.system,
                    sessionId=self.session_id,
                    eventType=event_type,
                    label=event_label,
                    status="refused",
                    durationMs=round(duration, 3),
                    input=input_payload,
                    stateBefore=state_before,
                    operationId=operation_id,
                    parentId=parent_id,
                    provenance=prov.to_dict(),
                    error={
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "refusalCode": refusal_code(exc),
                    },
                    metadata=metadata or {},
                )
            )
            raise SystemRefusal(
                system=self.system,
                kind=type(exc).__name__,
                message=str(exc),
                code=refusal_code(exc),
                provenance=prov.to_dict(),
                event=event,
            ) from exc
        except Exception as exc:  # genuine failure — still shown, never hidden
            duration = (time.perf_counter() - started) * 1000
            self.sink.emit(
                SyberEvent(
                    system=self.system,
                    sessionId=self.session_id,
                    eventType=event_type,
                    label=event_label,
                    status="error",
                    durationMs=round(duration, 3),
                    input=input_payload,
                    stateBefore=state_before,
                    operationId=operation_id,
                    parentId=parent_id,
                    provenance=prov.to_dict(),
                    error={
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(limit=6),
                    },
                    metadata=metadata or {},
                )
            )
            raise
        duration = (time.perf_counter() - started) * 1000
        event = self.sink.emit(
            SyberEvent(
                system=self.system,
                sessionId=self.session_id,
                eventType=event_type,
                label=event_label,
                status="ok",
                durationMs=round(duration, 3),
                input=input_payload,
                output=transform(result) if transform else _safe(result),
                stateBefore=state_before,
                operationId=operation_id,
                parentId=parent_id,
                provenance=prov.to_dict(),
                metadata=metadata or {},
            )
        )
        return result, event

    async def arun(
        self,
        fn: Callable[..., Any],
        *args: Any,
        event_type: str,
        event_label: str | None = None,
        refusals: Iterable[type[BaseException]] = (),
        input_payload: Any = None,
        state_before: Any = None,
        operation_id: str | None = None,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        execution: str = "in-process import",
        transform: Callable[[Any], Any] | None = None,
        **kwargs: Any,
    ) -> tuple[Any, SyberEvent]:
        """Async twin of `run`, for engines whose real API is a coroutine."""
        prov = Provenance.of(self.system, fn, execution=execution)
        started = time.perf_counter()
        refusal_types = tuple(refusals)
        try:
            result = await fn(*args, **kwargs)
        except refusal_types as exc:
            duration = (time.perf_counter() - started) * 1000
            event = self.sink.emit(
                SyberEvent(
                    system=self.system,
                    sessionId=self.session_id,
                    eventType=event_type,
                    label=event_label,
                    status="refused",
                    durationMs=round(duration, 3),
                    input=input_payload,
                    stateBefore=state_before,
                    operationId=operation_id,
                    parentId=parent_id,
                    provenance=prov.to_dict(),
                    error={
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "refusalCode": refusal_code(exc),
                    },
                    metadata=metadata or {},
                )
            )
            raise SystemRefusal(
                system=self.system,
                kind=type(exc).__name__,
                message=str(exc),
                code=refusal_code(exc),
                provenance=prov.to_dict(),
                event=event,
            ) from exc
        except Exception as exc:
            duration = (time.perf_counter() - started) * 1000
            self.sink.emit(
                SyberEvent(
                    system=self.system,
                    sessionId=self.session_id,
                    eventType=event_type,
                    label=event_label,
                    status="error",
                    durationMs=round(duration, 3),
                    input=input_payload,
                    stateBefore=state_before,
                    operationId=operation_id,
                    parentId=parent_id,
                    provenance=prov.to_dict(),
                    error={
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(limit=6),
                    },
                    metadata=metadata or {},
                )
            )
            raise
        duration = (time.perf_counter() - started) * 1000
        event = self.sink.emit(
            SyberEvent(
                system=self.system,
                sessionId=self.session_id,
                eventType=event_type,
                label=event_label,
                status="ok",
                durationMs=round(duration, 3),
                input=input_payload,
                output=transform(result) if transform else _safe(result),
                stateBefore=state_before,
                operationId=operation_id,
                parentId=parent_id,
                provenance=prov.to_dict(),
                metadata=metadata or {},
            )
        )
        return result, event


def refusal_code(exc: BaseException) -> str | None:
    """Extract a system's own machine-readable refusal code.

    Each source system spells this differently: Bough carries `reason`
    (`CYCLIC_AUTOMATON`), Barn raises `TransitionError("artifact_required")`
    where the message *is* the code, and SyberRuntime raises typed exceptions
    whose class name is the code. Nothing is invented: if a system offers no
    code, this returns None.
    """
    for attr in ("code", "reason", "refusal_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value:
            return value
    message = str(exc)
    # Barn's TransitionError message is a bare snake_case token.
    if message and " " not in message and message.replace("_", "").isalnum():
        return message
    return None


class SystemRefusal(Exception):
    """A real refusal raised by a source system, carried to the transport layer."""

    def __init__(
        self,
        *,
        system: str,
        kind: str,
        message: str,
        code: str | None,
        provenance: dict[str, Any],
        event: SyberEvent,
    ) -> None:
        super().__init__(message)
        self.system = system
        self.kind = kind
        self.message = message
        self.code = code
        self.provenance = provenance
        self.event = event

    def to_dict(self) -> dict[str, Any]:
        return {
            "refused": True,
            "system": self.system,
            "kind": self.kind,
            "code": self.code,
            "message": self.message,
            "provenance": self.provenance,
            "eventSeq": self.event.seq,
        }


def _safe(value: Any, depth: int = 0) -> Any:
    """Best-effort JSON projection that never invents structure."""
    if depth > 6:
        return "<max depth>"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _safe(v, depth + 1) for k, v in list(value.items())[:200]}
    if isinstance(value, (list, tuple, set)):
        return [_safe(v, depth + 1) for v in list(value)[:200]]
    if hasattr(value, "to_dict"):
        try:
            return _safe(value.to_dict(), depth + 1)
        except Exception:
            pass
    if hasattr(value, "model_dump"):
        try:
            return _safe(value.model_dump(mode="json"), depth + 1)
        except Exception:
            pass
    if hasattr(value, "__dict__") or hasattr(value, "__slots__"):
        slots = getattr(value, "__slots__", None)
        if slots:
            return {s: _safe(getattr(value, s, None), depth + 1) for s in slots}
        return {k: _safe(v, depth + 1) for k, v in vars(value).items() if not k.startswith("_")}
    return repr(value)
