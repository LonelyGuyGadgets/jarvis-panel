from jarvis.status import SourceResult, collect_all, health_percent
from jarvis.config import Config


def cfg():
    return Config(actions={}, secrets={}, bind_host="127.0.0.1", port=1, raw={})


def ok(data=None, as_of=1000.0, state="ok"):
    return SourceResult(state, data or {}, as_of)


def test_source_exception_becomes_offline():
    def boom(c):
        raise RuntimeError("nope")

    out = collect_all(cfg(), {"bad": boom, "good": lambda c: ok({"x": 1}, 1000.0)}, {}, now=1000.0)
    assert out["bad"].state == "offline"
    assert out["good"].state == "ok" and out["good"].data == {"x": 1}


def test_old_cached_result_marked_stale():
    cache = {"plex": ok({"streams": 2}, as_of=969.0)}
    out = collect_all(cfg(), {"plex": lambda c: SourceResult("offline", {}, 1000.0)}, cache, now=1000.0)
    assert out["plex"].state == "stale"
    assert out["plex"].data == {"streams": 2}
    assert out["plex"].as_of == 969.0


def test_recent_cached_result_survives_a_blip():
    cache = {"plex": ok({"streams": 2}, as_of=990.0)}
    out = collect_all(cfg(), {"plex": lambda c: SourceResult("offline", {}, 1000.0)}, cache, now=1000.0)
    assert out["plex"].state == "ok" and out["plex"].as_of == 990.0


def test_failure_with_no_cache_is_offline():
    out = collect_all(cfg(), {"plex": lambda c: SourceResult("offline", {}, 1000.0)}, {}, now=1000.0)
    assert out["plex"].state == "offline"


def test_good_read_updates_cache():
    cache = {}
    collect_all(cfg(), {"plex": lambda c: ok({"streams": 1}, 1000.0)}, cache, now=1000.0)
    assert cache["plex"].data == {"streams": 1}


def test_health_percent():
    results = {"a": ok(), "b": ok(), "c": ok(state="warn"), "d": ok(state="offline")}
    assert health_percent(results) == 62


def test_unconfigured_excluded_from_health():
    results = {"a": ok(), "b": ok(state="unconfigured")}
    assert health_percent(results) == 100


def test_health_with_no_sources_is_zero():
    assert health_percent({}) == 0


def test_slow_source_hits_deadline_and_others_still_return():
    import time
    def slow(c):
        time.sleep(1.0)
        return ok({"x": 1}, time.time())

    start = time.time()
    out = collect_all(cfg(), {"slow": slow, "fast": lambda c: ok({"y": 2}, time.time())},
                      {}, now=time.time(), timeout=0.2)
    assert time.time() - start < 0.7
    assert out["slow"].state == "offline"
    assert out["fast"].state == "ok"


def test_slow_source_with_cached_data_goes_stale_after_deadline():
    import time
    now = time.time()
    cache = {"slow": ok({"x": 1}, as_of=now - 40)}
    out = collect_all(cfg(), {"slow": lambda c: time.sleep(1.0) or ok()}, cache, now=now, timeout=0.2)
    assert out["slow"].state == "stale" and out["slow"].data == {"x": 1}
