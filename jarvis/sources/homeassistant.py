"""Home Assistant client: state of configured lights/speakers and a handful of services.

Only entities listed under [smart_home] in config.toml can ever be controlled."""
import threading
import time
from typing import Callable, Optional

import httpx

from jarvis.actions import ActionResult, ActionSpec
from jarvis.status import SourceResult


def _token(cfg) -> Optional[str]:
    return cfg.secrets.get("homeassistant", {}).get("token") or None


def _smart(cfg) -> dict:
    return cfg.raw.get("smart_home", {})


def _ids(value) -> list:
    """A configured entry is one entity id, or a list of them (one button, several lamps)."""
    return [value] if isinstance(value, str) else list(value)


def _allowed(cfg) -> set:
    return {eid for group in _smart(cfg).values() for value in group.values() for eid in _ids(value)}


# The last colour each light showed while lit. Home Assistant reports no colour for a light that is off,
# so this is how a light that was off before Ultron's show gets its own colour back afterwards.
_colours: dict = {}
_colours_lock = threading.Lock()
colour_memory_paused = threading.Event()        # set while the show paints everything red


def colour_params(attrs: dict) -> dict:
    """Service data that recreates a lit light's brightness and colour."""
    params: dict = {}
    if attrs.get("brightness") is not None:
        params["brightness"] = attrs["brightness"]
    if attrs.get("color_mode") == "color_temp" and attrs.get("color_temp_kelvin"):
        params["color_temp_kelvin"] = attrs["color_temp_kelvin"]
    elif attrs.get("rgb_color"):
        params["rgb_color"] = list(attrs["rgb_color"])
    return params


def remember_colours(states: list) -> None:
    if colour_memory_paused.is_set():
        return
    with _colours_lock:
        for s in states:
            if s.get("state") == "on":
                params = colour_params(s.get("attributes") or {})
                if "rgb_color" in params or "color_temp_kelvin" in params:
                    _colours[s["entity_id"]] = params


def remembered_colours() -> dict:
    with _colours_lock:
        return {k: dict(v) for k, v in _colours.items()}


def forget_colours() -> None:
    with _colours_lock:
        _colours.clear()


def _make_client(cfg) -> httpx.Client:
    return httpx.Client(base_url=cfg.raw.get("homeassistant", {}).get("url", ""), timeout=5)


def _art_path(attrs: dict) -> Optional[str]:
    """Album art lives on Home Assistant itself; anything pointing elsewhere is ignored."""
    pic = attrs.get("entity_picture")
    return pic if isinstance(pic, str) and pic.startswith("/") and not pic.startswith("//") else None


def fetch_art(cfg, speaker: str, client: Optional[httpx.Client] = None):
    """(bytes, content_type) of the album art for a configured speaker, else None."""
    eid = _smart(cfg).get("speakers", {}).get(speaker)
    token = _token(cfg)
    if not eid or not token:
        return None
    client = client or _make_client(cfg)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        states = client.get("/api/states", headers=headers)
        states.raise_for_status()
        entity = next((x for x in states.json() if x.get("entity_id") == eid), {})
        path = _art_path(entity.get("attributes", {}))
        if path is None:
            return None
        img = client.get(path, headers=headers)
        img.raise_for_status()
        ctype = img.headers.get("content-type", "")
        return (img.content, ctype) if ctype.startswith("image/") else None
    except (httpx.HTTPError, ValueError, AttributeError):
        return None


def read(cfg, client: Optional[httpx.Client] = None) -> SourceResult:
    token = _token(cfg)
    if not token:
        return SourceResult("unconfigured", {}, time.time())
    client = client or _make_client(cfg)
    try:
        resp = client.get("/api/states", headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        states = resp.json()
        by_id = {s["entity_id"]: s for s in states}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return SourceResult("offline", {}, time.time())
    smart = _smart(cfg)
    remember_colours([s for s in states if s["entity_id"] in _allowed(cfg)])
    lights = [{"name": name, "on": any(by_id.get(e, {}).get("state") == "on" for e in _ids(value))}
              for name, value in smart.get("lights", {}).items()]
    speakers = []
    for name, eid in smart.get("speakers", {}).items():
        entity = by_id.get(eid, {})
        attrs = entity.get("attributes", {})
        level = attrs.get("volume_level")
        playing = entity.get("state") in ("playing", "paused")
        speakers.append({"name": name, "state": entity.get("state", "unavailable"),
                         "volume": None if level is None else round(level * 100),
                         "title": (attrs.get("media_title") or None) if playing else None,
                         "artist": (attrs.get("media_artist") or None) if playing else None,
                         "art": playing and _art_path(attrs) is not None})
    return SourceResult("ok", {"lights": lights, "speakers": speakers}, time.time())


def call(cfg, domain: str, service: str, entity_id,
         client: Optional[httpx.Client] = None, **data) -> ActionResult:
    if not set(_ids(entity_id)) <= _allowed(cfg):
        return ActionResult("refused", "entity not configured")
    token = _token(cfg)
    if not token:
        return ActionResult("failed", "Home Assistant token not configured")
    client = client or _make_client(cfg)
    try:
        resp = client.post(f"/api/services/{domain}/{service}",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"entity_id": entity_id, **data})
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return ActionResult("failed", f"Home Assistant: {exc}")
    return ActionResult("done", "ok")


def toggle_group(cfg, entity_ids: list, client: Optional[httpx.Client] = None) -> ActionResult:
    """One button for several lamps: any on -> all off, otherwise all on."""
    token = _token(cfg)
    if not token:
        return ActionResult("failed", "Home Assistant token not configured")
    client = client or _make_client(cfg)
    try:
        resp = client.get("/api/states", headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        by_id = {x["entity_id"]: x for x in resp.json()}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return ActionResult("failed", f"Home Assistant: {exc}")
    any_on = any(by_id.get(e, {}).get("state") == "on" for e in entity_ids)
    return call(cfg, "light", "turn_off" if any_on else "turn_on", entity_ids, client=client)


def handlers(cfg, client: Optional[httpx.Client] = None) -> dict:
    """Build the internal action handlers for every configured entity and register
    matching allowlist entries on cfg.actions."""
    smart = _smart(cfg)
    table: dict = {}

    def add(name: str, domain: str, service: str, entity_id: str):
        table[name] = (lambda d=domain, s=service, e=entity_id: call(cfg, d, s, e, client=client))
        cfg.actions[name] = ActionSpec(argv=None, internal=name, changes_state=True, exclusive=False)

    for name, value in smart.get("lights", {}).items():
        ids = _ids(value)
        for verb in ("on", "off"):
            table[f"lights_{verb}_{name}"] = (lambda e=ids, svc=f"turn_{verb}": call(cfg, "light", svc, e if len(e) > 1 else e[0], client=client))
            cfg.actions[f"lights_{verb}_{name}"] = ActionSpec(argv=None, internal=f"lights_{verb}_{name}",
                                                              changes_state=True, exclusive=False)
        if len(ids) == 1:
            add(f"lights_toggle_{name}", "light", "toggle", ids[0])
        else:
            table[f"lights_toggle_{name}"] = (lambda e=ids: toggle_group(cfg, e, client=client))
            cfg.actions[f"lights_toggle_{name}"] = ActionSpec(argv=None, internal=f"lights_toggle_{name}",
                                                              changes_state=True, exclusive=False)
    for name, eid in smart.get("scenes", {}).items():
        add(f"scene_{name}", "scene", "turn_on", eid)
    for name, eid in smart.get("speakers", {}).items():
        add(f"volume_up_{name}", "media_player", "volume_up", eid)
        add(f"volume_down_{name}", "media_player", "volume_down", eid)
        add(f"play_pause_{name}", "media_player", "media_play_pause", eid)
    return table
