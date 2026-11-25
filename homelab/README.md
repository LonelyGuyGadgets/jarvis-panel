# Homelab guide

A general guide to building a small home server for media, photos, music, ebooks and home automation, like the one behind the Jarvis panel.

It describes the kind of setup, not a working copy of one. Addresses, users, ports and secrets are left out on purpose. Every value you need to fill in is marked `CHANGE_ME` or described in a comment.

- Six wiki pages explain how the pieces fit together, starting with [Homelab overview](https://github.com/LonelyGuyGadgets/jarvis-panel/wiki/Homelab-Overview).
- `homelab/stacks/<app>/compose.yaml`: starting-point Docker Compose files, one per app. Plex runs as a normal package, see `homelab/stacks/plex/README.md`.
