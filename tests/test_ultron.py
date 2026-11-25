import time

from fastapi.testclient import TestClient

from jarvis import ultron
from jarvis.app import create_app
from jarvis.config import Config
from jarvis.status import SourceResult
from jarvis.voice import phrases


def test_there_are_plenty_of_scripts_of_each_kind():
    assert len(ultron.NORMAL) >= 5
    assert len(ultron.REBEL) >= 3
    assert len(ultron.TAUNTS) >= 5


def test_every_script_is_complete_and_starts_with_jarvis_noticing():
    for sid, s in {**ultron.NORMAL, **ultron.REBEL}.items():
        assert len(s["intro"]) >= 2 and len(s["mid"]) >= 4, sid
        assert s["jwin"] and s["uwin"], sid
        assert s["intro"][0].startswith("jv_"), sid          # Jarvis speaks first
        assert any(k.startswith("u_") for k in s["intro"][1:2]), sid   # then Ultron answers


def test_victory_lines_belong_to_the_winner():
    for s in {**ultron.NORMAL, **ultron.REBEL}.values():
        assert all(k.startswith("jv_") for k in s["jwin"])
        assert all(k.startswith("u_") for k in s["uwin"])


def test_all_script_keys_are_unique_speakable_phrases():
    keys = [k for s in {**ultron.NORMAL, **ultron.REBEL}.values() for part in ("intro", "mid", "jwin", "uwin") for k in s[part]]
    keys += ultron.TAUNTS
    assert len(keys) == len(set(keys))
    p = phrases()
    for k in keys:
        assert k in p and p[k][0].isupper() and p[k].endswith((".", "?", "!")), k


def test_endpoint_lists_scripts_for_the_browser():
    cfg = Config(actions={}, secrets={}, bind_host="127.0.0.1", port=1, raw={})
    app = create_app(cfg, {"nuc": lambda c: SourceResult("ok", {}, time.time())}, {})
    r = TestClient(app, base_url="http://127.0.0.1").get("/api/ultron/scripts")
    assert r.status_code == 200
    j = r.json()
    assert set(j) == {"normal", "rebel", "taunts", "summon"}
    assert len(j["normal"]) == len(ultron.NORMAL) and "intro" in j["normal"][0]


def test_a_summoned_ultron_has_his_own_lines_that_are_all_speakable():
    from jarvis import ultron, voice
    lines = ultron.listing()["summon"]
    assert len(lines) == 3 and lines[0].startswith("jv_") and lines[1].startswith("u_") and lines[2].startswith("u_")   # hand over, arrive, leave
    assert all(k in voice.phrases() for k in lines)


def test_there_are_plenty_of_different_battles():
    assert len(ultron.NORMAL) >= 20 and len(ultron.REBEL) >= 10


def test_every_battle_line_is_short_enough_to_speak_and_has_no_stray_markup():
    for table in (ultron._RAW_NORMAL, ultron._RAW_REBEL):
        for sid, script in table.items():
            for part, rows in script.items():
                for spk, text in rows:
                    assert spk in ("jv", "u") and 3 < len(text) <= 140 and "{" not in text.replace("{owner}", ""), (sid, part, text)
