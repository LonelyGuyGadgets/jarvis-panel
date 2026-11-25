"""Room temperatures from Govee H5075 sensors, read straight off their Bluetooth broadcasts by the NUC.
The sensors only talk Bluetooth (Govee's cloud can't see them), and they announce temperature, humidity and battery
in every advertisement, so a periodic scan is all that is needed. No pairing, nothing is sent to them."""
import threading
import time
from typing import Optional

GOVEE_COMPANY_ID = 0xEC88
FRESH_SECONDS = 600


def decode(data: bytes) -> Optional[tuple]:
    """(temp_c, humidity_percent, battery_percent) from H5075 manufacturer data, or None if it isn't one."""
    if len(data) < 5:
        return None
    n = int.from_bytes(data[1:4], "big")
    negative = bool(n & 0x800000)
    n &= 0x7FFFFF
    temp = (n // 1000) / 10.0
    return (-temp if negative else temp), (n % 1000) / 10.0, data[4]


class Store:
    def __init__(self):
        self._lock = threading.Lock()
        self._by_addr: dict = {}

    def update(self, address: str, data: bytes, now: float) -> None:
        got = decode(data)
        if got is not None:
            with self._lock:
                self._by_addr[address.upper()] = (now, got)

    def get(self, address: str):
        with self._lock:
            return self._by_addr.get(address.upper())


def readings(cfg, store: Store, now: float) -> list:
    """[{"name","temp_f","humidity","battery"}] for each configured room heard from recently."""
    out = []
    for name, address in cfg.raw.get("climate", {}).get("sensors", {}).items():
        hit = store.get(address)
        if hit is None or now - hit[0] > FRESH_SECONDS:
            continue
        temp_c, humidity, battery = hit[1]
        out.append({"name": name, "temp_f": round(temp_c * 9 / 5 + 32), "humidity": round(humidity), "battery": battery})
    return out


STORE = Store()
_started = {"yes": False}


def _scan_forever(scan_seconds: float = 15, every: float = 90) -> None:
    try:
        import asyncio
        from bleak import BleakScanner
    except ImportError:
        return                                      # no Bluetooth library here (e.g. a dev machine)

    async def once():
        def seen(device, advert):
            data = advert.manufacturer_data.get(GOVEE_COMPANY_ID)
            if data:
                STORE.update(device.address, data, time.time())
        async with BleakScanner(seen):
            await asyncio.sleep(scan_seconds)

    while True:
        try:
            asyncio.run(once())
        except Exception:
            pass                                    # Bluetooth hiccup: try again next round
        time.sleep(max(1.0, every - scan_seconds))


def current(cfg) -> list:
    """Start the background scan the first time it is needed, then return the latest readings."""
    if cfg.raw.get("climate", {}).get("sensors") and not _started["yes"]:
        _started["yes"] = True
        threading.Thread(target=_scan_forever, daemon=True).start()
    return readings(cfg, STORE, time.time())
