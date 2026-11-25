import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal, Optional


@dataclass
class ActionSpec:
    argv: Optional[list]
    internal: Optional[str]
    changes_state: bool
    exclusive: bool


@dataclass
class ActionResult:
    status: Literal["done", "busy", "refused", "failed"]
    message: str


_locks: dict = {}
_last: dict = {}
_guard = threading.Lock()


def _reset():
    """Forget running/finished state (used by tests)."""
    with _guard:
        _locks.clear()
        _last.clear()


def _lock_for(name: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(name, threading.Lock())


def actions_running() -> list:
    with _guard:
        return sorted(n for n, lock in _locks.items() if lock.locked())


def last_results() -> dict:
    with _guard:
        return {n: dict(r) for n, r in _last.items()}


def _execute(spec: ActionSpec, internal: Optional[dict], timeout: Optional[float]) -> ActionResult:
    if spec.internal:
        handler = (internal or {}).get(spec.internal)
        if handler is None:
            return ActionResult("failed", f"no handler for {spec.internal}")
        return handler()
    try:
        proc = subprocess.run(spec.argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ActionResult("failed", str(exc))
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return ActionResult("failed", " | ".join(tail) or f"exit {proc.returncode}")
    return ActionResult("done", (proc.stdout or "").strip()[-200:] or "ok")


def _run_in_background(name: str, spec: ActionSpec, lock: threading.Lock, internal: Optional[dict]):
    def target():
        try:
            result = _execute(spec, internal, timeout=None)
        except Exception as exc:  # never lose a result because a handler blew up
            result = ActionResult("failed", str(exc))
        finally:
            pass
        with _guard:
            _last[name] = {"status": result.status, "message": result.message,
                           "finished_at": time.time()}
        lock.release()

    threading.Thread(target=target, daemon=True).start()


def run_action(name: str, confirm: bool, cfg, internal: Optional[dict] = None) -> ActionResult:
    spec = cfg.actions.get(name)
    if spec is None:
        return ActionResult("refused", "unknown action")
    if spec.changes_state and not confirm:
        return ActionResult("refused", "confirmation required")
    if not spec.exclusive:
        return _execute(spec, internal, timeout=3600)
    lock = _lock_for(name)
    if not lock.acquire(blocking=False):
        return ActionResult("busy", "already running")
    _run_in_background(name, spec, lock, internal)
    return ActionResult("done", "started")
