import datetime

from jarvis.brain import Brain, build_facts, clean

STATUS = {"sources": {
    "nuc": {"state": "ok", "data": {"cpu_percent": 12.4, "ram_percent": 42.5, "temp_c": 50.0}},
    "plex": {"state": "ok", "data": {"streams": 2}},
    "disks": {"state": "warn", "data": {"parity": "WARN", "pool": "OK", "free_gb": 4779.1}},
    "pihole": {"state": "ok", "data": {"blocked_today": 4633, "block_percent": 3.45, "blocking": True}},
    "smart_home": {"state": "ok", "data": {
        "lights": [{"name": "Office Panels", "on": True}, {"name": "Balcony", "on": False}],
        "speakers": [{"name": "Kitchen", "state": "playing", "volume": 30, "title": "Around the World",
                      "artist": "Daft Punk", "art": True},
                     {"name": "Office", "state": "off", "volume": None, "title": None, "artist": None, "art": False}]}},
}}
NOW = datetime.datetime(2026, 11, 19, 20, 40)


def test_facts_include_time_streams_music_and_lights():
    f = build_facts(STATUS, NOW)
    assert "20:40" in f and "Thursday" in f
    assert "2 Plex streams" in f
    assert "Kitchen" in f and "Around the World" in f and "Daft Punk" in f
    assert "Office Panels" in f and "Balcony" not in f.split("Lights on:")[1]


def test_facts_never_mention_the_disks():
    f = build_facts(STATUS, NOW).lower()
    assert "disk" not in f and "parity" not in f and "4779" not in f


def test_facts_cope_with_missing_sources():
    f = build_facts({"sources": {}}, NOW)
    assert "20:40" in f


def test_clean_strips_markdown_newlines_and_caps_length():
    assert clean("**Hello** there,\n\nsir!") == "Hello there, sir!"
    long = "One sentence. " * 60
    out = clean(long)
    assert len(out) <= 300 and out.endswith(".")


class FakePost:
    def __init__(self, text="Splendid, sir.", fail=False):
        self.calls, self.text, self.fail = [], text, fail

    def __call__(self, url, payload):
        self.calls.append((url, payload))
        if self.fail:
            raise OSError("down")
        return {"message": {"content": self.text}}


def test_reply_sends_persona_facts_and_question_and_returns_clean_text():
    post = FakePost("**Splendid**, sir.")
    b = Brain("http://x/api/chat", "m", post=post)
    out = b.reply("how is the house", "FACT LINE", now=1000.0)
    assert out == "Splendid, sir."
    url, payload = post.calls[0]
    msgs = payload["messages"]
    assert msgs[0]["role"] == "system" and "FACT LINE" in msgs[0]["content"] and "JARVIS" in msgs[0]["content"]
    assert msgs[-1] == {"role": "user", "content": "how is the house"}
    assert payload["stream"] is False and payload["model"] == "m"


def test_recent_exchanges_are_remembered_but_old_ones_are_not():
    post = FakePost("Quite so.")
    b = Brain("u", "m", post=post)
    b.reply("first question", "F", now=1000.0)
    b.reply("and again?", "F", now=1060.0)
    roles = [m["content"] for m in post.calls[1][1]["messages"]]
    assert "first question" in roles and "Quite so." in roles
    b.reply("much later", "F", now=1000.0 + 3600)
    assert "first question" not in [m["content"] for m in post.calls[2][1]["messages"]]


def test_a_down_model_returns_none_instead_of_raising():
    assert Brain("u", "m", post=FakePost(fail=True)).reply("hi", "F", now=1.0) is None


def test_an_empty_answer_returns_none():
    assert Brain("u", "m", post=FakePost("   ")).reply("hi", "F", now=1.0) is None


def test_persona_demands_24_hour_time():
    from jarvis.brain import PERSONA
    assert "24-hour" in PERSONA


def test_clean_converts_twelve_hour_times_to_24_hour():
    from jarvis.brain import clean
    assert clean("It is 8:40 PM, sir.") == "It is 20:40, sir."
    assert clean("Half past 7:05 a.m. already.") == "Half past 07:05 already."
    assert clean("Dinner at 6 pm.") == "Dinner at 18:00."
    assert clean("It is 12:15 AM.") == "It is 00:15."
    assert clean("Noon is 12:00 pm.") == "Noon is 12:00."
    assert clean("The time is 20:40.") == "The time is 20:40."


def test_a_guest_answers_in_its_own_persona_and_never_as_jarvis():
    for who, name in (("edith", "E.D.I.T.H."), ("friday", "F.R.I.D.A.Y."), ("jocasta", "JOCASTA"), ("ultron", "ULTRON")):
        post = FakePost("Hello.")
        b = Brain("http://x/api/chat", "m", post=post)
        b.reply("say something", "FACT LINE", now=1000.0, speaker=who)
        system = post.calls[0][1]["messages"][0]["content"]
        assert name in system and "JARVIS" not in system and "FACT LINE" in system
        assert "24-hour" in system and "ONE or TWO short spoken sentences" in system      # same house rules for everyone


def test_no_speaker_is_still_jarvis():
    post = FakePost("Splendid.")
    Brain("http://x/api/chat", "m", post=post).reply("hi", "F", now=1000.0)
    assert "JARVIS" in post.calls[0][1]["messages"][0]["content"]


def test_every_ai_is_told_whose_house_it_is_by_name():
    for speaker in (None, "edith", "friday", "jocasta", "ultron"):
        post = FakePost("ok")
        Brain("u", "m", post=post, owner="Alex").reply("hi", "F", now=1.0, speaker=speaker)
        system = post.calls[0][1]["messages"][0]["content"]
        assert "Alex" in system and "Bob" not in system and "{owner}" not in system


def test_brain_config_reads_the_owner_name():
    from types import SimpleNamespace
    from jarvis.brain import from_config
    b = from_config(SimpleNamespace(raw={"owner": {"name": "Alex"}, "brain": {"enabled": True}}))
    assert b.owner == "Alex"
