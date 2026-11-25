import subprocess
import threading
import time

import pytest

from jarvis.actions import ActionResult, ActionSpec, run_action
from jarvis.config import Config


def make_cfg(actions):
    return Config(actions=actions, secrets={}, bind_host="127.0.0.1", port=8088, raw={})


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture
def cfg():
    return make_cfg({
        "restart_plex": ActionSpec(argv=["sudo", "-n", "systemctl", "restart", "plexmediaserver"],
                                   internal=None, changes_state=True, exclusive=False),
        "snapraid_sync": ActionSpec(argv=["sudo", "-n", "snapraid", "sync"],
                                    internal=None, changes_state=True, exclusive=True),
        "disk_check": ActionSpec(argv=["sudo", "-n", "snapraid", "status"],
                                 internal=None, changes_state=False, exclusive=False),
    })


@pytest.mark.parametrize("name", ["rm -rf /", "../x", "", "restart_plex; ls", "RESTART_PLEX"])
def test_unknown_action_refused(cfg, monkeypatch, name):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a) or Completed())
    assert run_action(name, True, cfg).status == "refused"
    assert called == []


def test_state_change_requires_confirm(cfg, monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a) or Completed())
    result = run_action("restart_plex", False, cfg)
    assert result.status == "refused"
    assert called == []


def test_allowlisted_action_runs_exact_argv(cfg, monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        return Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_action("restart_plex", True, cfg)
    assert result.status == "done"
    assert seen["argv"] == ["sudo", "-n", "systemctl", "restart", "plexmediaserver"]
    assert not seen["kwargs"].get("shell")


def test_read_only_action_needs_no_confirm(cfg, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Completed(stdout="ok"))
    assert run_action("disk_check", False, cfg).status == "done"


def wait_until(pred, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(autouse=True)
def clean_actions():
    from jarvis import actions
    actions._reset()


def test_exclusive_action_runs_in_background_and_reports_busy(cfg, monkeypatch):
    from jarvis.actions import actions_running, last_results
    started, release, calls = threading.Event(), threading.Event(), []

    def slow_run(argv, **kwargs):
        calls.append((argv, kwargs))
        started.set()
        release.wait(5)
        return Completed()

    monkeypatch.setattr(subprocess, "run", slow_run)
    first = run_action("snapraid_sync", True, cfg)
    assert first.status == "done" and "started" in first.message
    assert started.wait(5)
    assert run_action("snapraid_sync", True, cfg).status == "busy"
    assert actions_running() == ["snapraid_sync"]
    assert calls[0][1].get("timeout") is None
    release.set()
    assert wait_until(lambda: actions_running() == [])
    assert last_results()["snapraid_sync"]["status"] == "done"
    assert len(calls) == 1


def test_background_failure_is_recorded(cfg, monkeypatch):
    from jarvis.actions import actions_running, last_results
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Completed(returncode=2, stderr="disk error"))
    assert run_action("snapraid_sync", True, cfg).status == "done"
    assert wait_until(lambda: actions_running() == [])
    last = last_results()["snapraid_sync"]
    assert last["status"] == "failed" and "disk error" in last["message"]


def test_exclusive_action_can_run_again_after_finishing(cfg, monkeypatch):
    from jarvis.actions import actions_running
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Completed())
    run_action("snapraid_sync", True, cfg)
    assert wait_until(lambda: actions_running() == [])
    assert run_action("snapraid_sync", True, cfg).status == "done"


def test_failed_command_reports_failed(cfg, monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: Completed(returncode=1, stderr="line1\nboom"))
    result = run_action("restart_plex", True, cfg)
    assert result.status == "failed"
    assert "boom" in result.message


def test_internal_action_uses_handler_and_needs_confirm():
    cfg = make_cfg({"pause_pihole": ActionSpec(argv=None, internal="pause_pihole",
                                               changes_state=True, exclusive=False)})
    handler = lambda: ActionResult("done", "paused")
    assert run_action("pause_pihole", False, cfg, {"pause_pihole": handler}).status == "refused"
    assert run_action("pause_pihole", True, cfg, {"pause_pihole": handler}).message == "paused"


def test_internal_action_without_handler_fails():
    cfg = make_cfg({"pause_pihole": ActionSpec(argv=None, internal="pause_pihole",
                                               changes_state=True, exclusive=False)})
    assert run_action("pause_pihole", True, cfg, {}).status == "failed"


def test_load_config_reads_actions_and_secrets(tmp_path):
    from jarvis.config import load_config
    (tmp_path / "config.toml").write_text(
        'bind_host = "192.0.2.10"\nport = 8088\n'
        '[actions.restart_plex]\nargv = ["sudo","-n","systemctl","restart","plexmediaserver"]\nchanges_state = true\n'
        '[actions.pause_pihole]\ninternal = "pause_pihole"\nchanges_state = true\n')
    (tmp_path / "secrets.toml").write_text('[pihole]\npassword = "x"\n')
    cfg = load_config(str(tmp_path / "config.toml"), str(tmp_path / "secrets.toml"))
    assert cfg.bind_host == "192.0.2.10" and cfg.port == 8088
    assert cfg.actions["restart_plex"].argv[-1] == "plexmediaserver"
    assert cfg.actions["pause_pihole"].internal == "pause_pihole"
    assert cfg.secrets["pihole"]["password"] == "x"


def test_load_config_missing_secrets_is_empty(tmp_path):
    from jarvis.config import load_config
    (tmp_path / "config.toml").write_text('bind_host = "127.0.0.1"\nport = 1\n')
    cfg = load_config(str(tmp_path / "config.toml"), str(tmp_path / "nope.toml"))
    assert cfg.secrets == {}
