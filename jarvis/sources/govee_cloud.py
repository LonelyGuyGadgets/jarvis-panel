"""Govee cloud API, for lights Home Assistant's local integration can't reach (older models without LAN control).
Only the lights listed under [govee_cloud.lights] in config.toml can ever be controlled.
Govee limits each device to about 10 commands a minute, so state reads are cached and callers must not hammer it."""
import threading
import time
import uuid
from typing import Optional

import httpx

from jarvis.actions import ActionResult, ActionSpec

BASE = "https://openapi.api.govee.com"
STATE_TTL = 20.0
_cache: dict = {}                 # name -> (time read, snapshot)
_lock = threading.Lock()

ON_OFF = "devices.capabilities.on_off"
COLOR = "devices.capabilities.color_setting"
RANGE = "devices.capabilities.range"


def _key(cfg) -> Optional[str]:
    return cfg.secrets.get("govee", {}).get("api_key") or None


def _lights(cfg) -> dict:
    return cfg.raw.get("govee_cloud", {}).get("lights", {})


def has_colour(cfg, name: str) -> bool:
    return bool(_lights(cfg).get(name, {}).get("color", True))


def _client(cfg) -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=8)


def _control(cfg, name: str, cap_type: str, instance: str, value, client=None) -> ActionResult:
    dev = _lights(cfg).get(name)
    if dev is None:
        return ActionResult("refused", "light not configured")
    key = _key(cfg)
    if not key:
        return ActionResult("failed", "Govee API key not configured")
    client = client or _client(cfg)
    body = {"requestId": str(uuid.uuid4()),
            "payload": {"sku": dev["sku"], "device": dev["device"],
                        "capability": {"type": cap_type, "instance": instance, "value": value}}}
    try:
        resp = client.post("/router/api/v1/device/control", headers={"Govee-API-Key": key}, json=body)
        resp.raise_for_status()
        reply = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return ActionResult("failed", f"Govee: {exc}")
    if reply.get("code", 200) != 200:     # Govee reports problems (e.g. device offline) in the body of an HTTP 200
        return ActionResult("failed", f"Govee: {reply.get('msg', 'command failed')}")
    with _lock:
        _cache.pop(name, None)                  # the next read must see the change
    return ActionResult("done", "ok")


def power(cfg, name: str, on: bool, client=None) -> ActionResult:
    return _control(cfg, name, ON_OFF, "powerSwitch", 1 if on else 0, client)


def color(cfg, name: str, rgb: list, client=None) -> ActionResult:
    r, g, b = rgb
    return _control(cfg, name, COLOR, "colorRgb", (r << 16) | (g << 8) | b, client)


def kelvin(cfg, name: str, k: int, client=None) -> ActionResult:
    return _control(cfg, name, COLOR, "colorTemperatureK", k, client)


def brightness(cfg, name: str, pct: int, client=None) -> ActionResult:
    return _control(cfg, name, RANGE, "brightness", pct, client)


def snapshot(cfg, name: str, client=None) -> Optional[dict]:
    """{"online","on","brightness","rgb","kelvin"} from the cloud, or None if it can't be read."""
    dev, key = _lights(cfg).get(name), _key(cfg)
    if dev is None or not key:
        return None
    client = client or _client(cfg)
    try:
        resp = client.post("/router/api/v1/device/state", headers={"Govee-API-Key": key},
                           json={"requestId": str(uuid.uuid4()), "payload": {"sku": dev["sku"], "device": dev["device"]}})
        resp.raise_for_status()
        caps = {c["instance"]: c.get("state", {}).get("value") for c in resp.json()["payload"]["capabilities"]}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    return {"online": caps.get("online", True) is not False, "on": caps.get("powerSwitch") == 1, "brightness": caps.get("brightness"),
            "rgb": caps.get("colorRgb"), "kelvin": caps.get("colorTemperatureK") or 0}


def _cached_snapshot(cfg, name: str, client=None) -> Optional[dict]:
    with _lock:
        hit = _cache.get(name)
        if hit and time.time() - hit[0] < STATE_TTL:
            return hit[1]
    snap = snapshot(cfg, name, client)
    if snap is not None:
        with _lock:
            _cache[name] = (time.time(), snap)
    return snap


def read_lights(cfg, client=None) -> list:
    """The cloud lights as panel entries [{"name", "on"}]; lights that can't be read are left out."""
    out = []
    for name in _lights(cfg):
        snap = _cached_snapshot(cfg, name, client)
        if snap is not None:
            out.append({"name": name, "on": snap["on"]})
    return out


def toggle(cfg, name: str, client=None) -> ActionResult:
    snap = snapshot(cfg, name, client)
    if snap is None:
        return ActionResult("failed", "Govee: could not read the light")
    return power(cfg, name, not snap["on"], client)


def _rgb(value) -> Optional[list]:
    return None if value is None else [(value >> 16) & 255, (value >> 8) & 255, value & 255]


def restore(cfg, name: str, snap: dict, client=None) -> None:
    """Put a light back as snapshotted: on or off, in its own colour. The colour is set even if it was off,
    so it does not keep Ultron's red; one whose colour can't be read comes back white."""
    if not has_colour(cfg, name):                # a plug: power is all there is
        power(cfg, name, bool(snap["on"]), client)
        return
    power(cfg, name, True, client)
    rgb = _rgb(snap.get("rgb"))
    if snap.get("kelvin"):
        kelvin(cfg, name, snap["kelvin"], client)
    elif rgb is None:
        kelvin(cfg, name, 4000, client)
    else:
        color(cfg, name, rgb, client)
    if snap.get("brightness") is not None:
        brightness(cfg, name, snap["brightness"], client)
    if not snap["on"]:
        power(cfg, name, False, client)


def matches(cfg, name: str, want: dict, got: dict) -> bool:
    """Is the light really back as it was? Power always; colour too where the light has one."""
    if bool(got.get("on")) != bool(want.get("on")):
        return False
    if not has_colour(cfg, name):
        return True
    if want.get("kelvin"):
        return abs((got.get("kelvin") or 0) - want["kelvin"]) <= 150
    if want.get("rgb") is not None:
        return not got.get("kelvin") and got.get("rgb") == want["rgb"]
    return True


def handlers(cfg, client=None) -> dict:
    """Internal action handlers for every configured cloud light, registered on cfg.actions."""
    table: dict = {}
    for name in _lights(cfg):
        for verb, fn in (("toggle", lambda n=name: toggle(cfg, n, client)),
                         ("on", lambda n=name: power(cfg, n, True, client)),
                         ("off", lambda n=name: power(cfg, n, False, client))):
            key = f"lights_{verb}_{name}"
            table[key] = fn
            cfg.actions[key] = ActionSpec(argv=None, internal=key, changes_state=True, exclusive=False)
    return table
