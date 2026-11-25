"""Local preview with fake data. Usage: python dev_server.py [offline]
`offline` makes Pi-hole report OFFLINE so the degraded look can be checked."""
import sys
import time

import uvicorn

from jarvis.actions import ActionResult, ActionSpec
from jarvis.app import create_app
from jarvis.config import Config
from jarvis.status import SourceResult

OFFLINE = "offline" in sys.argv


def now():
    return time.time()


sources = {
    "nuc": lambda c: SourceResult("ok", {"cpu_percent": 14.0, "ram_percent": 41.0, "temp_c": 52.0}, now()),
    "plex": lambda c: SourceResult("ok", {"streams": 2}, now()),
    "disks": lambda c: SourceResult("warn", {"pool": "OK", "parity": "WARN", "free_gb": 5120.0, "disks": {}}, now()),
    "pihole": lambda c: SourceResult("offline", {}, now()) if OFFLINE else
        SourceResult("ok", {"blocked_today": 18204, "block_percent": 23.0, "blocking": True}, now()),
    "smart_home": lambda c: SourceResult("ok", {
        "lights": [{"name": n, "on": o} for n, o in [("Bedroom Lamp", False), ("Office Panels", True), ("Floor Lamps", False), ("Office Floor Lamp", True), ("Office Ceiling", True), ("Bedroom Ceiling", False), ("Balcony", False), ("Office Light Bars", False), ("TV Lights", True), ("Couch Lamp", False)]],
        "climate": [{"name": "Living Room", "temp_f": 63, "humidity": 55, "battery": 20}, {"name": "Kitchen", "temp_f": 66, "humidity": 48, "battery": 64}, {"name": "Bedroom", "temp_f": 67, "humidity": 50, "battery": 67}, {"name": "Office", "temp_f": 71, "humidity": 41, "battery": 59}],
        "speakers": [{"name": "Office", "state": "idle", "volume": None}, {"name": "Living Room", "state": "idle", "volume": None}, {"name": "Kitchen", "state": "off", "volume": None}, {"name": "Soundbar", "state": "off", "volume": None}, {"name": "Bedroom", "state": "off", "volume": None}],
    }, now()),
}
names = ["restart_plex", "snapraid_sync", "restart_samba", "pause_pihole", "resume_pihole", "disk_check",
         "lights_toggle_living", "lights_toggle_desk", "volume_down_sonos", "play_pause_sonos", "volume_up_sonos"]
cfg = Config(actions={n: ActionSpec(None, n, n != "disk_check", False) for n in names},
             secrets={}, bind_host="127.0.0.1", port=8099, raw={})
internal = {n: (lambda n=n: ActionResult("done", f"{n} (fake)")) for n in names}

if __name__ == "__main__":
    ART = (b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
           b'<stop offset="0" stop-color="#ff7a18"/><stop offset="1" stop-color="#af002d"/></linearGradient></defs>'
           b'<rect width="200" height="200" fill="url(#g)"/><circle cx="100" cy="100" r="46" fill="#ffd166"/></svg>')
    uvicorn.run(create_app(cfg, sources, internal, art_fetch=lambda n: (ART, "image/svg+xml") if n == "Office" else None), host="127.0.0.1", port=8099, log_level="warning")
