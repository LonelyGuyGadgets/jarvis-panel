"""Reads the spoken-line files in jarvis/lines/ (plain text, easy to add to). Every line is still a fixed, pre-written
phrase: the browser can only ask for them by key, so nothing here can make the panel say anything unexpected."""
import os
import re

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lines")
_LINE = re.compile(r"^(intro|mid|jwin|uwin) (jv|u): (.+)$")
PARTS = ("intro", "mid", "jwin", "uwin")


def _rows(name: str):
    with open(os.path.join(DIR, name), encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            line = raw.strip()
            if line and not line.startswith("#"):
                yield n, line


def read_lines(name: str) -> list:
    """One spoken line per row; blank rows and # comments are skipped."""
    return [line for _, line in _rows(name)]


def read_scripts(name: str) -> dict:
    """Battle scripts: `== id` starts one, then `part speaker: text` rows. -> {id: {part: [(speaker, text), ...]}}"""
    scripts, cur = {}, None
    for n, line in _rows(name):
        if line.startswith("== "):
            cur = scripts[line[3:].strip()] = {p: [] for p in PARTS}
            continue
        m = _LINE.match(line)
        if cur is None or not m:
            raise ValueError(f"{name} line {n}: expected '== id' or 'part speaker: text', got {line!r}")
        cur[m.group(1)].append((m.group(2), m.group(3)))
    for sid, s in scripts.items():
        if len(s["intro"]) < 2 or len(s["mid"]) < 4 or not s["jwin"] or not s["uwin"]:
            raise ValueError(f"{name} script {sid}: needs 2+ intro, 4+ mid, a jwin and a uwin line")
    return scripts
