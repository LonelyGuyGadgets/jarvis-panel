import json
import subprocess

import httpx

from jarvis.config import Config
from jarvis.sources import disks, nuc, plex


def make_cfg(raw=None, secrets=None):
    return Config(actions={}, secrets=secrets or {}, bind_host="127.0.0.1", port=1, raw=raw or {})


def test_nuc_read_has_cpu_ram_temp():
    r = nuc.read(make_cfg())
    assert r.state == "ok"
    assert set(r.data) >= {"cpu_percent", "ram_percent", "temp_c"}
    assert 0 <= r.data["ram_percent"] <= 100


class Resp:
    def __init__(self, status=200, payload=None):
        self.status_code, self._p = status, payload

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=None)


PLEX_CFG = dict(raw={"plex": {"url": "http://localhost:32400"}}, secrets={"plex": {"token": "t"}})


def test_plex_streams_counted_from_sessions_json(monkeypatch):
    seen = {}

    def fake_get(url, **kw):
        seen["url"], seen["headers"] = url, kw.get("headers", {})
        return Resp(200, {"MediaContainer": {"size": 2, "Metadata": [{}, {}]}})

    monkeypatch.setattr(httpx, "get", fake_get)
    r = plex.read(make_cfg(**PLEX_CFG))
    assert r.state == "ok" and r.data["streams"] == 2
    assert seen["url"].endswith("/status/sessions")
    assert seen["headers"]["X-Plex-Token"] == "t"


def test_plex_down_is_offline(monkeypatch):
    def fake_get(url, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", fake_get)
    assert plex.read(make_cfg(**PLEX_CFG)).state == "offline"


def test_plex_without_token_reports_online_without_stream_count(monkeypatch):
    urls = []
    monkeypatch.setattr(httpx, "get", lambda url, **kw: urls.append(url) or Resp(200, {}))
    r = plex.read(make_cfg(raw={"plex": {"url": "http://localhost:32400"}}))
    assert r.state == "ok" and r.data["streams"] is None
    assert urls[0].endswith("/identity")


SMART_GOOD = "SMART overall-health self-assessment test result: PASSED\n  5 Reallocated_Sector_Ct 0x0033 100 100 010 Pre-fail Always - 0\n197 Current_Pending_Sector 0x0012 100 100 000 Old_age Always - 0\n"
SMART_BAD = "SMART overall-health self-assessment test result: FAILED!\n  5 Reallocated_Sector_Ct 0x0033 001 001 010 Pre-fail Always - 2048\n"
SMART_REALLOC = "SMART overall-health self-assessment test result: PASSED\n  5 Reallocated_Sector_Ct 0x0033 100 100 010 Pre-fail Always - 8\n"

DISK_RAW = {"disks": {"parity": "sde", "tb1": "sda"}, "disk_pool": {"path": "."}}


def fake_smart(outputs):
    class P:
        def __init__(self, out):
            self.returncode, self.stdout, self.stderr = 0, out, ""

    def run(argv, **kw):
        dev = argv[-1].split("/")[-1]
        return P(outputs[dev])

    return run


def test_disk_parity_failure_is_warn(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_smart({"sde": SMART_BAD, "sda": SMART_GOOD}))
    r = disks.read(make_cfg(raw=DISK_RAW))
    assert r.state == "warn"
    assert r.data["parity"] == "WARN"
    assert r.data["pool"] == "OK"


def test_disk_reallocated_sectors_is_warn(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_smart({"sde": SMART_REALLOC, "sda": SMART_GOOD}))
    assert disks.read(make_cfg(raw=DISK_RAW)).data["parity"] == "WARN"


def test_disks_all_good_is_ok_with_free_space(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_smart({"sde": SMART_GOOD, "sda": SMART_GOOD}))
    r = disks.read(make_cfg(raw=DISK_RAW))
    assert r.state == "ok" and r.data["parity"] == "OK"
    assert r.data["free_gb"] >= 0


def test_disk_smartctl_missing_is_offline(monkeypatch):
    def run(*a, **k):
        raise FileNotFoundError("sudo")

    monkeypatch.setattr(subprocess, "run", run)
    assert disks.read(make_cfg(raw=DISK_RAW)).state == "offline"


SMART_REAL_GOOD = """=== START OF READ SMART DATA SECTION ===
SMART overall-health self-assessment test result: PASSED

ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
  5 Reallocated_Sector_Ct   0x0033   100   100   005    Pre-fail  Always       -       0
197 Current_Pending_Sector  0x0022   100   100   000    Old_age   Always       -       0
198 Offline_Uncorrectable   0x0008   100   100   000    Old_age   Offline      -       0
"""


def test_attribute_table_header_word_failed_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_smart({"sde": SMART_REAL_GOOD, "sda": SMART_REAL_GOOD}))
    r = disks.read(make_cfg(raw=DISK_RAW))
    assert r.state == "ok" and r.data["parity"] == "OK" and r.data["pool"] == "OK"


def test_pending_sectors_make_a_passed_disk_warn(monkeypatch):
    bad = SMART_REAL_GOOD.replace("Old_age   Always       -       0", "Old_age   Always       -       72", 1)
    monkeypatch.setattr(subprocess, "run", fake_smart({"sde": bad, "sda": SMART_REAL_GOOD}))
    assert disks.read(make_cfg(raw=DISK_RAW)).data["parity"] == "WARN"


def test_nuc_temp_prefers_coretemp_and_ignores_implausible(monkeypatch):
    import psutil
    from collections import namedtuple
    T = namedtuple("T", "label current high critical")
    monkeypatch.setattr(psutil, "sensors_temperatures", lambda: {
        "acpitz": [T("", -263.2, None, None), T("", 49.0, None, None)],
        "coretemp": [T("Package id 0", 54.0, None, None), T("Core 0", 48.0, None, None)],
    }, raising=False)
    assert nuc.read(make_cfg()).data["temp_c"] == 54.0


def test_nuc_temp_skips_implausible_when_no_coretemp(monkeypatch):
    import psutil
    from collections import namedtuple
    T = namedtuple("T", "label current high critical")
    monkeypatch.setattr(psutil, "sensors_temperatures", lambda: {
        "acpitz": [T("", -263.2, None, None), T("", 49.0, None, None)]}, raising=False)
    assert nuc.read(make_cfg()).data["temp_c"] == 49.0


def test_unreadable_disks_are_a_warning_not_healthy(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_smart({"sde": "", "sda": ""}))
    r = disks.read(make_cfg(raw=DISK_RAW))
    assert r.state == "warn"
    assert r.data["parity"] == "UNKNOWN" and r.data["pool"] == "UNKNOWN"


def test_one_unreadable_pool_disk_makes_pool_unknown_not_ok(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_smart({"sde": SMART_REAL_GOOD, "sda": ""}))
    r = disks.read(make_cfg(raw=DISK_RAW))
    assert r.state == "warn" and r.data["pool"] == "UNKNOWN" and r.data["parity"] == "OK"
