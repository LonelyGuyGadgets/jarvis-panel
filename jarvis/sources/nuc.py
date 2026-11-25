import time

import psutil

from jarvis.status import SourceResult


def _plausible(t) -> bool:
    return -20 < t < 130


def _temp_c():
    try:
        temps = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None
    ordered = [temps["coretemp"]] if temps.get("coretemp") else []
    ordered += [v for k, v in temps.items() if k != "coretemp"]
    for entries in ordered:
        for e in entries:
            if _plausible(e.current):
                return round(e.current, 1)
    return None


def read(cfg) -> SourceResult:
    data = {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "ram_percent": psutil.virtual_memory().percent,
        "temp_c": _temp_c(),
    }
    return SourceResult("ok", data, time.time())
