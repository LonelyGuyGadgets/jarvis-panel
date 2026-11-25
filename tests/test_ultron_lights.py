import json
import time

import httpx
from fastapi.testclient import TestClient

from jarvis.app import create_app
from jarvis.config import Config
from jarvis.sources import homeassistant as ha
from jarvis.status import SourceResult
from jarvis.ultron_lights import UltronLights

LIGHTS = {"desk": "light.a", "floor": ["light.b", "light.c"], "ceil": "light.d"}
ALL = {"light.a", "light.b", "light.c", "light.d"}
STATES = [
    {"entity_id": "light.a", "state": "on", "attributes": {"brightness": 120, "color_mode": "color_temp", "color_temp_kelvin": 3000}},
    {"entity_id": "light.b", "state": "on", "attributes": {"brightness": 200, "color_mode": "rgb", "rgb_color": [10, 200, 30]}},
    {"entity_id": "light.c", "state": "off", "attributes": {}},
    {"entity_id": "light.d", "state": "off", "attributes": {}},
]


def make_cfg(token="tok"):
    secrets = {"homeassistant": {"token": token}} if token else {}
    raw = {"homeassistant": {"url": "http://ha.test"}, "smart_home": {"lights": LIGHTS}}
    return Config(actions={}, secrets=secrets, bind_host="x", port=1, raw=raw)


class Recorder:
    def __init__(self, states=None):
        self.calls = []                      # (service, json body)
        self.states = states or STATES

    def client(self):
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, json=self.states)
            self.calls.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
            return httpx.Response(200, json=[])
        return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ha.test")


def ids_of(body):
    e = body["entity_id"]
    return set([e] if isinstance(e, str) else e)


def final_state(calls):
    """entity id -> the last (service, body) that touched it."""
    out = {}
    for service, body in calls:
        for eid in ids_of(body):
            out[eid] = (service, body)
    return out


def test_start_turns_every_light_on_red_then_blinks():
    rec = Recorder()
    u = UltronLights(make_cfg(), client=rec.client(), interval=0.01, max_seconds=30, verify_wait=0)
    assert u.start() is True
    time.sleep(0.25)
    u.stop()
    first_service, first_body = rec.calls[0]
    assert first_service == "turn_on" and first_body["rgb_color"] == [255, 0, 0] and first_body["brightness"] == 255
    assert ids_of(first_body) == ALL
    assert {s for s, _ in rec.calls} >= {"turn_on", "turn_off"}            # it actually blinks


def test_stop_puts_every_light_back_how_it_was():
    rec = Recorder()
    u = UltronLights(make_cfg(), client=rec.client(), interval=0.01, max_seconds=30, settle=0, verify_wait=0)
    u.start()
    time.sleep(0.1)
    u.stop()
    after = final_state(rec.calls)
    assert after["light.a"][0] == "turn_on" and after["light.a"][1]["brightness"] == 120 and after["light.a"][1]["color_temp_kelvin"] == 3000
    assert after["light.b"][0] == "turn_on" and after["light.b"][1]["rgb_color"] == [10, 200, 30]
    assert after["light.c"][0] == "turn_off" and after["light.d"][0] == "turn_off"
    n = len(rec.calls)
    time.sleep(0.1)
    assert len(rec.calls) == n and not u.running                           # nothing more after stop


def test_it_restores_on_its_own_after_the_failsafe_time():
    rec = Recorder()
    u = UltronLights(make_cfg(), client=rec.client(), interval=0.01, max_seconds=0.15, settle=0, verify_wait=0)
    u.start()
    time.sleep(0.6)
    assert not u.running
    assert rec.calls[-1][0] == "turn_off"                                  # last restore call (light.d was off)


def test_start_twice_is_one_run_and_stop_without_start_is_harmless():
    rec = Recorder()
    u = UltronLights(make_cfg(), client=rec.client(), interval=0.01, max_seconds=30, verify_wait=0)
    u.stop()
    assert u.start() is True and u.start() is False
    u.stop()


def test_no_home_assistant_token_means_nothing_happens():
    rec = Recorder()
    u = UltronLights(make_cfg(token=None), client=rec.client(), interval=0.01, max_seconds=30, verify_wait=0)
    assert u.start() is False and rec.calls == []


class FakeLights:
    def __init__(self):
        self.log = []

    def start(self):
        self.log.append("start")
        return True

    def stop(self):
        self.log.append("stop")


def test_endpoint_starts_and_stops_the_light_show():
    fake = FakeLights()
    app = create_app(make_cfg(), {"nuc": lambda c: SourceResult("ok", {}, time.time())}, {}, ultron_lights=fake)
    c = TestClient(app, base_url="http://x")
    assert c.post("/api/ultron/lights", json={"mode": "start"}).status_code == 200
    assert c.post("/api/ultron/lights", json={"mode": "stop"}).status_code == 200
    assert c.post("/api/ultron/lights", json={"mode": "bogus"}).status_code == 422
    assert fake.log == ["start", "stop"]


WHITE_K = 4000


def red_free(body):
    return body.get("rgb_color") != [255, 0, 0]


def show(states=None, client=None, **kw):
    """Run a short light show against a fake Home Assistant and wait for the restore and its checks to finish."""
    rec = Recorder(states)
    u = UltronLights(make_cfg(), client=client or rec.client(), interval=0.01, max_seconds=30, settle=0, verify_wait=0, **kw)
    u.start()
    time.sleep(0.1)
    u.stop()
    for _ in range(200):
        if not u.running:
            break
        time.sleep(0.01)
    return rec, u


def test_a_light_that_was_off_gets_its_remembered_colour_back_before_it_is_switched_off():
    ha.forget_colours()
    ha.colour_memory_paused.clear()
    ha.remember_colours([{"entity_id": "light.c", "state": "on",
                          "attributes": {"brightness": 77, "color_mode": "rgb", "rgb_color": [5, 6, 250]}}])
    rec, _ = show()
    mine = [(svc, body) for svc, body in rec.calls if ids_of(body) == {"light.c"}]
    assert mine[-1][0] == "turn_off"                                           # it ends off, as it began
    assert any(svc == "turn_on" and b.get("rgb_color") == [5, 6, 250] and b.get("brightness") == 77 for svc, b in mine)


def test_a_light_that_was_off_with_no_remembered_colour_is_left_white_not_red():
    ha.forget_colours()
    ha.colour_memory_paused.clear()
    rec, _ = show()
    mine = [(svc, body) for svc, body in rec.calls if ids_of(body) == {"light.d"}]
    assert mine[-1][0] == "turn_off"
    whites = [b for svc, b in mine if svc == "turn_on" and b.get("color_temp_kelvin") == WHITE_K]
    assert whites and all(red_free(b) for b in whites)


def test_a_light_that_was_red_before_the_show_comes_back_red():
    states = [dict(STATES[0], attributes={"brightness": 90, "color_mode": "rgb", "rgb_color": [255, 0, 0]})] + STATES[1:]
    rec, _ = show(states)
    service, body = final_state(rec.calls)["light.a"]
    assert service == "turn_on" and body.get("rgb_color") == [255, 0, 0] and body.get("brightness") == 90


def test_a_light_with_no_known_colour_comes_back_white():
    states = [dict(STATES[0], attributes={})] + STATES[1:]
    rec, _ = show(states)
    service, body = final_state(rec.calls)["light.a"]
    assert service == "turn_on" and body.get("color_temp_kelvin") == WHITE_K


class FlakyHA:
    """A Home Assistant whose bulbs really keep state, and ignore the first few commands sent to some of them,
    the way Govee LAN bulbs drop a command that arrives right behind another."""
    def __init__(self, drops):
        self.dev = {}
        for s in STATES:
            a = s["attributes"]
            self.dev[s["entity_id"]] = {"on": s["state"] == "on", "attrs": dict(a)}
        self.drops = dict(drops)                 # (service, entity id) -> how many to ignore
        self.calls = []

    def states(self):
        return [{"entity_id": e, "state": "on" if d["on"] else "off", "attributes": d["attrs"] if d["on"] else {}}
                for e, d in self.dev.items()]

    def client(self):
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, json=self.states())
            service = request.url.path.rsplit("/", 1)[-1]
            body = json.loads(request.content)
            self.calls.append((service, body))
            for eid in ids_of(body):
                if self.drops.get((service, eid), 0) > 0:
                    self.drops[(service, eid)] -= 1
                    continue
                d = self.dev[eid]
                d["on"] = service == "turn_on"
                if service == "turn_on":
                    attrs = {"brightness": body.get("brightness", d["attrs"].get("brightness"))}
                    if "rgb_color" in body:
                        attrs.update(color_mode="rgb", rgb_color=body["rgb_color"])
                    elif "color_temp_kelvin" in body:
                        attrs.update(color_mode="color_temp", color_temp_kelvin=body["color_temp_kelvin"])
                    d["attrs"] = attrs
            return httpx.Response(200, json=[])
        return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ha.test")


def test_a_bulb_that_ignores_its_off_command_is_checked_and_switched_off_again():
    fake = FlakyHA({("turn_off", "light.c"): 2})
    show(client=fake.client())
    assert fake.dev["light.c"]["on"] is False and fake.dev["light.d"]["on"] is False


def test_a_bulb_that_ignores_its_restore_is_checked_and_put_back_on_in_its_colour():
    fake = FlakyHA({("turn_on", "light.b"): 3})                # misses the red, and the first restore
    show(client=fake.client())
    b = fake.dev["light.b"]
    assert b["on"] is True and b["attrs"]["rgb_color"] == [10, 200, 30]
    assert fake.dev["light.a"]["attrs"]["color_temp_kelvin"] == 3000


def test_stop_does_not_wait_for_the_slow_checks():
    rec = Recorder()
    u = UltronLights(make_cfg(), client=rec.client(), interval=0.01, max_seconds=30, settle=0, verify_wait=5)
    u.start()
    time.sleep(0.1)
    t0 = time.time()
    u.stop()
    assert time.time() - t0 < 1
    assert final_state(rec.calls)["light.d"][0] == "turn_off"                 # the restore itself is already done


def test_colours_seen_during_the_show_are_not_remembered():
    ha.forget_colours()
    ha.colour_memory_paused.clear()
    rec = Recorder()
    u = UltronLights(make_cfg(), client=rec.client(), interval=0.01, max_seconds=30, settle=0, verify_wait=0)
    u.start()
    rec.states = [{"entity_id": "light.a", "state": "on",
                   "attributes": {"brightness": 255, "color_mode": "rgb", "rgb_color": [255, 0, 0]}}]
    ha.read(make_cfg(), client=rec.client())                                   # the panel polls while he blinks
    u.stop()
    assert ha.remembered_colours()["light.a"] == {"brightness": 120, "color_temp_kelvin": 3000}


def test_reading_the_lights_remembers_each_lit_lights_colour():
    ha.forget_colours()
    ha.colour_memory_paused.clear()
    ha.read(make_cfg(), client=Recorder().client())
    assert ha.remembered_colours()["light.a"] == {"brightness": 120, "color_temp_kelvin": 3000}
    assert ha.remembered_colours()["light.b"] == {"brightness": 200, "rgb_color": [10, 200, 30]}
    assert "light.c" not in ha.remembered_colours()
