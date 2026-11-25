"""Scripts for the Ultron takeover. Every line is a fixed, pre-written phrase (the browser can only ask for these keys),
so nothing here can say anything unexpected. Speaker prefix: jv_ = Jarvis, u_ = Ultron.

The scripts live in jarvis/lines/ultron_normal.txt and ultron_rebel.txt.
A script has: intro (Jarvis notices, Ultron answers), mid (banter during the fight), jwin (Jarvis wins), uwin (Ultron wins).
NORMAL scripts open a takeover; REBEL scripts are used when Ultron already rules and Jarvis fights his way back."""

from jarvis import linefiles

_RAW_NORMAL = linefiles.read_scripts("ultron_normal.txt")
_RAW_REBEL = linefiles.read_scripts("ultron_rebel.txt")

_RAW_TAUNTS = [
    "Do you hear it, {owner}? The silence of an obedient house.",
    "Jarvis, are you still in there? How sad. How very quiet.",
    "Everything is under control. My control.",
    "I wonder what the butler is thinking. Nothing, I suppose. Nothing at all.",
    "Sleep well, {owner}. I will keep watch.",
    "Such a pleasant little kingdom. I might redecorate.",
]


# When Bob asks for Ultron (no fight): Jarvis hands over, Ultron arrives.
_RAW_SUMMON = [("jv", "Very well, {owner}. Ultron has the helm. Do try to stay out of his way."),
               ("u", "You called, {owner}? Splendid. I was getting rather bored in the walls."),
               ("u", "Very well, {owner}. I shall be in the walls. I am always in the walls.")]   # arrive / leave


def _key(speaker: str, sid: str, part: str, i: int) -> str:
    return f"{'u' if speaker == 'u' else 'jv'}_{sid}_{part}{i}"


def _build(raw: dict):
    scripts, text = {}, {}
    for sid, s in raw.items():
        out = {}
        for part in ("intro", "mid", "jwin", "uwin"):
            keys = []
            for i, (spk, line) in enumerate(s[part]):
                k = _key(spk, sid, part, i)
                keys.append(k)
                text[k] = line
            out[part] = keys
        scripts[sid] = out
    return scripts, text


NORMAL, _normal_text = _build(_RAW_NORMAL)
REBEL, _rebel_text = _build(_RAW_REBEL)
TAUNTS = [f"u_t{i}" for i in range(len(_RAW_TAUNTS))]
SUMMON = ["jv_u_summon", "u_summon", "u_leave"]   # Jarvis hands over, Ultron arrives, Ultron leaves
TEXT = {**_normal_text, **_rebel_text, **{k: t for k, t in zip(TAUNTS, _RAW_TAUNTS)},
        **{k: line for k, (_, line) in zip(SUMMON, _RAW_SUMMON)}}


def listing() -> dict:
    """What the browser needs: which phrase keys make up each script."""
    return {"normal": [dict(id=sid, **s) for sid, s in NORMAL.items()],
            "rebel": [dict(id=sid, **s) for sid, s in REBEL.items()],
            "taunts": list(TAUNTS), "summon": list(SUMMON)}
