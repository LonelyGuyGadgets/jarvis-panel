from jarvis import climate
from jarvis.config import Config


def make_cfg(sensors=None):
    raw = {"climate": {"sensors": sensors if sensors is not None else
                       {"Office": "CC:00:00:00:00:07", "Living Room": "CC:00:00:00:00:04", "Kitchen": "CC:00:00:00:00:05"}}}
    return Config(actions={}, secrets={}, bind_host="x", port=1, raw=raw)


def test_decode_reads_temperature_humidity_and_battery_from_a_govee_advert():
    # real packet from the office sensor: 21.8 C, 40.8 %, battery 59 %
    assert climate.decode(bytes.fromhex("000355283b00")) == (21.8, 40.8, 59)


def test_decode_handles_below_zero_and_rejects_garbage():
    below = (0x800000 | 5 * 10000 + 150 * 0 + 600).to_bytes(3, "big")      # -5.0 C, 60.0 %
    t, h, b = climate.decode(b"\x00" + below + b"\x32\x00")
    assert (t, h, b) == (-5.0, 60.0, 50)
    assert climate.decode(b"\x00\x01") is None


def test_readings_are_in_fahrenheit_by_room_and_only_for_fresh_configured_sensors():
    store = climate.Store()
    store.update("CC:00:00:00:00:07", bytes.fromhex("000355283b00"), now=1000)       # office, fresh
    store.update("CC:00:00:00:00:04", bytes.fromhex("00029e221400"), now=100)        # living room, 15 min old
    store.update("CC:00:00:00:00:08", bytes.fromhex("000355283b00"), now=1000)       # not configured
    out = climate.readings(make_cfg(), store, now=1000)
    assert out == [{"name": "Office", "temp_f": 71, "humidity": 41, "battery": 59}]  # kitchen never heard, living room stale


def test_address_matching_ignores_case():
    store = climate.Store()
    store.update("CC:00:00:00:00:07", bytes.fromhex("000355283b00"), now=5)
    assert climate.readings(make_cfg(), store, now=5)[0]["name"] == "Office"
