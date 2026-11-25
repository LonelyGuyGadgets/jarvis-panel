import time

from fastapi.testclient import TestClient

from jarvis import briefing
from jarvis.app import create_app
from jarvis.config import Config
from jarvis.status import SourceResult


def body(**sources):
    return {"sources": {n: {"state": s, "data": d} for n, (s, d) in sources.items()}}


HEALTHY = dict(
    nuc=("ok", {"cpu_percent": 12.4, "ram_percent": 40.0, "temp_c": 51.6}),
    plex=("ok", {"streams": 2}),
    disks=("ok", {"pool": "OK", "parity": "OK", "free_gb": 900}),
    pihole=("ok", {"blocked_today": 4321, "blocking": True}),
    smart_home=("ok", {"lights": [{"name": "A", "on": True}, {"name": "B", "on": False}, {"name": "C", "on": False}],
                       "speakers": []}),
)


def test_all_healthy_says_nominal_then_one_clause_per_system_with_a_real_detail():
    text = briefing.build(body(**HEALTHY))
    assert text.startswith("All systems nominal.")
    assert "N U C" in text and "12 percent" in text and "52 degrees" in text
    assert "Plex is up with 2 streams" in text
    assert "disk array is healthy" in text
    assert "4321 ads" in text
    assert "1 of 3 lights are on" in text


def test_a_single_stream_and_no_streams_read_naturally():
    one = briefing.build(body(**{**HEALTHY, "plex": ("ok", {"streams": 1})}))
    none = briefing.build(body(**{**HEALTHY, "plex": ("ok", {"streams": 0})}))
    unknown = briefing.build(body(**{**HEALTHY, "plex": ("ok", {"streams": None})}))
    assert "Plex is up with 1 stream." in one
    assert "Plex is up and nobody is watching" in none
    assert "Plex is up." in unknown


def test_problems_come_first_and_the_nominal_line_is_dropped():
    sick = {**HEALTHY, "pihole": ("offline", {}), "plex": ("offline", {})}
    text = briefing.build(body(**sick))
    assert not text.startswith("All systems nominal")
    assert text.index("Pie hole is offline") < text.index("The N U C")
    assert "Plex is offline" in text


def test_the_known_failing_disk_is_not_nagged_but_an_offline_array_is():
    warn = briefing.build(body(**{**HEALTHY, "disks": ("warn", {"pool": "OK", "parity": "FAIL"})}))
    assert "disk" not in warn.lower()
    assert warn.startswith("All systems nominal.")
    off = briefing.build(body(**{**HEALTHY, "disks": ("offline", {})}))
    assert "The disk array is offline." in off


def test_unconfigured_systems_are_left_out_and_paused_pihole_is_flagged():
    text = briefing.build(body(**{**HEALTHY, "pihole": ("ok", {"blocked_today": 5, "blocking": False})}))
    assert "Pie hole is paused" in text


def test_nothing_to_report_is_still_a_sentence():
    assert briefing.build({"sources": {}}).startswith("No systems")


# ---- the endpoint

class FakeVoice:
    def wav(self, key):
        return b"RIFFkey"

    def synth(self, text, prefix=""):
        return b"RIFF" + text.encode()


def make():
    cfg = Config(actions={}, secrets={}, bind_host="127.0.0.1", port=1, raw={})
    srcs = {n: (lambda c, s=s, d=d: SourceResult(s, d, time.time())) for n, (s, d) in HEALTHY.items()}
    app = create_app(cfg, srcs, {}, voice=FakeVoice(), brain=None, transcriber=None)
    return TestClient(app, base_url="http://127.0.0.1")


def test_the_briefing_endpoint_publishes_a_spoken_reply_the_panel_can_fetch():
    c = make()
    r = c.post("/api/briefing")
    assert r.status_code == 200 and r.json()["reply"].startswith("All systems nominal.")
    v = c.get("/api/status").json()["voice"]
    assert v["reply_id"] == 1 and v["reply"] == r.json()["reply"] and v["kind"] == "chat"
    assert c.get("/api/voice/reply/1").status_code == 200


def test_a_second_briefing_right_after_is_not_repeated():
    c = make()
    assert c.post("/api/briefing").status_code == 200
    again = c.post("/api/briefing")
    assert again.status_code == 200 and again.json().get("skipped") is True
    assert c.get("/api/status").json()["voice"]["id"] == 1


def test_no_voice_configured_means_no_briefing():
    cfg = Config(actions={}, secrets={}, bind_host="127.0.0.1", port=1, raw={})
    c = TestClient(create_app(cfg, {}, {}, voice=None, brain=None, transcriber=None), base_url="http://127.0.0.1")
    assert c.post("/api/briefing").status_code == 503
