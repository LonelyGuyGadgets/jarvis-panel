"""Pi-hole v6 API client: summary stats and a timed pause of blocking."""
import threading
import time
from typing import Optional

import httpx

from jarvis.actions import ActionResult
from jarvis.status import SourceResult

_session = {"sid": None}
_lock = threading.Lock()


class PiholeError(Exception):
    pass


def _reset():
    _session["sid"] = None


def _make_client(cfg) -> httpx.Client:
    return httpx.Client(base_url=cfg.raw.get("pihole", {}).get("url", ""), timeout=5)


def _password(cfg) -> Optional[str]:
    return cfg.secrets.get("pihole", {}).get("password") or None


def _login(client, password: str) -> str:
    resp = client.post("/api/auth", json={"password": password})
    if resp.status_code != 200:
        raise PiholeError("login rejected")
    sid = resp.json().get("session", {}).get("sid")
    if not sid:
        raise PiholeError("login rejected")
    _session["sid"] = sid
    return sid


def _request(client, cfg, method: str, path: str, **kwargs):
    password = _password(cfg)
    with _lock:
        sid = _session["sid"] or _login(client, password)
        resp = client.request(method, path, headers={"X-FTL-SID": sid}, **kwargs)
        if resp.status_code == 401:
            sid = _login(client, password)
            resp = client.request(method, path, headers={"X-FTL-SID": sid}, **kwargs)
    if resp.status_code >= 400:
        raise PiholeError(f"{path} returned {resp.status_code}")
    return resp.json()


def read(cfg, client: Optional[httpx.Client] = None) -> SourceResult:
    if not _password(cfg):
        return SourceResult("unconfigured", {}, time.time())
    client = client or _make_client(cfg)
    try:
        summary = _request(client, cfg, "GET", "/api/stats/summary")
        blocking = _request(client, cfg, "GET", "/api/dns/blocking")
        queries = summary.get("queries", {})
        data = {
            "blocked_today": int(queries.get("blocked", 0)),
            "block_percent": float(queries.get("percent_blocked", 0.0)),
            "blocking": blocking.get("blocking") == "enabled",
        }
    except (httpx.HTTPError, PiholeError, ValueError):
        return SourceResult("offline", {}, time.time())
    return SourceResult("ok", data, time.time())


def resume(cfg, client: Optional[httpx.Client] = None) -> ActionResult:
    if not _password(cfg):
        return ActionResult("failed", "Pi-hole password not configured")
    client = client or _make_client(cfg)
    try:
        _request(client, cfg, "POST", "/api/dns/blocking", json={"blocking": True})
    except (httpx.HTTPError, PiholeError, ValueError) as exc:
        return ActionResult("failed", f"Pi-hole: {exc}")
    return ActionResult("done", "Ad blocking is back on")


def pause(cfg, minutes: int = 5, client: Optional[httpx.Client] = None) -> ActionResult:
    if not _password(cfg):
        return ActionResult("failed", "Pi-hole password not configured")
    client = client or _make_client(cfg)
    try:
        _request(client, cfg, "POST", "/api/dns/blocking",
                 json={"blocking": False, "timer": minutes * 60})
    except (httpx.HTTPError, PiholeError, ValueError) as exc:
        return ActionResult("failed", f"Pi-hole: {exc}")
    return ActionResult("done", f"Ad blocking paused for {minutes} minutes")
