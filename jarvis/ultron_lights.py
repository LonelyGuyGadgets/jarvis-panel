"""Ultron's light show: every configured light goes red and blinks, then is put back exactly as it was:
on or off, in the colour and brightness it had. A light that was off gets the colour it last showed while lit.
Home Assistant lights blink about once a second; Govee cloud lights (older bars without LAN control) blink slowly
because Govee limits each device to ~10 commands a minute. Only configured lights are ever touched.

Govee bulbs drop a command that arrives right behind another, and Home Assistant shows the state it asked for
until its next poll of the bulb. So the restore is spaced out, then checked against the bulbs' real state a few
times after that poll, and anything still wrong is sent again.
A failsafe stops the show on its own so the lights can never be left blinking."""
import threading
import time
from typing import Optional

from jarvis.sources import govee_cloud as gc
from jarvis.sources import homeassistant as ha

RED = {"rgb_color": [255, 0, 0], "brightness": 255}
WHITE_KELVIN = 4000                         # only for a light whose colour was never seen


def _restore_params(params: dict) -> dict:
    """The colour to put a light back to: its own, or white when it was never seen lit (never Ultron's red)."""
    out = dict(params)
    if not (out.get("rgb_color") or out.get("color_temp_kelvin")):
        out["color_temp_kelvin"] = WHITE_KELVIN
    return out


def _light_ids(cfg) -> list:
    out: list = []
    for value in ha._smart(cfg).get("lights", {}).values():
        out.extend(ha._ids(value))
    return out


def _states(cfg, client) -> dict:
    resp = client.get("/api/states", headers={"Authorization": f"Bearer {ha._token(cfg)}"})
    resp.raise_for_status()
    return {s["entity_id"]: s for s in resp.json()}


def _snapshot(cfg, ids: list, client) -> dict:
    """entity id -> {"on": bool, "params": service data that recreates its colour/brightness}"""
    by_id = _states(cfg, client)
    ha.remember_colours([by_id[e] for e in ids if e in by_id])
    memory = ha.remembered_colours()
    snap = {}
    for eid in ids:
        st = by_id.get(eid, {})
        on = st.get("state") == "on"
        params = ha.colour_params(st.get("attributes", {}) or {}) if on else memory.get(eid, {})
        snap[eid] = {"on": on, "params": params}
    return snap


def _close(a, b, tol) -> bool:
    if isinstance(a, (list, tuple)):
        return b is not None and len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))
    return b is not None and abs(a - b) <= tol


def _matches(want: dict, st: dict) -> bool:
    """Is the bulb really how it was? Off lights only need to be off; lit ones need their colour too."""
    if (st.get("state") == "on") != want["on"]:
        return False
    if not want["on"]:
        return True
    a, p = st.get("attributes", {}) or {}, _restore_params(want["params"])
    if "color_temp_kelvin" in p and not _close(p["color_temp_kelvin"], a.get("color_temp_kelvin"), 150):
        return False
    if "rgb_color" in p and not _close(p["rgb_color"], a.get("rgb_color"), 12):
        return False
    return True


class UltronLights:
    def __init__(self, cfg, client=None, cloud_client=None, interval: float = 1.0,
                 cloud_interval: float = 7.0, max_seconds: float = 180, settle: float = 1.5,
                 verify_wait: float = 35.0, verify_rounds: int = 3, cloud_verify_wait: float = 40.0):
        self.cfg, self.client, self.cloud_client = cfg, client, cloud_client
        self.settle = settle
        self.interval, self.cloud_interval, self.max_seconds = interval, cloud_interval, max_seconds
        self.verify_wait, self.verify_rounds, self.cloud_verify_wait = verify_wait, verify_rounds, cloud_verify_wait
        self._stop = threading.Event()          # the show is over: restore
        self._abort = threading.Event()         # a new show wants the lights: stop checking the old restore
        self._threads: list = []
        self._restored: list = []               # one event per thread, set once its first restore is sent
        self._pending: dict = {}                # snapshots of a restore still being checked, reused by a new show
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def start(self) -> bool:
        with self._lock:
            if self.running:
                if not self._stop.is_set():
                    return False                # a show is already on
                self._abort.set()               # only the after-show checks are running: the new show takes over
                for t in self._threads:
                    t.join(timeout=30)
            pending, self._pending = self._pending, {}
            self._abort.clear()
            self._stop.clear()
            threads, restored = [], []
            ids = _light_ids(self.cfg) if ha._token(self.cfg) else []
            if ids:
                client = self.client or ha._make_client(self.cfg)
                try:
                    snap = pending.get("ha") or _snapshot(self.cfg, ids, client)
                    ev = threading.Event()
                    threads.append(threading.Thread(target=self._run, args=(ids, snap, client, ev), daemon=True))
                    restored.append(ev)
                except Exception:
                    pass
            if gc._key(self.cfg):
                snaps = pending.get("cloud") or {}
                if not snaps:
                    for name in gc._lights(self.cfg):
                        s = gc.snapshot(self.cfg, name, self.cloud_client)
                        if s is not None and s.get("online", True):     # an unplugged / Wi-Fi-less light can't be shown anything
                            snaps[name] = s
                if snaps:
                    ev = threading.Event()
                    threads.append(threading.Thread(target=self._run_cloud, args=(snaps, ev), daemon=True))
                    restored.append(ev)
            if not threads:
                return False
            if ids:
                ha.colour_memory_paused.set()   # the panel's polls must not learn Ultron's red as anyone's colour
            self._threads, self._restored = threads, restored
            for t in threads:
                t.start()
            return True

    def stop(self) -> None:
        """End the show. Returns once the lights have been told to go back; the checks carry on behind it."""
        with self._lock:
            restored = list(self._restored)
        self._stop.set()
        for ev in restored:
            ev.wait(timeout=30)

    def _call(self, client, service: str, entity_id, **data) -> None:
        try:
            ha.call(self.cfg, "light", service, entity_id, client=client, **data)
        except Exception:
            pass                                    # a flaky bulb must never break the show or the restore

    def _run(self, ids: list, snap: dict, client, restored: threading.Event) -> None:
        try:
            self._call(client, "turn_on", ids, **RED)
            on, waited = True, 0.0
            while not self._stop.wait(self.interval):
                waited += self.interval
                if waited >= self.max_seconds:
                    break
                on = not on
                if on:
                    self._call(client, "turn_on", ids, **RED)
                else:
                    self._call(client, "turn_off", ids)
        finally:
            try:
                time.sleep(self.settle)             # a blink still in flight must not get the last word
                self._restore(snap, client)
                restored.set()
                self._pending["ha"] = snap
                self._verify(snap, client)
            finally:
                restored.set()
                if not self._abort.is_set():        # an aborted check hands its snapshot to the next show
                    self._pending.pop("ha", None)
                    ha.colour_memory_paused.clear()

    def _restore(self, snap: dict, client) -> None:
        # Every light gets its own colour back first, the ones that were off too, so none keeps Ultron's red ...
        for eid, s in snap.items():
            self._call(client, "turn_on", eid, **_restore_params(s["params"]))
            time.sleep(self.settle / 5)
        time.sleep(self.settle)                     # ... and the colour lands before the "off" that follows it
        for eid, s in snap.items():
            if not s["on"]:
                self._call(client, "turn_off", eid)
                time.sleep(self.settle / 5)

    def _verify(self, snap: dict, client) -> None:
        """After Home Assistant has re-read the bulbs, put right any that missed their command."""
        for _ in range(self.verify_rounds):
            if self._abort.wait(self.verify_wait):
                return
            try:
                by_id = _states(self.cfg, client)
            except Exception:
                continue
            wrong = [eid for eid, s in snap.items() if not _matches(s, by_id.get(eid, {}))]
            if not wrong:
                return
            for eid in wrong:
                if snap[eid]["on"]:
                    self._call(client, "turn_on", eid, **_restore_params(snap[eid]["params"]))
                else:
                    self._call(client, "turn_off", eid)
                time.sleep(self.settle / 5)

    def _run_cloud(self, snaps: dict, restored: threading.Event) -> None:
        c = self.cloud_client
        try:
            for name in snaps:
                gc.power(self.cfg, name, True, c)
                if gc.has_colour(self.cfg, name):
                    gc.color(self.cfg, name, [255, 0, 0], c)
                    gc.brightness(self.cfg, name, 100, c)
            on, waited = True, 0.0
            while not self._stop.wait(self.cloud_interval):
                waited += self.cloud_interval
                if waited >= self.max_seconds:
                    break
                on = not on
                for name in snaps:                  # the colour sticks while it is off, so a blink is just power
                    gc.power(self.cfg, name, on, c)
        finally:
            try:
                for name, s in snaps.items():
                    try:
                        gc.restore(self.cfg, name, s, c)
                    except Exception:
                        pass
                restored.set()
                self._pending["cloud"] = snaps
                self._verify_cloud(snaps, c)
            finally:
                restored.set()
                if not self._abort.is_set():
                    self._pending.pop("cloud", None)

    def _verify_cloud(self, snaps: dict, c) -> None:
        """Govee refuses commands past its rate limit, so a restore can half-land: check, and send it again."""
        for _ in range(self.verify_rounds):
            if self._abort.wait(self.cloud_verify_wait):
                return
            wrong = []
            for name, want in snaps.items():
                got = gc.snapshot(self.cfg, name, c)
                if got is not None and not gc.matches(self.cfg, name, want, got):
                    wrong.append(name)
            if not wrong:
                return
            for name in wrong:
                try:
                    gc.restore(self.cfg, name, snaps[name], c)
                except Exception:
                    pass
