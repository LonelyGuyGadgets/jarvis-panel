import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from jarvis.app import create_app
from jarvis.config import Config
from jarvis.status import SourceResult
from jarvis.voice import Voice, VoiceUnavailable, phrases


def test_phrases_cover_each_source_and_the_link():
    p = phrases()
    for key in ("online", "link_lost", "link_restored"):
        assert key in p
    for src in ("nuc", "plex", "disks", "pihole", "smart_home"):
        for kind in ("warn", "offline", "ok"):
            assert f"{kind}_{src}" in p
    assert all(text and text[0].isupper() and text.endswith((".", "?", "!")) for text in p.values())


class FakePiper:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, argv, input=None, **kw):
        self.calls.append((argv, input))
        if self.fail:
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        out = argv[argv.index("-f") + 1]
        with open(out, "wb") as f:
            f.write(b"RIFFfake-wav")
        return subprocess.CompletedProcess(argv, 0, "", "")


def make_voice(tmp_path, run=None, model=True):
    m = tmp_path / "voice.onnx"
    if model:
        m.write_bytes(b"x")
    return Voice(str(m), "piper", str(tmp_path / "cache"), run=run or FakePiper())


def test_wav_synthesises_the_fixed_phrase_and_caches_it(tmp_path):
    run = FakePiper()
    v = make_voice(tmp_path, run)
    assert v.wav("online") == b"RIFFfake-wav"
    assert v.wav("online") == b"RIFFfake-wav"
    assert len(run.calls) == 1
    argv, text = run.calls[0]
    assert argv[0] == "piper" and "-m" in argv and text == phrases()["online"]


def test_unknown_key_is_never_synthesised(tmp_path):
    run = FakePiper()
    with pytest.raises(KeyError):
        make_voice(tmp_path, run).wav("rm -rf")
    assert run.calls == []


def test_missing_model_is_unavailable_and_runs_nothing(tmp_path):
    run = FakePiper()
    with pytest.raises(VoiceUnavailable):
        make_voice(tmp_path, run, model=False).wav("online")
    assert run.calls == []


def test_failed_synthesis_is_unavailable_and_not_cached(tmp_path):
    v = make_voice(tmp_path, FakePiper(fail=True))
    with pytest.raises(VoiceUnavailable):
        v.wav("online")
    v.run = FakePiper()
    assert v.wav("online") == b"RIFFfake-wav"


def app_client(voice):
    cfg = Config(actions={}, secrets={}, bind_host="127.0.0.1", port=1, raw={})
    app = create_app(cfg, {"nuc": lambda c: SourceResult("ok", {}, time.time())}, {}, voice=voice)
    return TestClient(app, base_url="http://127.0.0.1")


def test_endpoint_serves_wav(tmp_path):
    r = app_client(make_voice(tmp_path)).get("/api/voice/online")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content == b"RIFFfake-wav"


def test_endpoint_unknown_key_is_404(tmp_path):
    assert app_client(make_voice(tmp_path)).get("/api/voice/whatever").status_code == 404


def test_endpoint_without_a_voice_is_503():
    assert app_client(None).get("/api/voice/online").status_code == 503


def test_endpoint_unavailable_voice_is_503(tmp_path):
    assert app_client(make_voice(tmp_path, model=False)).get("/api/voice/online").status_code == 503


def test_synth_speaks_arbitrary_server_side_text_without_caching_it(tmp_path):
    run = FakePiper()
    v = make_voice(tmp_path, run)
    assert v.synth("Good evening, sir.") == b"RIFFfake-wav"
    assert run.calls[0][1] == "Good evening, sir."
    v.synth("Good evening, sir.")
    assert len(run.calls) == 2


def test_synth_without_a_model_is_unavailable(tmp_path):
    with pytest.raises(VoiceUnavailable):
        make_voice(tmp_path, model=False).synth("hello")


def test_ultron_uses_his_own_voice_model_when_installed(tmp_path):
    run = FakePiper()
    alt = tmp_path / "ultron.onnx"
    alt.write_bytes(b"x")
    v = make_voice(tmp_path, run)
    v.ultron_model = str(alt)
    v.wav("u_n1_intro1")
    v.wav("jv_n1_mid1")
    u, j = run.calls[0][0], run.calls[1][0]
    assert u[u.index("-m") + 1] == str(alt)
    assert j[j.index("-m") + 1] == v.model


def test_ultron_falls_back_to_the_main_voice_when_his_model_is_missing(tmp_path):
    run = FakePiper()
    v = make_voice(tmp_path, run)
    v.ultron_model = str(tmp_path / "nope.onnx")
    v.wav("u_n1_intro1")
    argv = run.calls[0][0]
    assert argv[argv.index("-m") + 1] == v.model


def test_synth_in_a_guests_voice_uses_its_model_and_pace(tmp_path):
    run = FakePiper()
    v = make_voice(tmp_path, run)
    alt = tmp_path / "edith.onnx"
    alt.write_text("x")
    v.alt_models = {"e_": str(alt)}
    v.synth("Hello!", "e_")
    argv = run.calls[0][0]
    assert str(alt) in argv and "--length-scale" in argv and argv[argv.index("--length-scale") + 1] == "0.9"
    v.synth("Hello.")
    assert str(alt) not in run.calls[1][0]                          # no prefix: Jarvis's own voice


def test_spoken_lines_use_the_owners_name_from_config():
    named = phrases("Alex")
    assert any("Alex" in t for t in named.values())
    for table in (named, phrases()):
        assert not any("{owner}" in t or "Bob" in t for t in table.values())


def test_voice_config_sets_the_owner_name():
    from types import SimpleNamespace
    from jarvis import voice as voice_mod
    cfg = SimpleNamespace(raw={"owner": {"name": "Alex"}, "voice": {"model": "/x.onnx"}})
    try:
        voice_mod.from_config(cfg)
        assert any("Alex" in t for t in phrases().values())
    finally:
        voice_mod.OWNER = "Boss"
