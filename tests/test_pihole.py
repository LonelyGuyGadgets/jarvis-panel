import json

import httpx
import pytest

from jarvis.config import Config
from jarvis.sources import pihole


def make_cfg(password="pw"):
    secrets = {"pihole": {"password": password}} if password else {}
    return Config(actions={}, secrets=secrets, bind_host="x", port=1,
                  raw={"pihole": {"url": "http://pi.test"}})


@pytest.fixture(autouse=True)
def fresh_session():
    pihole._reset()


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://pi.test")


def good_handler(requests):
    def handler(request):
        requests.append(request)
        path = request.url.path
        if path == "/api/auth":
            return httpx.Response(200, json={"session": {"valid": True, "sid": "SID1", "validity": 300}})
        if path == "/api/stats/summary":
            return httpx.Response(200, json={"queries": {"total": 1000, "blocked": 230, "percent_blocked": 23.0}})
        if path == "/api/dns/blocking" and request.method == "GET":
            return httpx.Response(200, json={"blocking": "enabled", "timer": None})
        if path == "/api/dns/blocking" and request.method == "POST":
            return httpx.Response(200, json={"blocking": "disabled", "timer": 300})
        return httpx.Response(404)
    return handler


def test_read_maps_summary():
    reqs = []
    r = pihole.read(make_cfg(), client=client_for(good_handler(reqs)))
    assert r.state == "ok"
    assert r.data == {"blocked_today": 230, "block_percent": 23.0, "blocking": True}
    summary = [q for q in reqs if q.url.path == "/api/stats/summary"][0]
    assert summary.headers["X-FTL-SID"] == "SID1"


def test_wrong_password_is_offline():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    r = pihole.read(make_cfg(), client=client_for(handler))
    assert r.state == "offline"


def test_unreachable_is_offline():
    def handler(request):
        raise httpx.ConnectError("refused")

    assert pihole.read(make_cfg(), client=client_for(handler)).state == "offline"


def test_missing_password_is_unconfigured():
    reqs = []
    r = pihole.read(make_cfg(password=None), client=client_for(good_handler(reqs)))
    assert r.state == "unconfigured"
    assert reqs == []


def test_session_is_reused_between_reads():
    reqs = []
    c = client_for(good_handler(reqs))
    pihole.read(make_cfg(), client=c)
    pihole.read(make_cfg(), client=c)
    assert len([q for q in reqs if q.url.path == "/api/auth"]) == 1


def test_expired_session_reauthenticates_once():
    state = {"first": True}
    reqs = []

    def handler(request):
        reqs.append(request)
        if request.url.path == "/api/stats/summary" and state["first"]:
            state["first"] = False
            return httpx.Response(401, json={})
        return good_handler([])(request)

    pihole._session["sid"] = "OLD"
    r = pihole.read(make_cfg(), client=client_for(handler))
    assert r.state == "ok"


def test_pause_sends_timer_300():
    reqs = []
    result = pihole.pause(make_cfg(), minutes=5, client=client_for(good_handler(reqs)))
    assert result.status == "done"
    post = [q for q in reqs if q.url.path == "/api/dns/blocking" and q.method == "POST"][0]
    assert json.loads(post.content) == {"blocking": False, "timer": 300}


def test_pause_unreachable_fails():
    def handler(request):
        raise httpx.ConnectError("refused")

    assert pihole.pause(make_cfg(), client=client_for(handler)).status == "failed"


def test_pause_without_password_fails_with_message():
    result = pihole.pause(make_cfg(password=None), client=client_for(good_handler([])))
    assert result.status == "failed" and "password" in result.message.lower()


def test_resume_turns_blocking_back_on_immediately():
    reqs = []
    result = pihole.resume(make_cfg(), client=client_for(good_handler(reqs)))
    assert result.status == "done"
    post = [q for q in reqs if q.url.path == "/api/dns/blocking" and q.method == "POST"][0]
    assert json.loads(post.content) == {"blocking": True}


def test_resume_unreachable_fails():
    def handler(request):
        raise httpx.ConnectError("refused")

    assert pihole.resume(make_cfg(), client=client_for(handler)).status == "failed"
