import os
import tomllib
from dataclasses import dataclass, field

from jarvis.actions import ActionSpec


@dataclass
class Config:
    actions: dict
    secrets: dict
    bind_host: str
    port: int
    raw: dict = field(default_factory=dict)


def load_config(config_path: str, secrets_path: str) -> Config:
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)
    secrets = {}
    if os.path.exists(secrets_path):
        with open(secrets_path, "rb") as f:
            secrets = tomllib.load(f)
    actions = {
        name: ActionSpec(
            argv=spec.get("argv"),
            internal=spec.get("internal"),
            changes_state=bool(spec.get("changes_state", True)),
            exclusive=bool(spec.get("exclusive", False)),
        )
        for name, spec in raw.get("actions", {}).items()
    }
    return Config(actions=actions, secrets=secrets, bind_host=raw["bind_host"],
                  port=int(raw["port"]), raw=raw)
