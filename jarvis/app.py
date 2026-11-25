import datetime
import os
import threading
import time
from typing import Literal, Optional

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, StrictBool

from jarvis import climate
from jarvis import guests as guests_mod
from jarvis import ultron as ultron_mod
from jarvis.ultron_lights import UltronLights
from jarvis.actions import actions_running, last_results, run_action
from jarvis.sources import disks, govee_cloud, homeassistant, nuc, pihole, plex
from jarvis import brain as brain_mod, briefing as briefing_mod, commands, voice as voice_mod

BRIEFING_COOLDOWN = 20.0   # seconds between boot briefings
from jarvis.status import cached, collect_all, health_percent

STATUS_CODES = {"done": 200, "busy": 409, "refused": 400, "failed": 502}
DEFAULT_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


class LightShowBody(BaseModel):
    mode: Literal["start", "stop"]


class QuipBody(BaseModel):
    speaker: Optional[Literal["edith", "friday", "jocasta", "ultron"]] = None   # who is in control; None is Jarvis


class ControlBody(BaseModel):
    speaker: Optional[Literal["edith", "friday", "jocasta", "ultron"]] = None   # who has the panel; None is Jarvis


VOICE_PREFIX = {"edith": "e_", "friday": "f_", "jocasta": "jo_", "ultron": "u_"}


class ActionBody(BaseModel):
    confirm: StrictBool = False


def smart_home_source(cfg):
    """Home Assistant's lights plus any Govee cloud lights (older models without local control) as extra buttons."""
    result = homeassistant.read(cfg)
    extra = govee_cloud.read_lights(cfg)
    if extra and result.state == "ok":
        result.data["lights"] = list(result.data.get("lights", [])) + extra
    if result.state == "ok":
        result.data["climate"] = climate.current(cfg)
    return result


def default_sources() -> dict:
    return {
        "nuc": nuc.read,
        "plex": plex.read,
        "disks": cached(disks.read, ttl=60),
        "pihole": pihole.read,
        "smart_home": smart_home_source,
    }


def default_internal(cfg) -> dict:
    table = {"pause_pihole": lambda: pihole.pause(cfg, minutes=5), "resume_pihole": lambda: pihole.resume(cfg)}
    table.update(homeassistant.handlers(cfg))
    table.update(govee_cloud.handlers(cfg))
    return table


def create_app(cfg, sources: Optional[dict] = None, internal: Optional[dict] = None,
               web_dir: Optional[str] = None, status_ttl: float = 2.0, voice=None,
               transcriber="config", brain="config", art_fetch=None, ultron_lights="config") -> FastAPI:
    sources = sources if sources is not None else default_sources()
    internal = internal if internal is not None else default_internal(cfg)
    web_dir = web_dir or DEFAULT_WEB_DIR
    if voice is None:
        voice = voice_mod.from_config(cfg)
    if brain == "config":
        brain = brain_mod.from_config(cfg)
    if art_fetch is None:
        art_fetch = lambda name: homeassistant.fetch_art(cfg, name)
    if ultron_lights == "config":
        ultron_lights = UltronLights(cfg)
    replies: dict = {}   # id -> (text, voice prefix), the last few things an AI said off the cuff
    if transcriber == "config":
        transcriber = commands.from_config(cfg)
    app = FastAPI(title="Jarvis panel")
    app.state.transcriber = transcriber
    if hasattr(transcriber, "warm"):   # load the speech model now, not on the first command
        threading.Thread(target=transcriber.warm, daemon=True).start()
    # Only answer requests addressed to the panel itself; blocks DNS-rebinding pages.
    hosts = [cfg.bind_host, "localhost", "127.0.0.1"] + list(cfg.raw.get("allowed_hosts", []))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    # Block cross-site requests. A web page on another site can make a browser send
    # "simple" POSTs (text/plain, form data) with no CORS preflight, so refuse those
    # types, and refuse any request a browser marks as coming from another site.
    SIMPLE_TYPES = ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data")

    @app.middleware("http")
    async def refuse_cross_site(request, call_next):
        if request.url.path.startswith("/api") and request.method not in ("GET", "HEAD", "OPTIONS"):
            ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype in SIMPLE_TYPES:
                return JSONResponse({"status": "refused", "message": "unsupported content type"}, status_code=415)
            if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
                return JSONResponse({"status": "refused", "message": "cross-site request"}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin != "null":
                from urllib.parse import urlsplit
                if urlsplit(origin).netloc != request.headers.get("host", ""):
                    return JSONResponse({"status": "refused", "message": "cross-site request"}, status_code=403)
            elif origin == "null":
                return JSONResponse({"status": "refused", "message": "cross-site request"}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def revalidate_pages(request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-cache"
        return response
    source_cache: dict = {}
    memo = {"at": 0.0, "body": None}
    lock = threading.Lock()
    last_voice = {"v": None, "n": 0}
    started = time.time()   # lets the panel notice a server restart and put Jarvis back in charge
    control = {"who": None}   # which AI has the panel (None is Jarvis); the panel reports it, voice switches set it

    @app.get("/api/status")
    def status():
        with lock:
            now = time.time()
            if memo["body"] is None or now - memo["at"] > status_ttl:
                results = collect_all(cfg, sources, source_cache, now)
                memo["body"] = {
                    "health": health_percent(results),
                    "generated_at": now,
                    "sources": {n: {"state": r.state, "data": r.data, "as_of": r.as_of}
                                for n, r in results.items()},
                }
                memo["at"] = time.time()  # measured after collecting, so a slow pass is not born expired
            return {**memo["body"], "running": actions_running(), "last_actions": last_results(),
                    "voice": last_voice["v"], "control": control["who"], "started": started}

    @app.post("/api/action/{name}")
    def action(name: str, body: ActionBody):
        result = run_action(name, body.confirm, cfg, internal)
        with lock:
            memo["body"] = None  # next status read reflects the change
        return JSONResponse({"status": result.status, "message": result.message},
                            status_code=STATUS_CODES[result.status])

    async def ask_brain(question: str, speaker=None):
        body = await run_in_threadpool(status)
        facts = brain_mod.build_facts(body, datetime.datetime.now())
        if speaker:
            return await run_in_threadpool(brain.reply, question, facts, time.time(), speaker)
        return await run_in_threadpool(brain.reply, question, facts, time.time())

    def publish_reply(heard: str, answer: str, speaker=None):
        """Make the panel speak this: the browser sees it in /api/status and fetches /api/voice/reply/<id>."""
        last_voice["n"] += 1
        n = last_voice["n"]
        replies[n] = (answer, VOICE_PREFIX.get(speaker, ""))
        for old in [k for k in replies if k <= n - 8]:
            del replies[old]
        last_voice["v"] = {"id": n, "heard": heard, "say": [], "kind": "chat", "reply": answer, "reply_id": n}
        if speaker:
            last_voice["v"]["reply_voice"] = VOICE_PREFIX[speaker]

    level = {"v": 0.0, "at": 0.0}

    @app.post("/api/control")
    def set_control(body: ControlBody):
        """The panel tells the server whenever the AI in control changes (taps, a guest's arrival, a long-press)."""
        control["who"] = body.speaker
        return {"speaker": control["who"]}

    @app.post("/api/audio-level")
    async def audio_level_in(request: Request):
        """The Surface listener reports how loud the room is (a number, never audio) so the core can pulse to it."""
        try:
            v = float((await request.json())["level"])
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"status": "refused", "message": "bad level"}, status_code=400)
        if not 0 <= v <= 100000:
            return JSONResponse({"status": "refused", "message": "bad level"}, status_code=400)
        level["v"], level["at"] = v, time.time()
        return {"status": "done"}

    @app.get("/api/audio-level")
    def audio_level_out():
        fresh = time.time() - level["at"] < 1.5
        return {"level": level["v"] if fresh else 0.0, "fresh": fresh}

    @app.post("/api/quip")
    async def quip(body: Optional[QuipBody] = None):
        """Tap the core: whoever is in control (Jarvis unless told otherwise) says something witty about the house."""
        if brain is None:
            return JSONResponse({"status": "failed", "message": "brain not enabled"}, status_code=503)
        speaker = body.speaker if body else None
        ask = ("Say one short, witty quip about the lab or the evening, as a butler would." if not speaker
               else "Say one short, witty quip about the lab or the evening, in your own style.")
        answer = await ask_brain(ask, speaker)
        if not answer:
            return JSONResponse({"status": "failed", "message": "no answer"}, status_code=502)
        publish_reply("", answer, speaker)
        return {"reply": answer}

    briefed = {"at": 0.0}

    @app.post("/api/briefing")
    async def briefing_endpoint():
        """The panel's first look after powering on: Jarvis reads out where every system stands.
        Built from live status (no LLM) and spoken through the same reply channel as a chat answer."""
        if voice is None:
            return JSONResponse({"status": "failed", "message": "voice not configured"}, status_code=503)
        if time.time() - briefed["at"] < BRIEFING_COOLDOWN:   # two screens booting together, or a reload loop
            return {"skipped": True}
        briefed["at"] = time.time()
        with lock:
            memo["body"] = None   # read the systems now, not a cached pass
        text = briefing_mod.build(await run_in_threadpool(status))
        publish_reply("", text)
        return {"reply": text}

    @app.get("/api/guests/scripts")
    async def guest_scripts():
        return guests_mod.listing()

    @app.post("/api/ultron/lights")
    def ultron_lights_show(body: LightShowBody):
        """The browser asks for the red blinking light show during an Ultron takeover, and for it to end."""
        if body.mode == "start":
            return {"started": bool(ultron_lights.start())}
        ultron_lights.stop()
        return {"stopped": True}

    @app.get("/api/ultron/scripts")
    async def ultron_scripts():
        return ultron_mod.listing()

    MAX_CLIP = 1024 * 1024  # ~30 s of 16 kHz mono 16-bit audio

    @app.post("/api/command")
    async def command(request: Request):
        """Speech clip in, spoken-reply keys out. Only voice-allowlisted actions can ever run from here."""
        heard_by = app.state.transcriber
        if heard_by is None:
            return JSONResponse({"status": "failed", "message": "voice commands not enabled"}, status_code=503)
        body = await request.body()
        if len(body) > MAX_CLIP:
            return JSONResponse({"status": "refused", "message": "clip too long"}, status_code=413)
        try:
            text = await run_in_threadpool(heard_by, body)
        except ValueError as exc:
            return JSONResponse({"status": "refused", "message": str(exc)}, status_code=400)
        except Exception:
            return JSONResponse({"status": "failed", "message": "transcription failed"}, status_code=502)
        speaker = control["who"]
        parsed = commands.parse(text, cfg, speaker) if text else None
        if parsed is None:
            return {"heard": text, "ignored": True, "say": [], "kind": "ignored"}
        if parsed.kind == "switch":
            control["who"] = None if parsed.who == "jarvis" else parsed.who
            last_voice["n"] += 1
            last_voice["v"] = {"id": last_voice["n"], "heard": text, "say": [], "kind": "switch", "who": parsed.who}
            return {"heard": text, "ignored": False, "say": [], "kind": "switch", "who": parsed.who}
        if parsed.kind == "mute":                         # panels (the kiosk and any browser) mute or unmute their own voice
            last_voice["n"] += 1
            last_voice["v"] = {"id": last_voice["n"], "heard": text, "say": [], "kind": "mute", "on": parsed.on}
            return {"heard": text, "ignored": False, "say": [], "kind": "mute", "on": parsed.on}
        say = list(parsed.say)
        if parsed.kind == "reply" and say == ["huh"] and brain is not None:
            answer = await ask_brain(commands.question(text), speaker)
            if answer:
                publish_reply(text, answer, speaker)
                return {"heard": text, "ignored": False, "say": [], "kind": "chat", "reply": answer}
        if parsed.kind == "status":
            with lock:
                memo["body"] = None
            levels = [(n, r["state"]) for n, r in (await run_in_threadpool(status))["sources"].items()
                      if n in voice_mod.SPOKEN and r["state"] != "unconfigured"]
            say = [f"{'warn' if st in ('warn', 'stale') else 'offline'}_{n}" for n, st in levels if st != "ok"] or ["all_nominal"]
        elif parsed.kind == "actions":
            ok = True
            for name in parsed.actions:
                if not commands.is_voice_action(name):
                    ok = False
                    continue
                try:
                    result = await run_in_threadpool(run_action, name, True, cfg, internal)
                    ok = ok and result.status == "done"
                except Exception:
                    ok = False
            with lock:
                memo["body"] = None
            if not ok:
                say = ["failed"]
        if speaker and say:   # Jarvis's fixed phrases are in his voice: when an AI has the panel it says them itself
            table = voice_mod.phrases()
            reply = " ".join(table[k] for k in say if k in table)
            publish_reply(text, reply, speaker)
            return {"heard": text, "ignored": False, "say": [], "kind": parsed.kind, "reply": reply}
        last_voice["n"] += 1
        last_voice["v"] = {"id": last_voice["n"], "heard": text, "say": say, "kind": parsed.kind}
        return {"heard": text, "ignored": False, "say": say, "kind": parsed.kind}

    @app.get("/api/voice/reply/{rid}")
    def reply_audio(rid: int):
        got = replies.get(rid)
        if got is None:
            return JSONResponse({"status": "refused", "message": "no such reply"}, status_code=404)
        text, prefix = got
        if voice is None:
            return JSONResponse({"status": "failed", "message": "voice not configured"}, status_code=503)
        try:
            return Response(voice.synth(text, prefix) if prefix else voice.synth(text), media_type="audio/wav")
        except voice_mod.VoiceUnavailable as exc:
            return JSONResponse({"status": "failed", "message": str(exc)}, status_code=503)

    @app.get("/api/art/{speaker}")
    def art(speaker: str):
        got = art_fetch(speaker)
        if got is None:
            return JSONResponse({"status": "refused", "message": "no art"}, status_code=404)
        return Response(got[0], media_type=got[1], headers={"Cache-Control": "max-age=30"})

    @app.get("/api/voice/{key}")
    def say(key: str):
        if key not in voice_mod.phrases():
            return JSONResponse({"status": "refused", "message": "unknown phrase"}, status_code=404)
        if voice is None:
            return JSONResponse({"status": "failed", "message": "voice not configured"}, status_code=503)
        try:
            data = voice.wav(key)
        except voice_mod.VoiceUnavailable as exc:
            return JSONResponse({"status": "failed", "message": str(exc)}, status_code=503)
        return Response(data, media_type="audio/wav")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(web_dir, "index.html"))

    if os.path.isdir(web_dir):
        app.mount("/static", StaticFiles(directory=web_dir), name="static")
    return app
