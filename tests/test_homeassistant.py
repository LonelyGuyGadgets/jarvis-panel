import json

import httpx

from jarvis.config import Config
from jarvis.sources import homeassistant as ha

SMART = {
    "lights": {"desk": "light.govee_desk", "living": "light.govee_living"},
    "scenes": {"movie": "scene.movie_night"},
    "speakers": {"sonos": "media_player.sonos_den", "kitchen": "media_player.nest_kitchen"},
}


def make_cfg(token="tok", smart=SMART):
    secrets = {"homeassistant": {"token": token}} if token else {}
    raw = {"homeassistant": {"url": "http://ha.test"}, "smart_home": smart}
    return Config(actions={}, secrets=secrets, bind_host="x", port=1, raw=raw)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ha.test")


def test_missing_token_is_unconfigured_and_makes_no_call():
    reqs = []

    def handler(request):
        reqs.append(request)
        return httpx.Response(200, json=[])

    r = ha.read(make_cfg(token=None), client=client_for(handler))
    assert r.state == "unconfigured" and reqs == []


def test_read_maps_states():
    states = [
        {"entity_id": "light.govee_desk", "state": "on", "attributes": {"friendly_name": "Desk"}},
        {"entity_id": "light.govee_living", "state": "off", "attributes": {}},
        {"entity_id": "media_player.sonos_den", "state": "playing", "attributes": {"volume_level": 0.35}},
        {"entity_id": "media_player.nest_kitchen", "state": "idle", "attributes": {}},
        {"entity_id": "light.something_else", "state": "on", "attributes": {}},
    ]
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=states)

    r = ha.read(make_cfg(), client=client_for(handler))
    assert r.state == "ok"
    assert seen["auth"] == "Bearer tok"
    assert r.data["lights"] == [{"name": "desk", "on": True}, {"name": "living", "on": False}]
    assert r.data["speakers"] == [
        {"name": "sonos", "state": "playing", "volume": 35, "title": None, "artist": None, "art": False},
        {"name": "kitchen", "state": "idle", "volume": None, "title": None, "artist": None, "art": False},
    ]


def test_read_unreachable_is_offline():
    def handler(request):
        raise httpx.ConnectError("refused")

    assert ha.read(make_cfg(), client=client_for(handler)).state == "offline"


def test_call_posts_service_with_bearer_and_entity():
    reqs = []

    def handler(request):
        reqs.append(request)
        return httpx.Response(200, json=[])

    result = ha.call(make_cfg(), "light", "toggle", "light.govee_desk", client=client_for(handler))
    assert result.status == "done"
    assert reqs[0].url.path == "/api/services/light/toggle"
    assert reqs[0].headers["Authorization"] == "Bearer tok"
    assert json.loads(reqs[0].content) == {"entity_id": "light.govee_desk"}


def test_unlisted_entity_refused_and_never_sent():
    reqs = []

    def handler(request):
        reqs.append(request)
        return httpx.Response(200, json=[])

    result = ha.call(make_cfg(), "lock", "unlock", "lock.front_door", client=client_for(handler))
    assert result.status == "refused"
    assert reqs == []


def test_call_failure_reported():
    def handler(request):
        return httpx.Response(500)

    assert ha.call(make_cfg(), "light", "toggle", "light.govee_desk",
                   client=client_for(handler)).status == "failed"


def test_handlers_register_actions_for_configured_entities_only():
    cfg = make_cfg()
    handlers = ha.handlers(cfg)
    expected = {"lights_toggle_desk", "lights_toggle_living", "scene_movie",
                "lights_on_desk", "lights_off_desk", "lights_on_living", "lights_off_living",
                "volume_up_sonos", "volume_down_sonos", "play_pause_sonos",
                "volume_up_kitchen", "volume_down_kitchen", "play_pause_kitchen"}
    assert set(handlers) == expected
    assert set(cfg.actions) == expected
    assert all(cfg.actions[n].internal == n and cfg.actions[n].changes_state for n in expected)


def test_handlers_empty_when_nothing_configured():
    cfg = make_cfg(smart={})
    assert ha.handlers(cfg) == {} and cfg.actions == {}


def test_handler_calls_the_right_service():
    cfg = make_cfg()
    reqs = []

    def handler(request):
        reqs.append(request)
        return httpx.Response(200, json=[])

    h = ha.handlers(cfg, client=client_for(handler))
    h["volume_up_sonos"]()
    h["scene_movie"]()
    assert reqs[0].url.path == "/api/services/media_player/volume_up"
    assert json.loads(reqs[0].content) == {"entity_id": "media_player.sonos_den"}
    assert reqs[1].url.path == "/api/services/scene/turn_on"


GROUP = {"lights": {"floor": ["light.a", "light.b"]}}


def _states(a, b):
    return [{"entity_id": "light.a", "state": a, "attributes": {}},
            {"entity_id": "light.b", "state": b, "attributes": {}}]


def test_grouped_light_is_on_if_any_member_is_on():
    r = ha.read(make_cfg(smart=GROUP), client=client_for(lambda req: httpx.Response(200, json=_states("off", "on"))))
    assert r.data["lights"] == [{"name": "floor", "on": True}]
    r = ha.read(make_cfg(smart=GROUP), client=client_for(lambda req: httpx.Response(200, json=_states("off", "off"))))
    assert r.data["lights"] == [{"name": "floor", "on": False}]


def _group_toggle(a, b):
    reqs = []

    def handler(request):
        reqs.append(request)
        return httpx.Response(200, json=_states(a, b))

    ha.handlers(make_cfg(smart=GROUP), client=client_for(handler))["lights_toggle_floor"]()
    return reqs[-1]


def test_group_toggle_turns_everything_off_when_any_is_on():
    last = _group_toggle("on", "off")
    assert last.url.path == "/api/services/light/turn_off"
    assert json.loads(last.content) == {"entity_id": ["light.a", "light.b"]}


def test_group_toggle_turns_everything_on_when_all_are_off():
    last = _group_toggle("off", "off")
    assert last.url.path == "/api/services/light/turn_on"
    assert json.loads(last.content) == {"entity_id": ["light.a", "light.b"]}


def test_list_with_an_unlisted_entity_is_refused_and_never_sent():
    reqs = []
    result = ha.call(make_cfg(smart=GROUP), "light", "turn_off", ["light.a", "light.evil"],
                     client=client_for(lambda req: reqs.append(req) or httpx.Response(200, json=[])))
    assert result.status == "refused" and reqs == []



def test_explicit_on_and_off_actions_call_the_matching_service():
    reqs = []
    h = ha.handlers(make_cfg(), client=client_for(lambda r: reqs.append(r) or httpx.Response(200, json=[])))
    h["lights_off_desk"]()
    h["lights_on_living"]()
    assert reqs[0].url.path == "/api/services/light/turn_off"
    assert json.loads(reqs[0].content) == {"entity_id": "light.govee_desk"}
    assert reqs[1].url.path == "/api/services/light/turn_on"


def test_explicit_on_off_for_a_grouped_light_targets_every_member():
    reqs = []
    h = ha.handlers(make_cfg(smart=GROUP), client=client_for(lambda r: reqs.append(r) or httpx.Response(200, json=[])))
    h["lights_off_floor"]()
    assert json.loads(reqs[0].content) == {"entity_id": ["light.a", "light.b"]}


def _playing_states(picture="/api/media_player_proxy/media_player.sonos_den?token=abc&cache=1"):
    return [{"entity_id": "media_player.sonos_den", "state": "playing",
             "attributes": {"volume_level": 0.35, "media_title": "Around the World", "media_artist": "Daft Punk",
                            "entity_picture": picture}},
            {"entity_id": "media_player.nest_kitchen", "state": "idle", "attributes": {}}]


def test_read_includes_now_playing_for_a_playing_speaker():
    r = ha.read(make_cfg(), client=client_for(lambda req: httpx.Response(200, json=_playing_states())))
    sonos = next(s for s in r.data["speakers"] if s["name"] == "sonos")
    assert sonos["title"] == "Around the World" and sonos["artist"] == "Daft Punk" and sonos["art"] is True
    kitchen = next(s for s in r.data["speakers"] if s["name"] == "kitchen")
    assert kitchen["title"] is None and kitchen["artist"] is None and kitchen["art"] is False


def test_art_for_a_configured_speaker_is_fetched_from_home_assistant_with_the_token():
    seen = []

    def handler(req):
        seen.append(req)
        if req.url.path == "/api/states":
            return httpx.Response(200, json=_playing_states())
        return httpx.Response(200, content=b"\x89PNGdata", headers={"content-type": "image/png"})

    got = ha.fetch_art(make_cfg(), "sonos", client=client_for(handler))
    assert got == (b"\x89PNGdata", "image/png")
    art_req = seen[-1]
    assert art_req.url.path == "/api/media_player_proxy/media_player.sonos_den"
    assert art_req.headers["authorization"] == "Bearer tok"


def test_art_for_an_unknown_speaker_or_without_a_picture_is_none_and_fetches_nothing():
    seen = []

    def handler(req):
        seen.append(req.url.path)
        return httpx.Response(200, json=_playing_states())

    assert ha.fetch_art(make_cfg(), "not-a-speaker", client=client_for(handler)) is None
    assert ha.fetch_art(make_cfg(), "kitchen", client=client_for(handler)) is None
    assert seen == ["/api/states"]


def test_art_url_must_stay_on_home_assistant():
    states = _playing_states(picture="http://evil.example/x.png")
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, json=states)

    assert ha.fetch_art(make_cfg(), "sonos", client=client_for(handler)) is None
    assert all("evil" not in u for u in seen)
