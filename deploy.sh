#!/bin/bash
# Runs on your computer: copies the project to the Pi and installs it.
#   ./deploy.sh [--provision | --web] [user@host]
# --provision also sets up a freshly flashed Pi (see docs/install.md).
# --web also sets up or updates the web interface (see docs/web.md).
set -euo pipefail
cd "$(dirname "$0")"
usage() { echo "usage: ./deploy.sh [--provision | --web] [user@host]   (or put user@host in a file called .printer)" >&2; exit 1; }
THEN="bash reporter/deploy/install.sh"
HOST=""
for word in "$@"; do
    case "$word" in
        --provision) THEN="bash reporter/deploy/provision.sh" ;;
        --web) THEN="WEB_NEXT=1 bash reporter/deploy/install.sh && bash reporter/deploy/setup-web.sh" ;;
        -*) usage ;;
        *) [ -z "$HOST" ] || usage; HOST=$word ;;
    esac
done
HOST=${HOST:-$(cat .printer 2>/dev/null || true)}
[ -n "$HOST" ] || usage
FILES=(reporter reporter_web assets deploy config.toml requirements.txt README.md)
if [ -f config.local.toml ]; then FILES+=(config.local.toml); else echo "no config.local.toml here: if there is one on the Pi, it stays in force"; fi

# Only the fonts the program uses; the whole family is 300 MB.
FONTS=()
[ -d assets/fonts ] && for f in $(grep -oE 'SF-[A-Za-z-]+\.otf' reporter/render.py | sort -u); do
    FONTS+=(--include "/assets/fonts/$f")
done

# A fresh Raspberry Pi OS Lite may not have rsync yet. -t so sudo can ask for a password.
ssh -t "$HOST" 'command -v rsync >/dev/null || (sudo apt-get update -q && sudo apt-get -yq install rsync) >/dev/null; mkdir -p reporter'
rsync -az --delete --exclude __pycache__ --exclude .DS_Store \
    ${FONTS[@]+"${FONTS[@]}"} --exclude '/assets/fonts/*' \
    "${FILES[@]}" "$HOST:reporter/"
ssh -t "$HOST" "$THEN"
