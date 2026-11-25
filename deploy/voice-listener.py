#!/usr/bin/env python3
"""Runs on the Surface. Listens on the built-in mic, cuts out each spoken phrase and posts it to the panel
server (/api/command), which transcribes it, looks for "Jarvis", and acts. Standard library only.

Tunables are environment variables so the room can be tuned without editing code (see the .service file)."""
import array
import http.client
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
import io

URL = os.environ.get("JARVIS_URL", "http://192.0.2.10:8088/api/command")
DEVICE = os.environ.get("JARVIS_MIC", "default")   # via PipeWire, so the panel (Chrome) can use the mic too
MIXER_CARD = os.environ.get("JARVIS_MIXER_CARD", "PCH")
RATE = 16000
FRAME = 320                                     # 20 ms
TRIGGER_X = float(os.environ.get("JARVIS_TRIGGER_X", "3.5"))   # speech must be this many x above the room noise
MIN_RMS = float(os.environ.get("JARVIS_MIN_RMS", "120"))       # ... and at least this loud (high-passed rms)
END_SILENCE = float(os.environ.get("JARVIS_END_SILENCE", "0.9"))
MAX_SECONDS = 8.0
MIN_SPEECH = 0.45
PREROLL = 15                                    # frames kept from before the trigger (300 ms)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def select_builtin_mic():
    """The docking station's input is silent; make the built-in mic PipeWire's default source."""
    try:
        out = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=10).stdout
        sources = out.split("Sources:")[1].split("Filters:")[0] if "Sources:" in out else ""
        for line in sources.splitlines():
            if "Built-in Audio" in line:
                node = "".join(c for c in line.split("Built-in")[0] if c.isdigit() or c == ".").strip(".").split(".")[-1]
                if node.isdigit():
                    subprocess.run(["wpctl", "set-default", node], check=False, timeout=10)
                return
    except (OSError, subprocess.SubprocessError, IndexError):
        pass


def set_mixer():
    for ctrl, val in (("Internal Mic Boost", "1"), ("Capture", "60")):
        subprocess.run(["amixer", "-q", "-c", MIXER_CARD, "sset", ctrl, val], check=False)


class HighPass:
    """One-pole high-pass (~120 Hz): removes the mic's DC offset and low rumble before measuring or sending."""
    def __init__(self):
        self.px = self.py = 0.0
        self.a = 1 / (1 + 2 * math.pi * 120 / RATE)

    def __call__(self, samples):
        out = array.array("h")
        px, py, a = self.px, self.py, self.a
        for x in samples:
            py = a * (py + x - px)
            px = x
            out.append(max(-32768, min(32767, int(py))))
        self.px, self.py = px, py
        return out


def rms(samples):
    return math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0


def wav_bytes(frames):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(b"".join(f.tobytes() for f in frames))
    return buf.getvalue()


def send(frames):
    req = urllib.request.Request(URL, data=wav_bytes(frames), headers={"Content-Type": "audio/wav"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            log("->", r.read().decode()[:200])
    except (urllib.error.URLError, OSError) as exc:
        log("send failed:", exc)


LEVEL_URL = URL.replace("/api/command", "/api/audio-level")


class LevelReporter:
    """Posts the room's loudness (just a number) ~9 times a second so the panel's core can pulse to it."""
    def __init__(self):
        parts = urllib.parse.urlsplit(LEVEL_URL)
        self.host, self.port, self.path = parts.hostname, parts.port or 80, parts.path
        self.conn, self.n, self.acc = None, 0, 0.0

    def feed(self, level):
        self.acc = max(self.acc, level)
        self.n += 1
        if self.n < 6:
            return
        value, self.acc, self.n = self.acc, 0.0, 0
        try:
            if self.conn is None:
                self.conn = http.client.HTTPConnection(self.host, self.port, timeout=2)
            self.conn.request("POST", self.path, body='{"level": %.1f}' % value, headers={"Content-Type": "application/json"})
            self.conn.getresponse().read()
        except (OSError, http.client.HTTPException):
            self.conn = None


def run():
    select_builtin_mic()
    set_mixer()
    proc = subprocess.Popen(["arecord", "-q", "-D", DEVICE, "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"],
                            stdout=subprocess.PIPE)
    hp = HighPass()
    reporter = LevelReporter()
    floor = None
    pre, clip = [], []
    loud = quiet = 0
    speaking = False
    log("listening on", DEVICE)
    while True:
        raw = proc.stdout.read(FRAME * 2)
        if len(raw) < FRAME * 2:
            raise RuntimeError("microphone stream ended")
        frame = hp(array.array("h", raw))
        level = rms(frame)
        reporter.feed(level)
        if floor is None:
            floor = level
        threshold = max(MIN_RMS, floor * TRIGGER_X)
        if not speaking:
            floor = 0.98 * floor + 0.02 * level          # track the room's noise only while nobody is talking
            pre.append(frame)
            if len(pre) > PREROLL:
                pre.pop(0)
            loud = loud + 1 if level > threshold else 0
            if loud >= 3:
                speaking, clip, quiet = True, list(pre), 0
                log("speech start (level %.0f, threshold %.0f)" % (level, threshold))
            continue
        clip.append(frame)
        quiet = quiet + 1 if level < threshold * 0.6 else 0
        seconds = len(clip) * FRAME / RATE
        if quiet * FRAME / RATE >= END_SILENCE or seconds >= MAX_SECONDS:
            speaking, loud, pre = False, 0, []
            voiced = seconds - quiet * FRAME / RATE
            if voiced >= MIN_SPEECH:
                log("clip %.1fs, sending" % seconds)
                send(clip)
            else:
                log("blip %.1fs, dropped" % voiced)
            clip = []


def main():
    while True:
        try:
            run()
        except Exception as exc:
            log("listener error:", exc)
            time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())
