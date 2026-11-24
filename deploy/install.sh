#!/bin/bash
# Runs on the Pi, from the project directory. Safe to run again at any time.
# Needs a sudo password only when a systemd unit changes.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR=$PWD

[ -x .venv/bin/pip ] || python3 -m venv --clear --system-site-packages .venv  # also one half made
.venv/bin/pip install --quiet -r requirements.txt

.venv/bin/python -m reporter check  # stop here if it cannot start or read its settings

zone=$(.venv/bin/python -c 'from reporter import config; print(config.load().timezone)')
[ "$(timedatectl show --property=Timezone --value 2>/dev/null)" = "$zone" ] || echo "!! the Pi's own time zone differs from the settings: sudo timedatectl set-timezone $zone"

changed=0
for unit in reporter.service reporter.timer reporter-button.service; do
    new=$(sed -e "s|@USER@|$USER|; s|@DIR@|$DIR|g" "deploy/$unit")
    if [ "$new" != "$(cat "/etc/systemd/system/$unit" 2>/dev/null || true)" ]; then
        printf '%s\n' "$new" | sudo tee "/etc/systemd/system/$unit" >/dev/null
        changed=1
    fi
done
if [ "$changed" = 1 ]; then
    sudo systemctl daemon-reload
    # Without this, time-sync.target is reached before the clock is actually right.
    sudo systemctl enable --quiet systemd-time-wait-sync.service
    sudo systemctl enable --quiet reporter.timer reporter-button.service
    sudo systemctl restart reporter.timer
fi
# Passwordless thanks to /etc/sudoers.d/reporter (see provision.sh).
sudo /usr/bin/systemctl restart reporter-button.service
systemctl list-timers --no-pager reporter.timer

if systemctl is-failed --quiet reporter-requests.path; then  # too many tries while something was wrong
    sudo systemctl reset-failed reporter-requests.path reporter-requests.service
    sudo systemctl start reporter-requests.path
fi

# What runs from its own root-owned copies. setup-web.sh, if that comes next, updates them.
[ -z "${WEB_NEXT:-}" ] || exit 0
changed() { [ -d "/usr/local/lib/$2" ] && [ "$(bash deploy/version.sh "$1")" != "$(cat "/usr/local/lib/$2/version" 2>/dev/null)" ]; }
if changed web reporter-web; then
    echo "!! the web interface has changed: run ./deploy.sh --web"
elif changed inbox receipt-inbox; then
    echo "!! the calendar drop box has changed: run the command in section 2 of docs/calendar.md again"
fi
