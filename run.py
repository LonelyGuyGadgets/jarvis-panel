import os
import sys

import uvicorn

from jarvis.app import create_app
from jarvis.config import load_config

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    cfg = load_config(os.path.join(HERE, "config.toml"), os.path.join(HERE, "secrets.toml"))
    host = sys.argv[1] if len(sys.argv) > 1 else cfg.bind_host
    uvicorn.run(create_app(cfg), host=host, port=cfg.port)


if __name__ == "__main__":
    main()
