import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Literal


@dataclass
class SourceResult:
    state: Literal["ok", "warn", "offline", "stale", "unconfigured"]
    data: dict
    as_of: float


def collect_all(cfg, sources: dict, cache: dict, now: float, stale_after: float = 30.0,
                timeout: float = 8.0) -> dict:
    """Read every source. A failing source never breaks the others; a source that
    fails after earlier success keeps its last good data, marked stale once it is
    older than stale_after seconds."""
    results = {}
    if not sources:
        return results
    pool = ThreadPoolExecutor(max_workers=len(sources))
    futures = {name: pool.submit(read, cfg) for name, read in sources.items()}
    wait(list(futures.values()), timeout=timeout)
    pool.shutdown(wait=False)  # a source that missed the deadline is abandoned, not waited for
    for name, future in futures.items():
        try:
            fresh = future.result(timeout=0) if future.done() else SourceResult("offline", {}, now)
        except Exception:
            fresh = SourceResult("offline", {}, now)
        if fresh.state in ("ok", "warn", "unconfigured"):
            cache[name] = fresh
            results[name] = fresh
            continue
        last = cache.get(name)
        if last is None or last.state not in ("ok", "warn"):
            results[name] = fresh
        elif now - last.as_of > stale_after:
            results[name] = SourceResult("stale", last.data, last.as_of)
        else:
            results[name] = last
    return results


def health_percent(results: dict) -> int:
    counted = [r for r in results.values() if r.state != "unconfigured"]
    if not counted:
        return 0
    score = sum(1.0 if r.state == "ok" else 0.5 if r.state == "warn" else 0.0 for r in counted)
    return int(100 * score / len(counted))


def cached(read: Callable, ttl: float) -> Callable:
    """Wrap a source so slow reads (like SMART) run at most once per ttl seconds."""
    lock = threading.Lock()
    memo = {}

    def wrapped(cfg):
        with lock:
            hit = memo.get("r")
            if hit is not None and time.time() - hit[0] < ttl:
                return hit[1]
            result = read(cfg)
            memo["r"] = (time.time(), result)
            return result

    return wrapped
