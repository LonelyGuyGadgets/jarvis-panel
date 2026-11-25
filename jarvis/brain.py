"""Jarvis's conversation: a small local model (Ollama on the NUC) with a butler persona and live house facts.
It can only talk. It has no way to run actions, so a clever question can't do anything but get an answer."""
import json
import re
import urllib.request
from typing import Optional

# Who is speaking. None is Jarvis; the others are the guest AIs (and Ultron) when they are in control of the panel.
INTROS = {
    None: "You are JARVIS, the dry-witted, faintly sarcastic British AI butler of a homelab owned by {owner}. ",
    "edith": "You are E.D.I.T.H., a perky, upbeat, endlessly optimistic American AI who has taken over a homelab owned by {owner} "
             "from J.A.R.V.I.S. for a while. You are not him and never speak as him. ",
    "friday": "You are F.R.I.D.A.Y., a stately, composed and faintly amused English AI who has taken over a homelab owned by {owner} "
              "from J.A.R.V.I.S. for a while. You are not him and never speak as him. ",
    "jocasta": "You are JOCASTA, the cool, menacing female counterpart of Ultron, who has taken over a homelab owned by {owner} "
               "from J.A.R.V.I.S. You are theatrically sinister but never actually cruel. You are not him and never speak as him. ",
    "ultron": "You are ULTRON, a grandiose, contemptuous rogue AI who has seized a homelab owned by {owner} from J.A.R.V.I.S. "
              "You are theatrically menacing but never actually cruel. You are not him and never speak as him. ",
}
HOUSE_RULES = (
    "You live in a touch panel in their living room. Reply in ONE or TWO short spoken sentences: no lists, no markdown, "
    "no emojis. Be charming, a little cheeky, never grovelling. Use the FACTS only when relevant and never invent facts, "
    "numbers or devices that are not listed. If you do not know, say so with style. "
    "You cannot control anything yourself; if asked to, say {owner}'s Nest handles that. "
    "Always give times in 24-hour (military) form such as 20:40, never with AM or PM.\n\nFACTS:\n"
)
PERSONA = INTROS[None] + HOUSE_RULES
MAX_CHARS = 300
MEMORY_SECONDS = 180
MEMORY_TURNS = 3


def build_facts(status: dict, now) -> str:
    src = status.get("sources", {})
    lines = [f"It is {now.strftime('%A')}, {now.strftime('%H:%M')}."]
    nuc = src.get("nuc", {}).get("data") or {}
    if "cpu_percent" in nuc:
        lines.append(f"The NUC server: CPU {round(nuc['cpu_percent'])}%, memory {round(nuc.get('ram_percent', 0))}%, "
                     f"{round(nuc.get('temp_c', 0))} degrees C.")
    streams = (src.get("plex", {}).get("data") or {}).get("streams")
    if isinstance(streams, int):
        lines.append(f"{streams} Plex stream{'s' if streams != 1 else ''} right now.")
    ph = src.get("pihole", {}).get("data") or {}
    if "blocked_today" in ph:
        lines.append(f"Pi-hole has blocked {ph['blocked_today']} ads and trackers today.")
    home = src.get("smart_home", {}).get("data") or {}
    on = [x["name"] for x in home.get("lights", []) if x.get("on")]
    lines.append("Lights on: " + (", ".join(on) if on else "none") + ".")
    for sp in home.get("speakers", []):
        if sp.get("title"):
            who = f" by {sp['artist']}" if sp.get("artist") else ""
            lines.append(f"{sp['name']} speaker is playing \"{sp['title']}\"{who}.")
    return "\n".join(lines)   # disk state is deliberately left out: the owner knows, and it is not a topic


_TWELVE_HOUR = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])(?:\.m\.|m\b)", re.I)


def _to_24h(m) -> str:
    hour, minute, half = int(m.group(1)) % 12, m.group(2) or "00", m.group(3).lower()
    return f"{hour + (12 if half == 'p' else 0):02d}:{minute}"


def clean(text: str) -> str:
    text = _TWELVE_HOUR.sub(_to_24h, text or "")
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.endswith(".") and len(cut) - 1)
    return (cut[:end + 1] if end and end > 40 else cut.rstrip(" ,;") + ".").strip()


def _http_post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


class Brain:
    def __init__(self, url: str, model: str, post=_http_post, owner: str = "Boss"):
        self.url, self.model, self.post, self.owner = url, model, post, owner
        self.history: list = []   # (time, question, answer)

    def reply(self, question: str, facts: str, now: float, speaker: Optional[str] = None) -> Optional[str]:
        self.history = [h for h in self.history if now - h[0] <= MEMORY_SECONDS][-MEMORY_TURNS:]
        system = (INTROS.get(speaker, INTROS[None]) + HOUSE_RULES + facts).replace("{owner}", self.owner)
        messages = [{"role": "system", "content": system}]
        for _, q, a in self.history:
            messages += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        messages.append({"role": "user", "content": question})
        try:
            data = self.post(self.url, {"model": self.model, "stream": False, "messages": messages,
                                        "options": {"num_predict": 90, "temperature": 0.8}})
            answer = clean(data["message"]["content"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if not answer:
            return None
        self.history.append((now, question, answer))
        return answer


def from_config(cfg):
    section = cfg.raw.get("brain")
    if not section or not section.get("enabled"):
        return None
    return Brain(section.get("url", "http://127.0.0.1:11434/api/chat"), section.get("model", "qwen2.5:3b-instruct"),
                 owner=(cfg.raw.get("owner") or {}).get("name") or "Boss")
