#!/bin/bash
# Runs on the Pi, once (safe to repeat): sets up the HTTPS calendar drop box.
#   bash deploy/setup-calendar.sh printer.example.com [--new-token]
# Needs a Cloudflare API token limited to "Zone / DNS / Edit" on that one domain.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=${1:?usage: setup-calendar.sh <hostname> [--new-token]}
[[ $HOST =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]] || { echo "not a hostname: $HOST" >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "== certificate for $HOST"
if ! sudo test -s "/etc/letsencrypt/live/$HOST/fullchain.pem"; then
    echo "installing certbot and its Cloudflare add-on, a few minutes on a Pi 3"
    sudo apt-get update -q >/dev/null
    sudo -E apt-get -yq install certbot python3-certbot-dns-cloudflare >/dev/null
    if ! sudo test -s /etc/letsencrypt/cloudflare.ini; then
        read -rsp "Paste the Cloudflare API token (it stays hidden), then Enter: " CF; echo
        [[ $CF =~ ^[A-Za-z0-9_-]{30,}$ ]] || { echo "that does not look like a Cloudflare token" >&2; exit 1; }
        sudo install -d -m 755 /etc/letsencrypt
        printf 'dns_cloudflare_api_token = %s\n' "$CF" | sudo sh -c 'umask 077; cat > /etc/letsencrypt/cloudflare.ini'
        unset CF
    fi
    read -rp "Do you accept the Let's Encrypt terms (letsencrypt.org/repository)? Type yes: " OK
    [ "$OK" = yes ] || { echo "stopped"; exit 1; }
    sudo certbot certonly --non-interactive --agree-tos --register-unsafely-without-email \
        --dns-cloudflare --dns-cloudflare-credentials /etc/letsencrypt/cloudflare.ini \
        --dns-cloudflare-propagation-seconds 30 -d "$HOST" ||
        { sudo rm -f /etc/letsencrypt/cloudflare.ini; echo "no certificate. If the token was refused, make a new one; it will be asked for again" >&2; exit 1; }
    sudo systemctl enable --quiet --now certbot.timer
fi

echo "== account that can only fill one folder"
id receipt-inbox >/dev/null 2>&1 ||
    sudo useradd --system --no-create-home --home-dir /var/lib/receipt-inbox --shell /usr/sbin/nologin receipt-inbox
sudo install -d -o root -g root -m 755 /var/lib/receipt-inbox
sudo install -d -o receipt-inbox -g "$(id -gn)" -m 2770 /var/lib/receipt-inbox/drop
sudo install -d -o root -g root -m 700 /etc/receipt-inbox

NEW=""
if [ "${2:-}" = --new-token ] || ! sudo test -s /etc/receipt-inbox/token.sha256; then
    NEW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
    sudo systemctl stop receipt-inbox.socket receipt-inbox.service 2>/dev/null || true  # it still knows the old one
    printf '%s' "$NEW" | sha256sum | cut -d' ' -f1 | sudo sh -c 'umask 077; cat > /etc/receipt-inbox/token.sha256'
    sudo rm -rf /var/lib/reporter-web/phone/token.sha256  # one made in the web interface would win
fi

echo "== service and firewall"
bash deploy/inbox.sh "$HOST"
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 fe80::/10 fc00::/7; do
    sudo ufw allow from "$net" to any port 8443 proto tcp comment "Calendar drop box, home network" >/dev/null
done

echo "== self-test"
check() {  # expected status, then curl arguments
    local want=$1 got; shift
    got=$(curl -sS -m 15 -o /dev/null -w '%{http_code}' --resolve "$HOST:8443:127.0.0.1" ${CURL_EXTRA:-} "$@" "https://$HOST:8443/calendar" || true)
    if [ "$got" = "$want" ]; then echo "ok: $got"; else echo "PROBLEM: wanted $want, got $got" >&2; exit 1; fi
}
check 405
check 401 -X POST -H 'Content-Type: application/json' -d '{"list":"x"}'
if [ -n "$NEW" ]; then
    printf 'Authorization: Bearer %s\n' "$NEW" | check 400 -X POST -H @- -H 'Content-Type: application/json' -d '{"list":"not a date"}'
    echo
    echo "Your phone token. Copy it now: only a fingerprint of it is kept on the Pi."
    echo
    echo "    $NEW"
    echo
    echo "Do not paste it anywhere except the shortcut. New one: add --new-token"
fi
echo "done: https://$HOST:8443/calendar"
