#!/usr/bin/env bash
# Pull the latest code from GitHub and restart the bot.
set -euo pipefail
cd "$(dirname "$0")/../.."
git pull --ff-only
.venv/bin/pip install --quiet -r requirements.txt
podman build -q -t quotebot-lavalink deploy/lavalink
systemctl --user restart quotebot-lavalink.service quotebot.service
echo "Updated and restarted. Logs: journalctl --user -u quotebot -f"
