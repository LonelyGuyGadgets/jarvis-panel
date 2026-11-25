"""Voice commands: speech -> text (Whisper, local) -> one of a small fixed set of existing actions.

Nothing here can run anything that is not on the voice allowlist: lights on/off, pause Pi-hole ads,
speaker volume and play/pause. Restarts, SnapRAID and disk checks are deliberately not reachable by voice."""
import difflib
import io
import re
import threading
import wave
from dataclasses import dataclass, field
from typing import Optional

VOICE_PREFIXES = ("lights_on_", "lights_off_", "volume_up_", "volume_down_", "play_pause_")


def is_voice_action(name: str) -> bool:
    return name == "pause_pihole" or name.startswith(VOICE_PREFIXES)


@dataclass
class Parsed:
    kind: str                                   # "reply" | "actions" | "status" | "switch" | "mute"
    actions: list = field(default_factory=list)  # run these (allowlisted) actions
    say: list = field(default_factory=list)      # phrase keys; for "actions" spoken once they succeed
    who: Optional[str] = None                    # for "switch": jarvis | edith | friday | jocasta | ultron
    on: Optional[bool] = None                    # for "mute": True = sound on, False = muted


MUTE_WORDS = {"mute", "silence", "quiet", "shush", "hush"}
UNMUTE_WORDS = {"unmute"}
MUTE_SKIP = {"speaker", "speakers", "music", "tv", "plex", "volume"}   # those mean the room speakers, not the panel


FILLERS = {"hey", "ok", "okay", "yo", "hi"}
LIGHT_WORDS = {"light", "lights", "lamp", "lamps", "lighting"}
UP = {"up", "louder", "increase", "raise", "higher"}
DOWN = {"down", "quieter", "lower", "softer", "decrease"}
MEDIA = {"pause", "play", "resume", "stop", "unpause"}
LIGHT_STOP = {"turn", "switch", "put", "set", "the", "my", "in", "on", "off", "all", "please", "and", "to", "of", "a",
              "light", "lights", "lamp", "lamps", "lighting", "everything"}
SPEAKER_STOP = {"turn", "the", "my", "in", "on", "up", "down", "volume", "louder", "quieter", "softer", "make", "speaker",
                "speakers", "music", "please", "a", "of", "to", "lower", "raise", "increase", "decrease", "higher",
                "pause", "play", "resume", "stop", "unpause", "it", "sound", "audio"}


def _tokens(text: str) -> list:
    text = text.lower().replace("pi-hole", "pihole").replace("pie hole", "pihole").replace("pi hole", "pihole")
    return re.findall(r"[a-z0-9']+", text)


def _stem(tok: str) -> str:
    return tok[:-1] if len(tok) > 3 and tok.endswith("s") else tok


def _name_tokens(name: str) -> set:
    toks = _tokens(name)
    out = []
    for t in toks:
        out.extend(["living", "room"] if t == "lr" else [t])
    return {_stem(t) for t in out}


def _match(target: list, names) -> list:
    want = {_stem(t) for t in target}
    return [n for n in names if want <= _name_tokens(n)]


# The AIs that can be handed the panel, and how Whisper tends to mishear them.
AI_NAMES = {"edith": ("edith", "edit", "edie", "edyth", "eadith"), "friday": ("friday",),
            "jocasta": ("jocasta", "jacosta", "yocasta", "jocosta", "jokasta"),
            "ultron": ("ultron", "altron", "ultran", "ultrahn")}
SWITCH_CUES = {"talk", "speak", "switch", "put", "bring", "connect", "let", "hand", "summon", "wake", "activate",
               "change", "call", "back"}


def _who(tok: str) -> Optional[str]:
    for who, names in AI_NAMES.items():
        if tok in names or difflib.SequenceMatcher(None, tok, who).ratio() >= 0.8:
            return who
    return "jarvis" if difflib.SequenceMatcher(None, tok, "jarvis").ratio() >= 0.72 else None


def _wake(tokens: list, control: Optional[str] = None) -> Optional[list]:
    """The wake word is "Jarvis", or the name of the AI that currently has the panel."""
    i = 0
    while i < len(tokens) and tokens[i] in FILLERS:
        i += 1
    if i < len(tokens) and (_who(tokens[i]) == "jarvis" or (control and _who(tokens[i]) == control)):
        return tokens[i + 1:]
    return None


def _switch(rest: list) -> Optional[str]:
    words = set(rest)
    if not (words & SWITCH_CUES or ("me" in words and words & {"get", "give"})):
        return None
    return next((w for w in map(_who, rest) if w), None)


def question(text: str) -> str:
    """What was said after the wake word, as spoken (for handing to the conversational brain)."""
    pos = 0
    for m in re.finditer(r"[A-Za-z0-9']+", text):
        if m.group().lower() in FILLERS:
            pos = m.end()
            continue
        return text[m.end():].lstrip(" ,.!?:;-").strip()
    return ""


def _reply(*keys) -> Parsed:
    return Parsed("reply", [], list(keys))


def parse(text: str, cfg, control: Optional[str] = None) -> Optional[Parsed]:
    """None when the wake word was not said (the speech is simply ignored). `control` is the AI that has the panel
    now (None is Jarvis); it can be addressed by name as well as Jarvis."""
    rest = _wake(_tokens(text), control)
    if rest is None:
        return None
    if not rest:
        return _reply("yes")
    who = _switch(rest)
    if who:
        return Parsed("switch", [], [], who)
    words = set(rest)
    if not words & MUTE_SKIP:
        if words & UNMUTE_WORDS or ("on" in words and words & {"sound", "voice", "talking"}):
            return Parsed("mute", on=True)
        if words & MUTE_WORDS or ("off" in words and words & {"sound", "voice", "talking"}):
            return Parsed("mute", on=False)
    smart = cfg.raw.get("smart_home", {})
    lights, speakers = list(smart.get("lights", {})), list(smart.get("speakers", {}))

    if "pause" in words and words & {"ad", "ads", "pihole", "blocking", "blocker"}:
        return Parsed("actions", ["pause_pihole"], ["ads_paused"])
    if words & {"status", "report"} or ("how" in words and words & {"things", "everything", "system", "systems"}):
        return Parsed("status")

    verb_on, verb_off = "on" in words, "off" in words
    if words & LIGHT_WORDS or ((verb_on != verb_off) and words & {"turn", "switch"} and not words & {"up", "down"}):
        if verb_on == verb_off:
            return _reply("huh")
        target = [t for t in rest if t not in LIGHT_STOP]
        hits = lights if not target else _match(target, lights)
        if not hits:
            return _reply("huh")
        verb = "on" if verb_on else "off"
        return Parsed("actions", [f"lights_{verb}_{n}" for n in hits], [f"lights_{verb}"])

    direction = "up" if words & UP else "down" if words & DOWN else None
    wants_media = bool(words & MEDIA)
    if direction or wants_media:
        target = [t for t in rest if t not in SPEAKER_STOP]
        if not target:
            return _reply("which_speaker")
        hits = _match(target, speakers)
        if not hits:
            return _reply("huh")
        verb = f"volume_{direction}" if direction else "play_pause"
        return Parsed("actions", [f"{verb}_{n}" for n in hits], ["ack"])
    return _reply("huh")


# ---------------------------------------------------------------- speech to text

PROMPT = ("Jarvis, turn off the office lights. Jarvis, pause the ads. Jarvis, let me talk to Edith. "
          "Jarvis, switch to Friday. Let me talk to Jocasta. Bring up Ultron. Bring back Jarvis.")


def decode_wav(data: bytes):
    """16 kHz mono 16-bit WAV -> float32 samples, DC removed, 120 Hz high-passed, peak-normalised."""
    import numpy as np
    try:
        with wave.open(io.BytesIO(data)) as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, 16000):
                raise ValueError("expected 16 kHz mono 16-bit wav")
            pcm = w.readframes(w.getnframes())
    except wave.Error as exc:
        raise ValueError(str(exc))
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if a.size < 1600:
        raise ValueError("too short")
    a -= a.mean()
    spec = np.fft.rfft(a)
    spec[np.fft.rfftfreq(a.size, 1 / 16000) < 120] = 0
    a = np.fft.irfft(spec, a.size).astype(np.float32)
    peak = float(np.abs(a).max())
    return a * (0.8 / peak) if peak > 1 else a / 32768.0


class Transcriber:
    def __init__(self, model_name: str = "small.en"):
        self.model_name, self._model, self._lock = model_name, None, threading.Lock()

    def warm(self):
        with self._lock:
            self._load()

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        return self._model

    def __call__(self, wav: bytes) -> str:
        samples = decode_wav(wav)
        with self._lock:
            segments, _ = self._load().transcribe(samples, language="en", beam_size=5, initial_prompt=PROMPT)
            # Whisper invents text on noise; drop segments it itself rates as probably not speech.
            keep = [s.text.strip() for s in segments if s.no_speech_prob < 0.5 and s.avg_logprob > -1.0]
        return " ".join(keep).strip()


def from_config(cfg):
    section = cfg.raw.get("voice_commands")
    if not section or not section.get("enabled"):
        return None
    return Transcriber(section.get("model", "small.en"))
