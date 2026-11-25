import time

import pytest
from fastapi.testclient import TestClient

from jarvis.actions import ActionResult, ActionSpec
from jarvis.app import create_app
from jarvis.config import Config
from jarvis.status import SourceResult, cached


def make_cfg(secrets=None):
    actions = {
        "restart_plex": ActionSpec(["true"], None, True, False),
        "snapraid_sync": ActionSpec(["true"], None, True, True),
        "pause_pihole": ActionSpec(None, "pause_pihole", True, False),
    }
    return Config(actions=actions, secrets=secrets or {}, bind_host="127.0.0.1", port=1, raw={})


def good(c):
    return SourceResult("ok", {"x": 1}, time.time())


def client(cfg=None, sources=None, internal=None, web_dir=None, status_ttl=2.0):
    app = create_app(cfg or make_cfg(), sources or {"nuc": good}, internal or {}, web_dir=web_dir,
                     status_ttl=status_ttl)
    return TestClient(app, base_url="http://127.0.0.1")


def test_status_shape():
    body = client().get("/api/status").json()
    assert set(body) == {"health", "generated_at", "sources", "running", "last_actions", "voice", "control", "started"}
    assert body["running"] == [] and body["last_actions"] == {}
    assert isinstance(body["health"], int) and 0 <= body["health"] <= 100
    assert set(body["sources"]["nuc"]) == {"state", "data", "as_of"}


def test_one_bad_source_does_not_break_status():
    def boom(c):
        raise RuntimeError("down")

    r = client(sources={"nuc": good, "pihole": boom}).get("/api/status")
    assert r.status_code == 200
    assert r.json()["sources"]["pihole"]["state"] == "offline"
    assert r.json()["sources"]["nuc"]["state"] == "ok"


def test_secrets_never_in_responses():
    cfg = make_cfg({"pihole": {"password": "SECRET-TOKEN-123"}})
    c = client(cfg)
    assert "SECRET-TOKEN-123" not in c.get("/api/status").text
    assert "SECRET-TOKEN-123" not in c.post("/api/action/restart_plex", json={"confirm": True}).text
    assert "SECRET-TOKEN-123" not in c.post("/api/action/nonsense", json={"confirm": True}).text


def test_action_unknown_is_400():
    r = client().post("/api/action/rm%20-rf", json={"confirm": True})
    assert r.status_code == 400 and r.json()["status"] == "refused"


def test_action_without_confirm_is_400():
    r = client().post("/api/action/restart_plex", json={})
    assert r.status_code == 400 and r.json()["status"] == "refused"


def test_action_done_is_200():
    r = client(internal={"pause_pihole": lambda: ActionResult("done", "paused")}) \
        .post("/api/action/pause_pihole", json={"confirm": True})
    assert r.status_code == 200 and r.json() == {"status": "done", "message": "paused"}


def test_action_busy_is_409():
    c = client(internal={"pause_pihole": lambda: ActionResult("busy", "already running")})
    assert c.post("/api/action/pause_pihole", json={"confirm": True}).status_code == 409


def test_action_failed_is_502():
    c = client(internal={"pause_pihole": lambda: ActionResult("failed", "boom")})
    assert c.post("/api/action/pause_pihole", json={"confirm": True}).status_code == 502


def test_root_serves_index(tmp_path):
    (tmp_path / "index.html").write_text("<h1>panel</h1>")
    r = client(web_dir=str(tmp_path)).get("/")
    assert r.status_code == 200 and "panel" in r.text


def test_cached_source_reuses_result_within_ttl():
    calls = []

    def read(c):
        calls.append(1)
        return SourceResult("ok", {}, time.time())

    wrapped = cached(read, ttl=60)
    wrapped(None)
    wrapped(None)
    assert len(calls) == 1


def test_sources_read_in_parallel():
    def slow(c):
        time.sleep(0.3)
        return SourceResult("ok", {}, time.time())

    start = time.time()
    client(sources={"a": slow, "b": slow, "c": slow}).get("/api/status")
    assert time.time() - start < 0.8


def test_default_wiring_includes_pihole_source_and_pause_handler():
    from jarvis.app import default_internal, default_sources
    assert "pihole" in default_sources()
    assert "pause_pihole" in default_internal(make_cfg())


def test_default_wiring_includes_smart_home():
    from jarvis.app import default_internal, default_sources
    cfg = make_cfg()
    cfg.raw["smart_home"] = {"lights": {"desk": "light.govee_desk"}}
    assert "smart_home" in default_sources()
    assert "lights_toggle_desk" in default_internal(cfg)
    assert "lights_toggle_desk" in cfg.actions


def test_slow_collection_does_not_expire_the_cache_for_waiting_requests():
    import threading
    calls = []

    def slow(c):
        calls.append(1)
        time.sleep(0.4)
        return SourceResult("ok", {}, time.time())

    c = client(sources={"a": slow}, status_ttl=0.2)
    threads = [threading.Thread(target=lambda: c.get("/api/status")) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len(calls) == 1


def test_request_with_foreign_host_header_is_rejected():
    ran = []
    c = client(internal={"pause_pihole": lambda: ran.append(1) or ActionResult("done", "x")})
    r = c.post("/api/action/pause_pihole", json={"confirm": True}, headers={"Host": "evil.example"})
    assert r.status_code == 400 and ran == []


def test_configured_lan_host_is_accepted():
    cfg = make_cfg()
    cfg.bind_host = "192.0.2.10"
    c = TestClient(create_app(cfg, {"nuc": good}, {}), base_url="http://192.0.2.10:8088")
    assert c.get("/api/status").status_code == 200


def test_confirm_must_be_a_real_boolean():
    ran = []
    c = client(internal={"pause_pihole": lambda: ran.append(1) or ActionResult("done", "x")})
    for bad in ("yes", "true", 1, "1"):
        assert c.post("/api/action/pause_pihole", json={"confirm": bad}).status_code == 422
    assert ran == []


def test_status_reports_running_background_actions(monkeypatch):
    import subprocess, threading
    from jarvis import actions
    actions._reset()
    release = threading.Event()

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (release.wait(5), Done())[1])
    c = client(make_cfg())
    assert c.post("/api/action/snapraid_sync", json={"confirm": True}).status_code == 200
    time.sleep(0.1)
    assert c.get("/api/status").json()["running"] == ["snapraid_sync"]
    release.set()
    deadline = time.time() + 3
    while time.time() < deadline and actions.actions_running():
        time.sleep(0.01)
    time.sleep(0.1)
    body = c.get("/api/status").json()
    assert body["running"] == [] and body["last_actions"]["snapraid_sync"]["status"] == "done"


def test_static_files_are_always_revalidated(tmp_path):
    (tmp_path / "index.html").write_text("<h1>panel</h1>")
    r = client(web_dir=str(tmp_path)).get("/")
    assert r.headers["cache-control"] == "no-cache"


def test_status_carries_the_server_start_time_so_the_panel_can_spot_a_restart():
    c = TestClient(create_app(Config(actions={}, secrets={}, bind_host="127.0.0.1", port=1, raw={}),
                              {"nuc": lambda cfg: SourceResult("ok", {}, time.time())}, {}), base_url="http://127.0.0.1")
    a, b = c.get("/api/status").json()["started"], c.get("/api/status").json()["started"]
    assert a == b and 0 < a <= time.time()



# --- cross-site protection ---------------------------------------------------

def _pihole_client(ran):
    return client(internal={"pause_pihole": lambda: ran.append(1) or ActionResult("done", "x")})


def test_cross_site_post_from_another_origin_is_refused():
    ran = []
    r = _pihole_client(ran).post("/api/action/pause_pihole", json={"confirm": True},
                                 headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and ran == []


def test_browser_marked_cross_site_request_is_refused():
    ran = []
    r = _pihole_client(ran).post("/api/action/pause_pihole", json={"confirm": True},
                                 headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and ran == []


def test_null_origin_is_refused():
    ran = []
    r = _pihole_client(ran).post("/api/action/pause_pihole", json={"confirm": True}, headers={"Origin": "null"})
    assert r.status_code == 403 and ran == []


@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"])
def test_simple_form_content_types_are_refused(ctype):
    c = client()
    for path in ("/api/command", "/api/audio-level"):
        r = c.post(path, content=b'{"level": 5}', headers={"content-type": ctype})
        assert r.status_code == 415


def test_same_origin_panel_requests_still_work():
    ran = []
    r = _pihole_client(ran).post("/api/action/pause_pihole", json={"confirm": True},
                                 headers={"Origin": "http://127.0.0.1", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200 and ran == [1]
    assert client().post("/api/audio-level", json={"level": 5}).status_code == 200
