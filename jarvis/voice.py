"""Spoken alerts. The browser can only ask for a phrase by key from a fixed list, never for arbitrary
text; each phrase is synthesised once with Piper (a local neural voice) and cached on disk."""
import os
import subprocess
import threading

from jarvis import guests, ultron

SPOKEN = {"nuc": "the N U C", "plex": "Plex", "disks": "the disk array", "pihole": "Pie hole",
          "smart_home": "the smart home"}


# EDITH is perky (a little quicker), FRIDAY stately (a little slower)
SPEECH_TWEAKS = {"e_": ["--length-scale", "0.9"], "f_": ["--length-scale", "1.1"], "jo_": ["--length-scale", "1.05"]}


class VoiceUnavailable(Exception):
    pass


def _cap(text: str) -> str:
    return text[0].upper() + text[1:]


OWNER = "Boss"   # whose house this is; the spoken lines address them by name ([owner] name in config.toml)


def phrases(owner: str = None) -> dict:
    table = {"online": "Systems online.", "link_lost": "Connection to the server lost.",
             "link_restored": "Connection restored.",
             # replies to voice commands
             "yes": "Yes?", "huh": "I didn't catch that.", "which_speaker": "Which speaker?", "ack": "Done.",
             "lights_on": "Lights on.", "lights_off": "Lights off.", "ads_paused": "Ads paused for five minutes.",
             "failed": "That didn't work.", "all_nominal": "All systems nominal.",
             # greetings and easter eggs
             "good_morning": "Good morning, {owner}. Systems online.", "good_afternoon": "Good afternoon, {owner}. Systems online.",
             "good_evening": "Good evening, {owner}. Systems online.", "party_mode": "Party protocol engaged."}
    table.update(ultron.TEXT)
    table.update(guests.TEXT)
    for src, label in SPOKEN.items():
        table[f"warn_{src}"] = f"Warning. {_cap(label)} needs attention."
        table[f"offline_{src}"] = f"{_cap(label)} is offline."
        table[f"ok_{src}"] = f"{_cap(label)} has recovered."
    name = owner or OWNER
    return {k: v.replace("{owner}", name) for k, v in table.items()}


class Voice:
    def __init__(self, model: str, piper_bin: str, cache_dir: str, run=subprocess.run):
        self.model, self.piper_bin, self.cache_dir, self.run = model, piper_bin, cache_dir, run
        self.ultron_model = None   # optional second, deeper voice for the Ultron takeover
        self.alt_models = {}       # voice-prefix -> model for the guest AIs (e_ EDITH, f_ FRIDAY, jo_ JOCASTA)
        self._lock = threading.Lock()

    def synth(self, text: str, prefix: str = "") -> bytes:
        """Speak server-generated text (an AI's replies) in the voice of `prefix` (a guest or Ultron); Jarvis by default.
        Never exposed to callers as a text parameter."""
        if not os.path.exists(self.model):
            raise VoiceUnavailable("voice model not installed")
        os.makedirs(self.cache_dir, exist_ok=True)
        tmp = os.path.join(self.cache_dir, f"reply-{threading.get_ident()}.wav")
        with self._lock:
            try:
                done = self.run(self._argv(prefix, tmp), input=text, text=True, capture_output=True, timeout=60)
            except (OSError, subprocess.SubprocessError) as exc:
                raise VoiceUnavailable(str(exc))
            if done.returncode != 0 or not os.path.exists(tmp):
                raise VoiceUnavailable("synthesis failed")
            with open(tmp, "rb") as f:
                data = f.read()
            os.remove(tmp)
            return data

    def _argv(self, key: str, out: str) -> list:
        model = self.model
        if key.startswith("u_") and self.ultron_model and os.path.exists(self.ultron_model):
            model = self.ultron_model
        for prefix, alt in self.alt_models.items():
            if key.startswith(prefix) and os.path.exists(alt):
                model = alt
        argv = [self.piper_bin, "-m", model, "-f", out]
        for prefix, tweak in SPEECH_TWEAKS.items():
            if key.startswith(prefix):
                argv += tweak
        return argv

    def wav(self, key: str) -> bytes:
        text = phrases()[key]  # KeyError for anything off the list
        if not os.path.exists(self.model):
            raise VoiceUnavailable("voice model not installed")
        path = os.path.join(self.cache_dir, f"{key}.wav")
        with self._lock:
            if not os.path.exists(path):
                os.makedirs(self.cache_dir, exist_ok=True)
                tmp = path + ".part"
                try:
                    done = self.run(self._argv(key, tmp), input=text, text=True,
                                    capture_output=True, timeout=60)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise VoiceUnavailable(str(exc))
                if done.returncode != 0 or not os.path.exists(tmp):
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    raise VoiceUnavailable("synthesis failed")
                os.replace(tmp, path)
        with open(path, "rb") as f:
            return f.read()


def from_config(cfg):
    """A Voice if [voice] is configured, else None (the panel then just stays silent)."""
    global OWNER
    OWNER = (cfg.raw.get("owner") or {}).get("name") or "Boss"
    section = cfg.raw.get("voice")
    if not section or not section.get("model"):
        return None
    v = Voice(section["model"], section.get("piper", "piper"),
              section.get("cache_dir", os.path.join(os.path.expanduser("~"), "jarvis", "voice-cache")))
    v.ultron_model = section.get("ultron_model")
    v.alt_models = dict(section.get("models", {}))
    return v
