import re
import shutil
import subprocess
import time

from jarvis.status import SourceResult

_COUNTERS = ("Reallocated_Sector_Ct", "Current_Pending_Sector", "Offline_Uncorrectable")


def _device_health(dev: str) -> str:
    proc = subprocess.run(["sudo", "-n", "smartctl", "-H", "-A", f"/dev/{dev}"],
                          capture_output=True, text=True, timeout=20)
    out = proc.stdout or ""
    verdict = re.search(r"test result:\s*(\w+)", out)
    if verdict and verdict.group(1).upper() != "PASSED":
        return "WARN"
    for line in out.splitlines():
        if any(c in line for c in _COUNTERS):
            m = re.search(r"(\d+)\s*$", line)
            if m and int(m.group(1)) > 0:
                return "WARN"
    return "OK" if verdict else "UNKNOWN"


def read(cfg) -> SourceResult:
    devices = cfg.raw.get("disks", {})
    health = {}
    try:
        for label, dev in devices.items():
            health[label] = _device_health(dev)
    except (OSError, subprocess.SubprocessError):
        return SourceResult("offline", {}, time.time())
    pool_labels = [l for l in health if l != "parity"]
    pool_states = [health[l] for l in pool_labels]
    pool = "WARN" if "WARN" in pool_states else "UNKNOWN" if ("UNKNOWN" in pool_states or not pool_states) else "OK"
    parity = health.get("parity", "UNKNOWN")
    free_gb = None
    path = cfg.raw.get("disk_pool", {}).get("path")
    if path:
        try:
            free_gb = round(shutil.disk_usage(path).free / 1e9, 1)
        except OSError:
            free_gb = None
    state = "ok" if (pool, parity) == ("OK", "OK") else "warn"
    data = {"disks": health, "parity": parity, "pool": pool, "free_gb": free_gb}
    return SourceResult(state, data, time.time())
