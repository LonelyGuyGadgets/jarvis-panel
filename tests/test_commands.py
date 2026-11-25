import pytest

from jarvis.commands import is_voice_action, parse
from jarvis.config import Config
from jarvis.voice import phrases

LIGHTS = ["Bedroom Lamp", "Office Panels", "LR Floor Lamps", "Office Floor Lamp", "Office Ceiling",
          "Bedroom Ceiling", "Balcony"]
SPEAKERS = ["Office", "Living Room", "Kitchen", "Soundbar", "Bedroom"]


def cfg():
    smart = {"lights": {n: "light.x" for n in LIGHTS}, "speakers": {n: "media_player.x" for n in SPEAKERS}}
    return Config(actions={}, secrets={}, bind_host="x", port=1, raw={"smart_home": smart})


def run(text):
    return parse(text, cfg())


def off(*names):
    return sorted(f"lights_off_{n}" for n in names)


def test_speech_without_the_wake_word_is_ignored():
    assert run("turn off the office lights") is None
    assert run("what a lovely day it is") is None
    assert run("") is None


@pytest.mark.parametrize("text", ["Jarvis", "Hey Jarvis.", "okay, Jarvis!", "Jervis"])
def test_wake_word_alone_gets_a_yes(text):
    p = run(text)
    assert p.kind == "reply" and p.actions == [] and p.say == ["yes"]


def test_a_misheard_wake_word_still_counts():
    assert sorted(run("Jervis, pause the ads").actions) == ["pause_pihole"]


def test_office_lights_off_hits_every_office_light():
    p = run("Jarvis, turn off the office lights.")
    assert p.kind == "actions" and sorted(p.actions) == off("Office Panels", "Office Floor Lamp", "Office Ceiling")
    assert p.say == ["lights_off"]


def test_living_room_floor_lamps_on_uses_the_lr_name():
    p = run("Jarvis, turn on the living room floor lamps")
    assert p.actions == ["lights_on_LR Floor Lamps"] and p.say == ["lights_on"]


def test_all_lights_and_bare_lights_off():
    for text in ("Jarvis, turn off all the lights", "Jarvis, lights off"):
        assert sorted(run(text).actions) == off(*LIGHTS)


def test_word_order_off_at_the_end():
    assert sorted(run("Jarvis, turn the bedroom lights off").actions) == off("Bedroom Lamp", "Bedroom Ceiling")


def test_a_named_light_that_does_not_exist_is_not_understood():
    p = run("Jarvis, turn off the garage lights")
    assert p.actions == [] and p.say == ["huh"]


@pytest.mark.parametrize("text", ["Jarvis, pause the ads", "Jarvis pause ads", "Jarvis, pause Pie hole", "jarvis pause blocking"])
def test_pause_ads(text):
    p = run(text)
    assert p.actions == ["pause_pihole"] and p.say == ["ads_paused"]


def test_volume_commands_name_the_speaker():
    assert run("Jarvis, volume up in the kitchen").actions == ["volume_up_Kitchen"]
    assert run("Jarvis, turn down the soundbar").actions == ["volume_down_Soundbar"]
    assert run("Jarvis, make the living room louder").actions == ["volume_up_Living Room"]


def test_play_pause_a_speaker():
    assert run("Jarvis, pause the music in the office").actions == ["play_pause_Office"]
    assert run("Jarvis, pause the kitchen speaker").actions == ["play_pause_Kitchen"]


def test_volume_without_a_speaker_asks_which():
    p = run("Jarvis, volume up")
    assert p.actions == [] and p.say == ["which_speaker"]


def test_status_request():
    for text in ("Jarvis, status report", "Jarvis, how are things", "Jarvis what's the system status"):
        assert run(text).kind == "status"


@pytest.mark.parametrize("text", ["Jarvis, restart Plex", "Jarvis, run the SnapRAID sync", "Jarvis, restart Samba",
                                  "Jarvis, check the disks", "Jarvis, open the pod bay doors"])
def test_nothing_risky_or_unknown_is_ever_run(text):
    p = run(text)
    assert p.actions == [] and p.say == ["huh"]


def test_every_action_the_parser_can_produce_is_voice_allowed():
    samples = ["Jarvis, turn off all the lights", "Jarvis, turn on the office lights", "Jarvis, pause the ads",
               "Jarvis, volume up in the kitchen", "Jarvis, pause the music in the office"]
    for text in samples:
        assert run(text).actions and all(is_voice_action(a) for a in run(text).actions)


def test_voice_allowlist_excludes_everything_destructive():
    for name in ("restart_plex", "restart_samba", "snapraid_sync", "disk_check", "lights_toggle_Balcony"):
        assert not is_voice_action(name)
    for name in ("pause_pihole", "lights_on_X", "lights_off_X", "volume_up_X", "volume_down_X", "play_pause_X"):
        assert is_voice_action(name)


def test_every_reply_the_parser_uses_is_a_speakable_phrase():
    known = phrases()
    for text in ["Jarvis", "Jarvis, turn on the office lights", "Jarvis, turn off the lights", "Jarvis, pause the ads",
                 "Jarvis, volume up", "Jarvis, volume up in the kitchen", "Jarvis, restart plex"]:
        for key in run(text).say:
            assert key in known, key
    for key in ("failed", "all_nominal"):
        assert key in known


# ---- handing the panel to another AI by voice

@pytest.mark.parametrize("text,who", [
    ("Jarvis, let me talk to Edith", "edith"), ("Jarvis, let me talk to EDITH.", "edith"),
    ("Jarvis, put Friday on", "friday"), ("Jarvis, switch to Jocasta", "jocasta"),
    ("Jarvis, bring up Ultron", "ultron"), ("Jarvis, let me talk to Ultron", "ultron"),
    ("Jarvis, I want to speak to Edit", "edith"), ("Jarvis, get me Friday", "friday"),
    ("Jarvis, bring back Jarvis", "jarvis"), ("Jarvis, let me talk to Jarvis", "jarvis"),
])
def test_asking_to_talk_to_an_ai_is_a_switch(text, who):
    p = run(text)
    assert p.kind == "switch" and p.who == who and p.actions == []


def test_ordinary_commands_are_not_mistaken_for_a_switch():
    assert run("Jarvis, turn off the office lights").kind == "actions"
    assert run("Jarvis, how are things").kind == "status"
    assert run("Jarvis, what is on Friday").kind != "switch"


def test_the_ai_in_control_can_be_woken_by_name_as_well_as_jarvis():
    assert parse("Edith, turn off the office lights", cfg(), "edith").kind == "actions"
    assert parse("Jarvis, turn off the office lights", cfg(), "edith").kind == "actions"
    assert parse("Edith", cfg(), "edith").say == ["yes"]
    p = parse("Edith, let me talk to Friday", cfg(), "edith")
    assert p.kind == "switch" and p.who == "friday"
    p = parse("Edith, bring back Jarvis", cfg(), "edith")
    assert p.kind == "switch" and p.who == "jarvis"


def test_only_the_ai_in_control_answers_to_its_name():
    assert parse("Edith, turn off the office lights", cfg()) is None            # Jarvis in control: Edith is not listening
    assert parse("Friday, turn off the office lights", cfg(), "edith") is None   # someone else's name


@pytest.mark.parametrize("text,on", [("Jarvis, mute", False), ("Jarvis, be quiet", False), ("hey Jarvis shush", False),
                                     ("Jarvis, turn the sound off", False), ("Jarvis, unmute", True), ("Jarvis, sound on", True)])
def test_mute_and_unmute_commands(text, on):
    p = run(text)
    assert p.kind == "mute" and p.on is on and not p.actions


@pytest.mark.parametrize("text", ["Jarvis, mute the speakers", "Jarvis, make the music quieter", "Jarvis, turn the volume down"])
def test_room_speaker_phrases_are_not_the_panels_mute(text):
    p = run(text)
    assert p is None or p.kind != "mute"
