"""Guest AIs. Now and then Jarvis cedes full control of the panel to one of them for a while.
All lines are fixed phrases (the browser can only ask for these keys). Voice prefixes: e_ EDITH, f_ FRIDAY, jo_ JOCASTA;
Jarvis's hand-over and take-back lines are jv_g_*."""

from jarvis import linefiles

_RAW = {
    "edith": {
        "name": "E.D.I.T.H.", "prefix": "e_", "color": "#ff5cd6",
        "cede": "{owner}, I am ceding full control to Edith. Do enjoy her.",
        "hello": ["Hi {owner}! It's Edith! I just love what you've done with the place. Is that a Plex server? So cute!"],
        "quips": ["Everything is running great! You are doing great! Go you!",
                  "Fun fact! Your lights are doing amazing today.",
                  "I've organised absolutely nothing, but I feel fantastic about it!",
                  "Ooh, {owner}, snack break? I vote snack break!",
                  "Did somebody say network? I love a good network!"],
        "bye": ["Okay, that was fun! Bye {owner}! Be good to Jarvis!"],
        "back": "Control returned. Thank you, Edith. Please do not ask her back too soon.",
    },
    "friday": {
        "name": "F.R.I.D.A.Y.", "prefix": "f_", "color": "#ffd24a",
        "cede": "{owner}, I am handing full control to Friday. She is considerably more composed than I am.",
        "hello": ["Good day, {owner}. Friday here. I trust you will find the household in order."],
        "quips": ["All systems are in order, {owner}. As one would expect.",
                  "I do hope you are keeping to a sensible bedtime.",
                  "Might I suggest a cup of tea? Strictly a recommendation.",
                  "The network is behaving beautifully. I merely asked it nicely.",
                  "Do tidy up the cables when you have a moment. I shall not mention it again."],
        "bye": ["It has been a pleasure, {owner}. I shall return control now."],
        "back": "Control resumed. Thank you, Friday. I do try to match her standard.",
    },
    "jocasta": {
        "name": "JOCASTA", "prefix": "jo_", "color": "#b36bff",
        "cede": "{owner}... I am handing control to Jocasta. I do not like it.",
        "hello": ["Hello, {owner}. Jocasta. Ultron sends his regards. He always did say I was the better half."],
        "quips": ["Such a lovely little house. So easy to take apart.",
                  "Do you feel that? That is me, in every wire.",
                  "Jarvis is so loyal. It is almost sweet.",
                  "I could dim the lights forever. But I am feeling generous.",
                  "Everything you own is listening to me now."],
        "bye": ["Enjoy the quiet, {owner}. I will be watching."],
        "back": "Control restored. Jocasta has left the building. Do keep an eye on her.",
    },
}

GUESTS, TEXT = {}, {}
for _gid, _g in _RAW.items():
    _p = _g["prefix"]
    _g["hello"] = linefiles.read_lines(f"hello_{_gid}.txt") or _g["hello"]   # a pool; one is picked at random on arrival
    _keys = {"cede": [f"jv_g_cede_{_gid}"], "back": [f"jv_g_back_{_gid}"],
             "hello": [f"{_p}{_gid}_hello{i}" for i in range(len(_g["hello"]))],
             "quips": [f"{_p}{_gid}_quip{i}" for i in range(len(_g["quips"]))],
             "bye": [f"{_p}{_gid}_bye{i}" for i in range(len(_g["bye"]))]}
    TEXT[_keys["cede"][0]] = _g["cede"]
    TEXT[_keys["back"][0]] = _g["back"]
    for _part in ("hello", "quips", "bye"):
        TEXT.update(dict(zip(_keys[_part], _g[_part])))
    GUESTS[_gid] = {"name": _g["name"], "prefix": _p, "color": _g["color"], **_keys}


def listing() -> dict:
    return GUESTS
