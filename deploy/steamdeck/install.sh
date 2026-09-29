#!/usr/bin/env bash
# One-time setup for hosting the bot on a Steam Deck (SteamOS 3.5+).
# Run from Desktop Mode as the normal "deck" user. No sudo or read-only
# filesystem changes: Python lives in a venv, Lavalink runs in Podman, and
# both start automatically as systemd user services.
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO="$PWD"
UNITS="$HOME/.config/systemd/user"

command -v podman >/dev/null || { echo "Podman is missing. Update SteamOS to 3.5 or newer."; exit 1; }

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env. Fill in DISCORD_TOKEN, QUOTES_CHANNEL_ID, LAVALINK_PASSWORD"
  echo "(any long random string) and DASHBOARD_TOKEN, then run this script again."
  exit 1
fi
# Lavalink runs on this machine now.
sed -i 's|^LAVALINK_URI=$|LAVALINK_URI=http://127.0.0.1:2333|' .env
grep -q '^LAVALINK_PASSWORD=.' .env || { echo "Set LAVALINK_PASSWORD in .env first."; exit 1; }
grep -q '^DISCORD_TOKEN=.' .env && ! grep -q '^DISCORD_TOKEN=your-bot-token-here' .env \
  || { echo "Set DISCORD_TOKEN in .env first."; exit 1; }

for f in quotes.json names.json nicknames.json; do
  [ -f "$f" ] || echo "Note: $f not found here. Copy your saved data files into $REPO before starting."
done

echo "Installing Python packages..."
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "Building Lavalink..."
podman build -q -t quotebot-lavalink deploy/lavalink

mkdir -p "$UNITS"
cat > "$UNITS/quotebot-lavalink.service" <<UNIT
[Unit]
Description=Lavalink for Discord Quote Bot
After=network-online.target

[Service]
ExecStartPre=-/usr/bin/podman rm -f quotebot-lavalink
ExecStart=/usr/bin/podman run --rm --name quotebot-lavalink -p 127.0.0.1:2333:2333 --env-file $REPO/.env quotebot-lavalink
ExecStop=/usr/bin/podman stop -t 10 quotebot-lavalink
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNIT

cat > "$UNITS/quotebot.service" <<UNIT
[Unit]
Description=Discord Quote Bot
After=network-online.target quotebot-lavalink.service
Wants=quotebot-lavalink.service

[Service]
WorkingDirectory=$REPO
EnvironmentFile=$REPO/.env
ExecStart=$REPO/.venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now quotebot-lavalink.service quotebot.service

# Keep services running when nobody is logged in (optional; needs the deck password).
loginctl enable-linger "$USER" 2>/dev/null || echo "Tip: run 'sudo loginctl enable-linger $USER' so the bot runs even before login."

echo
echo "Done. Check it with:  systemctl --user status quotebot"
echo "Live logs:            journalctl --user -u quotebot -f"
