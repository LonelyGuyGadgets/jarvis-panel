import time

from fastapi.testclient import TestClient

from jarvis.app import create_app
from jarvis.config import Config
from jarvis.status import SourceResult


class FakeVoice:
    def __init__(self):
        self.spoken = []

    def wav(self, key):
        return b"RIFFkey"

    def synth(self, text, prefix=""):
        self.spoken.append((text, prefix))
        return b"RIFF" + text.encode()


class FakeBrain:
    def __init__(self, answer="Splendid, sir."):
        self.answer, self.asked = answer, []

    def reply(self, question, facts, now, speaker=None):
        self.asked.append((question, facts, speaker))
        return self.answer


def make(heard, brain, art=None):
    cfg = Config(actions={}, secrets={}, bind_host="127.0.0.1", port=1, raw={"smart_home": {"lights": {}, "speakers": {}}})
    voice = FakeVoice()
    app = create_app(cfg, {"nuc": lambda c: SourceResult("ok", {"cpu_percent": 5}, time.time())}, {},
                     transcriber=lambda wav: heard, voice=voice, brain=brain, art_fetch=art)
    return TestClient(app, base_url="http://127.0.0.1"), voice


def post(c):
    return c.post("/api/command", content=b"RIFFxxxx", headers={"content-type": "audio/wav"})


def test_a_question_goes_to_the_brain_and_comes_back_as_a_spoken_reply():
    brain = FakeBrain()
    c, voice = make("Jarvis, how is the house doing?", brain)
    j = post(c).json()
    assert j["kind"] == "chat" and j["reply"] == "Splendid, sir." and j["say"] == []
    assert brain.asked[0][0].lower().startswith("how is the house")
    assert "Jarvis" not in brain.asked[0][0]
    v = c.get("/api/status").json()["voice"]
    assert v["reply_id"] == 1 and v["reply"] == "Splendid, sir."
    r = c.get("/api/voice/reply/1")
    assert r.status_code == 200 and r.content == b"RIFFSplendid, sir." and r.headers["content-type"] == "audio/wav"


def test_the_brain_never_gets_to_run_anything_even_when_asked_to():
    c, _ = make("Jarvis, restart plex", FakeBrain("I couldn't possibly."))
    j = post(c).json()
    assert j["kind"] == "chat"


def test_a_dead_brain_falls_back_to_i_didnt_catch_that():
    c, _ = make("Jarvis, what is the meaning of life", FakeBrain(answer=None))
    assert post(c).json()["say"] == ["huh"]


def test_no_brain_configured_keeps_the_old_huh():
    c, _ = make("Jarvis, tell me a joke", None)
    assert post(c).json()["say"] == ["huh"]


def test_builtin_commands_still_win_over_the_brain():
    brain = FakeBrain()
    c, _ = make("Jarvis, status report", brain)
    assert post(c).json()["kind"] == "status" and brain.asked == []


def test_unknown_reply_id_is_404():
    c, _ = make("Jarvis, hi there friend", FakeBrain())
    assert c.get("/api/voice/reply/7").status_code == 404


def test_art_proxy_serves_images_and_404s_otherwise():
    c, _ = make("x", None, art=lambda name: (b"IMG", "image/jpeg") if name == "Kitchen" else None)
    ok = c.get("/api/art/Kitchen")
    assert ok.status_code == 200 and ok.content == b"IMG" and ok.headers["content-type"] == "image/jpeg"
    assert c.get("/api/art/Nope").status_code == 404


def test_quip_endpoint_has_jarvis_say_something_unprompted():
    brain = FakeBrain("Another day, another terabyte, sir.")
    c, _ = make("x", brain)
    r = c.post("/api/quip")
    assert r.status_code == 200 and r.json()["reply"] == "Another day, another terabyte, sir."
    assert "witty" in brain.asked[0][0].lower() or "quip" in brain.asked[0][0].lower()
    v = c.get("/api/status").json()["voice"]
    assert v["reply_id"] == 1 and v["kind"] == "chat"


def test_quip_without_a_brain_is_503_and_with_a_dead_brain_502():
    c, _ = make("x", None)
    assert c.post("/api/quip").status_code == 503
    c2, _ = make("x", FakeBrain(answer=None))
    assert c2.post("/api/quip").status_code == 502


def test_audio_level_is_posted_by_the_listener_and_read_by_the_panel():
    c, _ = make("x", None)
    assert c.get("/api/audio-level").json() == {"level": 0.0, "fresh": False}
    assert c.post("/api/audio-level", json={"level": 73.5}).status_code == 200
    got = c.get("/api/audio-level").json()
    assert got == {"level": 73.5, "fresh": True}


def test_audio_level_rejects_junk_and_goes_stale():
    c, _ = make("x", None)
    for bad in ({"level": "loud"}, {"level": -1}, {"level": 1e9}, {}, {"level": None}):
        assert c.post("/api/audio-level", json=bad).status_code == 400
    assert c.get("/api/audio-level").json()["fresh"] is False


def test_a_tap_quip_for_a_guest_is_asked_and_spoken_as_that_guest():
    brain = FakeBrain("Isn't this fun!")
    c, voice = make("", brain)
    assert c.post("/api/quip", json={"speaker": "edith"}).json()["reply"] == "Isn't this fun!"
    question, _, speaker = brain.asked[0]
    assert speaker == "edith" and "butler" not in question
    v = c.get("/api/status").json()["voice"]
    assert v["reply_voice"] == "e_"
    assert c.get("/api/voice/reply/%d" % v["reply_id"]).status_code == 200
    assert voice.spoken[-1] == ("Isn't this fun!", "e_")


def test_each_speaker_has_its_own_voice_prefix_and_jarvis_has_none():
    for who, prefix in (("friday", "f_"), ("jocasta", "jo_"), ("ultron", "u_")):
        brain = FakeBrain("Hm.")
        c, voice = make("", brain)
        c.post("/api/quip", json={"speaker": who})
        assert c.get("/api/status").json()["voice"]["reply_voice"] == prefix
        c.get("/api/voice/reply/1")
        assert voice.spoken[-1][1] == prefix
    brain = FakeBrain("Splendid.")
    c, voice = make("", brain)
    c.post("/api/quip")
    assert brain.asked[0][2] is None and "reply_voice" not in c.get("/api/status").json()["voice"]


def test_an_unknown_speaker_is_refused():
    c, _ = make("", FakeBrain())
    assert c.post("/api/quip", json={"speaker": "skynet"}).status_code == 422
