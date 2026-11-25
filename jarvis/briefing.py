"""The spoken status rundown Jarvis gives when the panel first powers on. Plain text built from the
status body (no LLM), so it is instant, predictable and can never invent a fact."""
from jarvis.voice import SPOKEN, _cap

ORDER = ["nuc", "plex", "disks", "pihole", "smart_home"]


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _hours(h) -> str:
    return "less than an hour ago" if h < 1 else f"{round(h)} hour{'' if round(h) == 1 else 's'} ago"


def _problem(name: str, state: str, data: dict):
    """A sentence if this system needs attention, else None. The failing parity disk is a known issue the
    owner does not want repeated, so the disk array is only called out when it is offline."""
    label = _cap(SPOKEN[name])
    if name == "disks":
        return f"{label} is offline." if state == "offline" else None
    if state == "offline":
        return f"{label} is offline."
    if name == "pihole" and state == "ok" and data.get("blocking") is False:
        return f"{label} is paused."
    if state in ("warn", "stale"):
        return f"{label} needs attention."
    return None


def _healthy(name: str, data: dict):
    """One short clause with a real number in it, for a system that is fine."""
    if name == "nuc":
        parts = []
        if data.get("cpu_percent") is not None:
            parts.append(f"{round(data['cpu_percent'])} percent processor load")
        if data.get("temp_c") is not None:
            parts.append(f"{round(data['temp_c'])} degrees")
        return "The N U C is running" + (" at " + " and ".join(parts) if parts else "") + "."
    if name == "plex":
        s = data.get("streams")
        if not isinstance(s, int):
            return "Plex is up."
        return "Plex is up and nobody is watching." if s == 0 else f"Plex is up with {_count(s, 'stream')}."
    if name == "disks":
        return "The disk array is healthy."
    if name == "pihole":
        return f"Pie hole has blocked {data['blocked_today']} ads today." if "blocked_today" in data else "Pie hole is up."
    if name == "smart_home":
        lights = data.get("lights") or []
        if not lights:
            return "The smart home is online."
        on = sum(1 for x in lights if x.get("on"))
        return f"{on} of {len(lights)} lights are on."
    return None


def build(status: dict) -> str:
    sources = status.get("sources", {})
    problems, good = [], []
    for name in ORDER:
        src = sources.get(name)
        if not src or src.get("state") == "unconfigured":
            continue
        data = src.get("data") or {}
        sentence = _problem(name, src.get("state"), data)
        if sentence:
            problems.append(sentence)
        if src.get("state") == "ok" and not sentence:
            line = _healthy(name, data)
            if line:
                good.append(line)
    if not problems and not good:
        return "No systems are reporting in."
    head = problems if problems else ["All systems nominal."]
    return " ".join(head + good)
