#!/bin/bash
# Installs or updates the calendar drop box's program and units. Run by setup-calendar.sh, and
# by setup-web.sh if it has changed.
#   bash deploy/inbox.sh printer.example.com
set -euo pipefail
cd "$(dirname "$0")/.."
LIB=/usr/local/lib/receipt-inbox
sudo install -d -o root -g root -m 755 "$LIB"
sudo rm -f "$LIB/version"
sudo install -o root -g root -m 644 deploy/receipt_inbox.py "$LIB/receipt_inbox.py"
sed "s|@HOST@|$1|g" deploy/receipt-inbox.service | sudo tee /etc/systemd/system/receipt-inbox.service >/dev/null
sudo install -o root -g root -m 644 deploy/receipt-inbox.socket /etc/systemd/system/receipt-inbox.socket
sudo systemctl daemon-reload
sudo systemctl enable --quiet receipt-inbox.socket
sudo systemctl stop receipt-inbox.service 2>/dev/null || true  # starts again when the phone calls
sudo systemctl restart receipt-inbox.socket
bash deploy/version.sh inbox | sudo sh -c "cat > $LIB/version"
