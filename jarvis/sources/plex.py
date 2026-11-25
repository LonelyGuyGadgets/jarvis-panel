import time

import httpx

from jarvis.status import SourceResult


def read(cfg) -> SourceResult:
    base = cfg.raw.get("plex", {}).get("url", "http://localhost:32400")
    token = cfg.secrets.get("plex", {}).get("token")
    headers = {"Accept": "application/json"}
    try:
        if token:
            headers["X-Plex-Token"] = token
            resp = httpx.get(f"{base}/status/sessions", headers=headers, timeout=3)
            resp.raise_for_status()
            streams = int(resp.json().get("MediaContainer", {}).get("size", 0))
        else:
            resp = httpx.get(f"{base}/identity", headers=headers, timeout=3)
            resp.raise_for_status()
            streams = None
    except (httpx.HTTPError, ValueError):
        return SourceResult("offline", {}, time.time())
    return SourceResult("ok", {"streams": streams}, time.time())
