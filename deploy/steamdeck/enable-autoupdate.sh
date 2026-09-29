#!/usr/bin/env bash
# Enable updates for the existing Podman migration installation, as deck.
set -euo pipefail
cd "$(dirname "$0")"
root="$HOME/server/discord-quote-bot"
units="$HOME/.config/systemd/user"
for unit in discord-quote-bot discord-lavalink; do
    test -f "$units/$unit.service" || { echo "Existing $unit.service required"; exit 1; }
done
test -f "$root/backup-data.py"
mkdir -p "$root/deploy" "$root/backups"
install -m 700 autoupdate.py "$root/deploy/autoupdate.py"
if [ ! -f "$root/deploy-state.json" ]; then
    for name in discord-quote-bot discord-lavalink; do
        podman tag "localhost/$name:migration" "localhost/$name:current"
        cp "$units/$name.service" "$root/backups/$name.before-autoupdate.service"
        sed -i "s|localhost/$name:migration|localhost/$name:current|" "$units/$name.service"
    done
    printf '%s\n' '{"deployed":"4e7dd4b54946be7cd60ca62cafa13ac4d0a63c95"}' > "$root/deploy-state.json"
    chmod 600 "$root/deploy-state.json"
fi
cat > "$units/discord-bot-update.service" <<'UNIT'
[Unit]
Description=Deploy tested GitHub updates for the Discord bot
[Service]
Type=oneshot
Environment=GIT_TERMINAL_PROMPT=0
Environment=PYTHONUNBUFFERED=1
UMask=0077
ExecStart=/usr/bin/python3 %h/server/discord-quote-bot/deploy/autoupdate.py
TimeoutStartSec=30min
UNIT
cat > "$units/discord-bot-update.timer" <<'UNIT'
[Unit]
Description=Check GitHub master for Discord bot updates every two minutes
[Timer]
OnBootSec=2min
OnUnitInactiveSec=2min
AccuracySec=10s
[Install]
WantedBy=timers.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now discord-bot-update.timer
echo 'Automatic updates enabled. Logs: journalctl --user -u discord-bot-update'
