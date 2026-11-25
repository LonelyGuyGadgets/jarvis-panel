import time

from fastapi.testclient import TestClient

from jarvis.app import create_app
from jarvis.actions import ActionResult
from jarvis.config import ActionSpec, Config
from jarvis.status import SourceResult

SMART = {"lights": {"Office Panels": "light.a", "Balcony": "light.b"}, "speakers": {"Kitchen": "media_player.k"}}


def make(heard, states=None, boom=False):
    ran = []
    actions = {}
    for n in ("lights_off_Office Panels", "lights_off_Balcony", "lights_on_Balcony", "pause_pihole", "volume_up_Kitchen",
              "restart_plex"):
        actions[n] = ActionSpec(argv=None, internal=n, changes_state=True, exclusive=False)
    cfg = Config(actions=actions, secrets={}, bind_host="127.0.0.1", port=1, raw={"smart_home": SMART})

    def handler(name):
        def f():
            ran.append(name)
            if boom:
                raise RuntimeError("x")
            return ActionResult("done", "ok")
        return f
    internal = {n: handler(n) for n in actions}
    states = states or {"nuc": "ok"}
    sources = {k: (lambda c, s=s: SourceResult(s, {}, time.time())) for k, s in states.items()}
    app = create_app(cfg, sources, internal, transcriber=lambda wav: heard, voice=None)
    return TestClient(app, base_url="http://127.0.0.1"), ran


def post(client, body=b"RIFFxxxx"):
    return client.post("/api/command", content=body, headers={"content-type": "audio/wav"})


def test_command_runs_matching_actions_and_reports_what_to_say():
    c, ran = make("Jarvis, turn off the office lights")
    r = post(c)
    assert r.status_code == 200
    j = r.json()
    assert ran == ["lights_off_Office Panels"] and j["say"] == ["lights_off"] and j["heard"].startswith("Jarvis")


def test_speech_without_wake_word_does_nothing():
    c, ran = make("turn off the office lights")
    j = post(c).json()
    assert ran == [] and j["say"] == [] and j["ignored"] is True


def test_empty_transcript_is_ignored():
    c, ran = make("")
    assert post(c).json()["ignored"] is True and ran == []


def test_destructive_commands_never_run():
    c, ran = make("Jarvis, restart Plex")
    j = post(c).json()
    assert ran == [] and j["say"] == ["huh"]


def test_failed_action_says_failed_not_success():
    c, ran = make("Jarvis, pause the ads", boom=True)
    assert post(c).json()["say"] == ["failed"]


def test_status_request_reports_all_nominal_when_healthy():
    c, _ = make("Jarvis, status report", {"nuc": "ok", "plex": "ok"})
    assert post(c).json()["say"] == ["all_nominal"]


def test_status_request_names_each_problem():
    c, _ = make("Jarvis, status report", {"nuc": "ok", "disks": "warn", "plex": "offline"})
    assert sorted(post(c).json()["say"]) == ["offline_plex", "warn_disks"]


def test_command_without_transcriber_is_503():
    cfg = Config(actions={}, secrets={}, bind_host="127.0.0.1", port=1, raw={})
    app = create_app(cfg, {"nuc": lambda c: SourceResult("ok", {}, time.time())}, {}, transcriber=None, voice=None)
    assert TestClient(app, base_url="http://127.0.0.1").post("/api/command", content=b"x").status_code == 503


def test_bad_audio_is_400():
    c, _ = make("x")
    def bad(wav):
        raise ValueError("expected 16 kHz mono 16-bit wav")
    c.app.state.transcriber = bad
    assert post(c, b"garbage").status_code == 400


def test_oversized_upload_is_413():
    c, _ = make("Jarvis")
    assert post(c, b"x" * (2 * 1024 * 1024)).status_code == 413


def test_status_carries_the_latest_voice_exchange_for_the_panel():
    c, _ = make("Jarvis, turn off the office lights")
    assert c.get("/api/status").json()["voice"] is None
    post(c)
    v1 = c.get("/api/status").json()["voice"]
    assert v1["say"] == ["lights_off"] and v1["heard"].startswith("Jarvis") and v1["id"] == 1
    post(c)
    assert c.get("/api/status").json()["voice"]["id"] == 2


def test_ignored_speech_does_not_reach_the_panel():
    c, _ = make("so anyway I told him no")
    post(c)
    assert c.get("/api/status").json()["voice"] is None


def test_a_switch_request_sets_who_is_in_control_and_tells_the_panel():
    c, ran = make("Jarvis, let me talk to Edith")
    j = post(c).json()
    assert j["kind"] == "switch" and j["who"] == "edith" and ran == []
    s = c.get("/api/status").json()
    assert s["voice"]["kind"] == "switch" and s["voice"]["who"] == "edith" and s["control"] == "edith"


def test_asking_for_jarvis_back_clears_control():
    c, _ = make("Jarvis, bring back Jarvis")
    c.post("/api/control", json={"speaker": "friday"})
    assert c.get("/api/status").json()["control"] == "friday"
    assert post(c).json()["who"] == "jarvis"
    assert c.get("/api/status").json()["control"] is None


def test_the_panel_reports_who_is_in_control_and_junk_is_refused():
    c, _ = make("")
    assert c.post("/api/control", json={"speaker": "ultron"}).status_code == 200
    assert c.get("/api/status").json()["control"] == "ultron"
    assert c.post("/api/control", json={"speaker": None}).status_code == 200
    assert c.get("/api/status").json()["control"] is None
    assert c.post("/api/control", json={"speaker": "hal9000"}).status_code == 422


def test_commands_are_acknowledged_in_the_voice_of_whoever_is_in_control():
    c, ran = make("Edith, turn off the office lights")
    c.post("/api/control", json={"speaker": "edith"})
    j = post(c).json()
    assert ran == ["lights_off_Office Panels"] and j["say"] == [] and j["reply"] == "Lights off."
    v = c.get("/api/status").json()["voice"]
    assert v["reply"] == "Lights off." and v["reply_voice"] == "e_"


def test_edith_is_deaf_to_her_name_while_jarvis_has_the_panel():
    c, ran = make("Edith, turn off the office lights")
    assert post(c).json()["ignored"] is True and ran == []


def test_mute_command_is_published_for_every_panel_and_runs_nothing():
    c, ran = make("Jarvis, mute")
    j = post(c).json()
    assert j["kind"] == "mute" and j["on"] is False and ran == []
    v = c.get("/api/status").json()["voice"]
    assert v["kind"] == "mute" and v["on"] is False
