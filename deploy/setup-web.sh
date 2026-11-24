#!/bin/bash
# Runs on the Pi: sets up the web interface, or updates it. Safe to repeat.
#   bash deploy/setup-web.sh [--new-password]
# Needs the certificate from setup-calendar.sh; the name is events.host in config.local.toml.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR=$PWD
LIB=/usr/local/lib/reporter-web
BASE=/var/lib/reporter-web
GROUP=$(id -gn)
HOST=$(.venv/bin/python -c 'from reporter import config; print(config.load().events.host)')
[[ $HOST =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]] || { echo "no usable host under [events] in config.local.toml: $HOST" >&2; exit 1; }
sudo test -s "/etc/letsencrypt/live/$HOST/fullchain.pem" || { echo "no certificate for $HOST: run setup-calendar.sh first" >&2; exit 1; }

SOCKETS="reporter-web-tls.socket reporter-web.socket"
UNITS="reporter-web-tls.socket reporter-web-tls.service reporter-web.socket reporter-web.service reporter-requests.path reporter-requests.service"
# Sockets too, or a visitor could start the old version again while this runs. If it stops
# halfway, the pages must not stay away.
trap '[ $? = 0 ] || sudo systemctl start $SOCKETS 2>/dev/null || true' EXIT
sudo systemctl stop $SOCKETS reporter-web-tls.service reporter-web.service 2>/dev/null || true

echo "== accounts and folders"
for account in reporter-web reporter-tls; do
    id "$account" >/dev/null 2>&1 ||
        sudo useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$account"
done
MOUNT=$(systemd-escape --path --suffix=mount "$BASE")
sudo install -o root -g root -m 644 deploy/reporter-web.mount "/etc/systemd/system/$MOUNT"
sudo systemctl daemon-reload
if ! mountpoint -q "$BASE"; then
    sudo install -d -o root -g root -m 755 "$BASE"
    if ! sudo test -s "$BASE.img"; then
        sudo truncate -s 16M "$BASE.img.new"
        sudo mkfs.ext4 -q -m 0 "$BASE.img.new"
        sudo chmod 600 "$BASE.img.new"
        sudo mv "$BASE.img.new" "$BASE.img"
    fi
    sudo systemctl enable --quiet --now "$MOUNT"
    mountpoint -q "$BASE" || { echo "PROBLEM: $BASE is not mounted" >&2; exit 1; }
fi
sudo install -d -o root -g root -m 755 "$BASE"
sudo install -d -o reporter-web -g "$GROUP" -m 2750 "$BASE/settings"   # it writes, this account reads
sudo install -d -o reporter-web -g "$GROUP" -m 2770 "$BASE/requests"   # it writes, this account clears
sudo install -d -o "$USER" -g reporter-web -m 2750 "$BASE/out"         # this account writes, it reads
if id receipt-inbox >/dev/null 2>&1; then
    sudo install -d -o reporter-web -g receipt-inbox -m 2750 "$BASE/phone"  # it writes a fingerprint, the drop box reads
fi
install -d -m 700 "$HOME/.config/reporter"                             # where the train token goes

echo "== program"
sudo install -d -o root -g root -m 755 "$LIB" "$LIB/reporter" "$LIB/reporter_web" "$LIB/reporter_web/static"
sudo install -o root -g root -m 644 reporter/__init__.py reporter/settings.py reporter/stations.py reporter/stations.csv "$LIB/reporter/"
sudo install -o root -g root -m 644 reporter_web/*.py reporter_web/style.css "$LIB/reporter_web/"
sudo install -o root -g root -m 644 reporter_web/static/* "$LIB/reporter_web/static/"
sudo install -o root -g root -m 644 deploy/reporter_web_start.py "$LIB/start.py"
sudo install -o root -g root -m 644 deploy/reporter_web_tls.py "$LIB/tls.py"
sudo rm -f "$LIB/version"

echo "== password"
sudo install -d -o root -g root -m 700 /etc/reporter-web
if [ "${1:-}" = --new-password ] || ! sudo test -s /etc/reporter-web/password; then
    HASH=$(cd "$LIB" && /usr/bin/python3 -I -c 'import sys; sys.path.insert(0, "'"$LIB"'"); from reporter_web import auth; sys.exit(auth.main())')
    printf '%s\n' "$HASH" | sudo sh -c 'umask 077; cat > /etc/reporter-web/password.new && mv /etc/reporter-web/password.new /etc/reporter-web/password'
    unset HASH
    sudo rm -rf "$BASE/settings/password"  # one chosen on the page would win
else
    echo "kept (add --new-password to change it)"
    CHOSEN=$(sudo stat -c %y "$BASE/settings/password" 2>/dev/null | cut -d. -f1) || true
    [ -z "$CHOSEN" ] || echo "one chosen on the page is in force, from $CHOSEN. If that was not you: --new-password"
fi

if [ -d /usr/local/lib/receipt-inbox ] && [ "$(bash deploy/version.sh inbox)" != "$(cat /usr/local/lib/receipt-inbox/version 2>/dev/null)" ]; then
    echo "== calendar drop box, newer version"
    bash deploy/inbox.sh "$HOST"
fi

echo "== services and firewall"
for unit in $UNITS; do
    sed -e "s|@HOST@|$HOST|g; s|@USER@|$USER|g; s|@DIR@|$DIR|g; s|@HOME@|$HOME|g" "deploy/$unit" | sudo tee "/etc/systemd/system/$unit" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl reset-failed $UNITS 2>/dev/null || true
sudo systemctl enable --quiet $SOCKETS reporter-requests.path
sudo systemctl restart reporter-requests.path $SOCKETS
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 fe80::/10 fc00::/7; do
    sudo ufw allow from "$net" to any port 8444 proto tcp comment "Web interface, home network" >/dev/null
done

echo "== self-test"
rm -f "$BASE/out/status.json"
sudo -u reporter-web touch "$BASE/requests/status"  # not as this account, which could be led elsewhere by a link
for _ in $(seq 30); do [ -s "$BASE/out/status.json" ] && break; sleep 2; done
[ -s "$BASE/out/status.json" ] && echo "ok: the printer program answers" || { echo "PROBLEM: no answer, see journalctl -u reporter-requests" >&2; exit 1; }
check() {  # what it shows, expected status, then curl arguments
    local what=$1 want=$2 got; shift 2
    got=$(curl -sS -m 20 -o /dev/null -w '%{http_code}' --resolve "$HOST:8444:127.0.0.1" "$@" || true)
    if [ "$got" = "$want" ]; then echo "ok: $what"; else echo "PROBLEM: $what: wanted $want, got $got" >&2; exit 1; fi
}
check "the sign-in page opens" 200 "https://$HOST:8444/login"
check "other pages need signing in" 303 "https://$HOST:8444/times"
check "other names are refused" 421 -H "Host: evil.example" "https://$HOST:8444/login"
check "other sites cannot send forms" 403 -H "Origin: https://evil.example" -d "password=x" "https://$HOST:8444/login"
check "guesses are refused" 403 -H "Origin: https://$HOST:8444" -d "password=x" "https://$HOST:8444/login"
bash deploy/version.sh web | sudo sh -c "cat > $LIB/version"
echo "done: https://$HOST:8444"
