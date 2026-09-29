#!/usr/bin/env bash
set -euo pipefail
updater="$HOME/server/discord-quote-bot/deploy/autoupdate.py"
if [ -f "$updater" ]; then
    exec python3 "$updater" "$@"
fi
# Legacy virtualenv installation.
cd "$(dirname "$0")/../.."
git pull --ff-only
.venv/bin/pip install --quiet -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
podman build -q -t quotebot-lavalink deploy/lavalink
systemctl --user restart quotebot-lavalink.service quotebot.service
