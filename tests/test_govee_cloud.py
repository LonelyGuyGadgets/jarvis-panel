import json
import time

import httpx

from jarvis.config import Config
from jarvis.sources import govee_cloud
from jarvis.ultron_lights import UltronLights

BARS = {"sku": "H6054", "device": "AA:BB"}


def make_cfg(key="k", ha_token=None):
    secrets = {}
    if key:
        secrets["govee"] = {"api_key": key}
    if ha_token:
        secrets["homeassistant"] = {"token": ha_token}
    raw = {"homeassistant": {"url": "http://ha.test"}, "smart_home": {"lights": {"desk": "light.a"}},
           "govee_cloud": {"lights": {"Office Light Bars": BARS}}}
    return Config(actions={}, secrets=secrets, bind_host="x", port=1, raw=raw)


class FakeGovee:
    """Pretends to be Govee's cloud: remembers power/colour/brightness and records every control call."""
    def __init__(self, on=True, rgb=0x112233, bright=40, kelvin=0, online=True, sku="H6054", drop_power=0):
        self.sku = sku
        self.drop_power = drop_power        # how many power commands to refuse, like Govee past its rate limit
        self.on, self.rgb, self.bright, self.kelvin, self.online = on, rgb, bright, kelvin, online
        self.controls = []                  # (instance, value)
        self.state_reads = 0

    def client(self):
        def handler(request):
            assert request.headers["Govee-API-Key"] == "k"
            body = json.loads(request.content)
            if request.url.path.endswith("/device/state"):
                self.state_reads += 1
                caps = [{"type": "devices.capabilities.online", "instance": "online", "state": {"value": self.online}},
                        {"type": "devices.capabilities.on_off", "instance": "powerSwitch", "state": {"value": 1 if self.on else 0}},
                        {"type": "devices.capabilities.range", "instance": "brightness", "state": {"value": self.bright}},
                        {"type": "devices.capabilities.color_setting", "instance": "colorRgb", "state": {"value": self.rgb}},
                        {"type": "devices.capabilities.color_setting", "instance": "colorTemperatureK", "state": {"value": self.kelvin}}]
                return httpx.Response(200, json={"code": 200, "payload": {"capabilities": caps}})
            cap = body["payload"]["capability"]
            if not self.online:      # Govee answers HTTP 200 with an error code in the body
                return httpx.Response(200, json={"code": 400, "msg": "Device is offline. Please check the Wi-Fi connection."})
            assert body["payload"]["sku"] == self.sku and body["payload"]["device"] == "AA:BB"
            self.controls.append((cap["instance"], cap["value"]))
            if cap["instance"] == "powerSwitch" and self.drop_power > 0:
                self.drop_power -= 1
                return httpx.Response(200, json={"code": 429, "msg": "Too many requests"})
            if cap["instance"] == "powerSwitch":
                self.on = bool(cap["value"])
            elif cap["instance"] == "colorRgb":
                self.rgb, self.kelvin = cap["value"], 0
            elif cap["instance"] == "colorTemperatureK":
                self.kelvin = cap["value"]
            elif cap["instance"] == "brightness":
                self.bright = cap["value"]
            return httpx.Response(200, json={"code": 200, "msg": "success"})
        return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://govee.test")


def test_power_color_and_brightness_send_the_right_cloud_commands():
    g = FakeGovee()
    c = g.client()
    assert govee_cloud.power(make_cfg(), "Office Light Bars", True, client=c).status == "done"
    govee_cloud.color(make_cfg(), "Office Light Bars", [255, 0, 0], client=c)
    govee_cloud.brightness(make_cfg(), "Office Light Bars", 100, client=c)
    assert g.controls == [("powerSwitch", 1), ("colorRgb", 255 << 16), ("brightness", 100)]


def test_unknown_light_is_refused_and_no_key_fails_without_a_call():
    g = FakeGovee()
    assert govee_cloud.power(make_cfg(), "Garage", True, client=g.client()).status == "refused"
    assert govee_cloud.power(make_cfg(key=None), "Office Light Bars", True, client=g.client()).status == "failed"
    assert g.controls == []


def test_snapshot_reads_power_brightness_and_colour():
    g = FakeGovee(on=False, rgb=0x0A141E, bright=55)
    s = govee_cloud.snapshot(make_cfg(), "Office Light Bars", client=g.client())
    assert s == {"on": False, "brightness": 55, "rgb": 0x0A141E, "kelvin": 0, "online": True}


def test_read_lights_reports_on_state_and_is_cached_so_polling_is_cheap():
    govee_cloud._cache.clear()
    g = FakeGovee(on=True)
    c = g.client()
    assert govee_cloud.read_lights(make_cfg(), client=c) == [{"name": "Office Light Bars", "on": True}]
    govee_cloud.read_lights(make_cfg(), client=c)
    assert g.state_reads == 1
    govee_cloud.power(make_cfg(), "Office Light Bars", False, client=c)      # a change drops the cache
    assert govee_cloud.read_lights(make_cfg(), client=c) == [{"name": "Office Light Bars", "on": False}]


def test_toggle_flips_power():
    govee_cloud._cache.clear()
    g = FakeGovee(on=True)
    govee_cloud.toggle(make_cfg(), "Office Light Bars", client=g.client())
    assert g.controls == [("powerSwitch", 0)]


def test_handlers_register_toggle_on_off_actions():
    cfg = make_cfg()
    table = govee_cloud.handlers(cfg, client=FakeGovee().client())
    for n in ("lights_toggle_Office Light Bars", "lights_on_Office Light Bars", "lights_off_Office Light Bars"):
        assert n in table and n in cfg.actions


def test_ultron_show_blinks_the_bars_slowly_and_restores_them():
    govee_cloud._cache.clear()
    g = FakeGovee(on=False, rgb=0x0A141E, bright=55)           # bars start OFF with a colour
    u = UltronLights(make_cfg(), client=None, cloud_client=g.client(), interval=0.01, cloud_interval=0.05, max_seconds=30, cloud_verify_wait=0)
    assert u.start() is True                                     # no HA token, but Govee works
    time.sleep(0.4)
    u.stop()
    inst = [i for i, _ in g.controls]
    assert ("colorRgb", 255 << 16) in g.controls and ("brightness", 100) in g.controls
    assert g.controls.count(("powerSwitch", 0)) >= 2 and g.controls.count(("powerSwitch", 1)) >= 2   # it blinked
    assert inst[-4:] == ["powerSwitch", "colorRgb", "brightness", "powerSwitch"]                    # restore burst
    assert g.controls[-3] == ("colorRgb", 0x0A141E) and g.controls[-2] == ("brightness", 55)
    assert g.controls[-1] == ("powerSwitch", 0) and not g.on                                         # back to off


def test_an_offline_light_reports_the_error_instead_of_pretending_it_worked():
    g = FakeGovee(online=False)
    r = govee_cloud.power(make_cfg(), "Office Light Bars", False, client=g.client())
    assert r.status == "failed" and "offline" in r.message.lower()


def test_the_ultron_show_leaves_offline_lights_alone():
    govee_cloud._cache.clear()
    g = FakeGovee(online=False)
    u = UltronLights(make_cfg(), client=None, cloud_client=g.client(), interval=0.01, cloud_interval=0.05, max_seconds=30, cloud_verify_wait=0)
    assert u.start() is False and g.controls == []


def plug_cfg():
    cfg = make_cfg()
    cfg.raw["govee_cloud"]["lights"] = {"Couch Lamp": {"sku": "H5083", "device": "AA:BB", "color": False}}
    return cfg


def test_a_plug_with_no_colour_only_ever_gets_power_commands_in_the_show():
    govee_cloud._cache.clear()
    g = FakeGovee(on=False, sku="H5083")
    u = UltronLights(plug_cfg(), client=None, cloud_client=g.client(), interval=0.01, cloud_interval=0.05, max_seconds=30, cloud_verify_wait=0)
    assert u.start() is True
    time.sleep(0.3)
    u.stop()
    assert {i for i, _ in g.controls} == {"powerSwitch"}
    assert g.controls[-1] == ("powerSwitch", 0) and not g.on                # it was off, so it ends off


def test_a_plug_that_was_on_ends_on():
    govee_cloud._cache.clear()
    g = FakeGovee(on=True, sku="H5083")
    u = UltronLights(plug_cfg(), client=None, cloud_client=g.client(), interval=0.01, cloud_interval=0.05, max_seconds=30, cloud_verify_wait=0)
    u.start()
    time.sleep(0.2)
    u.stop()
    assert g.controls[-1] == ("powerSwitch", 1) and g.on


def test_a_bar_that_was_red_before_the_show_comes_back_red():
    govee_cloud._cache.clear()
    g = FakeGovee(on=True, rgb=0xFF0000, bright=80)
    u = UltronLights(make_cfg(), client=None, cloud_client=g.client(), interval=0.01, cloud_interval=0.05, max_seconds=30,
                     cloud_verify_wait=0)
    u.start()
    time.sleep(0.3)
    u.stop()
    assert g.controls[-2] == ("colorRgb", 0xFF0000) and g.rgb == 0xFF0000 and g.on and g.bright == 80


def wait_done(u):
    for _ in range(300):
        if not u.running:
            return
        time.sleep(0.01)


def test_a_bar_whose_off_command_was_refused_is_checked_and_switched_off():
    govee_cloud._cache.clear()
    g = FakeGovee(on=False, rgb=0x0A141E, bright=55)
    u = UltronLights(make_cfg(), client=None, cloud_client=g.client(), interval=0.01, cloud_interval=0.05, max_seconds=30,
                     cloud_verify_wait=0)
    u.start()
    time.sleep(0.2)
    g.drop_power = 2                              # the show used up Govee's allowance: the restore's power commands bounce
    u.stop()
    wait_done(u)
    assert not g.on and g.rgb == 0x0A141E and g.bright == 55


def test_a_bar_that_was_on_in_white_is_checked_back_to_its_white():
    govee_cloud._cache.clear()
    g = FakeGovee(on=True, rgb=0, bright=70, kelvin=2700)
    u = UltronLights(make_cfg(), client=None, cloud_client=g.client(), interval=0.01, cloud_interval=0.05, max_seconds=30,
                     cloud_verify_wait=0)
    u.start()
    time.sleep(0.2)
    u.stop()
    wait_done(u)
    assert g.on and g.kelvin == 2700 and g.bright == 70
