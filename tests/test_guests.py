import time

from fastapi.testclient import TestClient

from jarvis import guests
from jarvis.app import create_app
from jarvis.config import Config
from jarvis.status import SourceResult
from jarvis.voice import Voice, phrases
from tests.test_voice import FakePiper, make_voice


def test_the_three_guest_ais_exist_with_their_own_voice_prefix():
    assert set(guests.GUESTS) == {"edith", "friday", "jocasta"}
    assert {g["prefix"] for g in guests.GUESTS.values()} == {"e_", "f_", "jo_"}


def test_every_guest_has_a_complete_script():
    for gid, g in guests.GUESTS.items():
        assert g["cede"] and g["back"], gid
        assert all(k.startswith("jv_g_") for k in g["cede"] + g["back"]), gid     # Jarvis hands over and takes back
        assert g["hello"] and len(g["quips"]) >= 4 and g["bye"], gid
        for k in g["hello"] + g["quips"] + g["bye"]:
            assert k.startswith(g["prefix"]), (gid, k)


def test_all_guest_keys_are_unique_speakable_phrases():
    keys = [k for g in guests.GUESTS.values() for part in ("cede", "hello", "quips", "bye", "back") for k in g[part]]
    assert len(keys) == len(set(keys))
    p = phrases()
    for k in keys:
        assert k in p and p[k][0].isupper() and p[k].endswith((".", "?", "!")), k


def test_endpoint_lists_the_guests_for_the_browser():
    cfg = Config(actions={}, secrets={}, bind_host="127.0.0.1", port=1, raw={})
    app = create_app(cfg, {"nuc": lambda c: SourceResult("ok", {}, time.time())}, {})
    j = TestClient(app, base_url="http://127.0.0.1").get("/api/guests/scripts").json()
    assert set(j) == {"edith", "friday", "jocasta"}
    assert j["edith"]["quips"]
    # shown names carry the acronym dots (E.D.I.T.H., F.R.I.D.A.Y.); Jocasta is not an acronym
    assert [j[g]["name"] for g in ("edith", "friday", "jocasta")] == ["E.D.I.T.H.", "F.R.I.D.A.Y.", "JOCASTA"]


def test_each_guest_speaks_in_their_own_voice_model_when_installed(tmp_path):
    run = FakePiper()
    v = make_voice(tmp_path, run)
    for pre in ("e_", "f_", "jo_"):
        m = tmp_path / f"{pre}.onnx"
        m.write_bytes(b"x")
        v.alt_models[pre] = str(m)
    v.wav("e_edith_hello0")
    v.wav("f_friday_hello0")
    v.wav("jo_jocasta_hello0")
    v.wav("jv_g_cede_edith")
    models = [c[0][c[0].index("-m") + 1] for c in run.calls]
    assert models[0].endswith("e_.onnx") and models[1].endswith("f_.onnx") and models[2].endswith("jo_.onnx")
    assert models[3] == v.model                     # Jarvis keeps his own voice


def test_a_missing_guest_model_falls_back_to_the_main_voice(tmp_path):
    run = FakePiper()
    v = make_voice(tmp_path, run)
    v.alt_models["e_"] = str(tmp_path / "missing.onnx")
    v.wav("e_edith_hello0")
    argv = run.calls[0][0]
    assert argv[argv.index("-m") + 1] == v.model


def test_edith_talks_a_touch_faster_and_friday_a_touch_slower(tmp_path):
    run = FakePiper()
    v = make_voice(tmp_path, run)
    v.wav("e_edith_hello0")
    v.wav("f_friday_hello0")
    e, f = run.calls[0][0], run.calls[1][0]
    assert float(e[e.index("--length-scale") + 1]) < 1.0 < float(f[f.index("--length-scale") + 1])


def test_each_guest_has_a_pool_of_different_arrival_lines():
    for gid, g in guests.GUESTS.items():
        lines = [guests.TEXT[k] for k in g["hello"]]
        assert len(lines) >= 20 and len(set(lines)) == len(lines), gid
        assert all(5 < len(t) <= 220 and "{" not in t.replace("{owner}", "") for t in lines), gid


def test_the_original_arrival_lines_are_still_first_in_each_pool():
    assert "Plex server" in guests.TEXT[guests.GUESTS["edith"]["hello"][0]]
    assert "household in order" in guests.TEXT[guests.GUESTS["friday"]["hello"][0]]
    assert "better half" in guests.TEXT[guests.GUESTS["jocasta"]["hello"][0]]
