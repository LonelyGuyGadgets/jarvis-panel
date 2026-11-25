# Plex

Plex runs as a normal Ubuntu package from Plex's own repository, not in Docker, so there is no compose file.
Point its libraries at the pool folder. Read-only access is enough. Turn on hardware transcoding if your processor supports it.
