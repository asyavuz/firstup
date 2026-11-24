#!/bin/bash
# Prints one fingerprint of everything that is installed as root, to tell whether it has changed.
#   bash deploy/version.sh web | inbox
set -eo pipefail
cd "$(dirname "$0")/.."
export LC_ALL=C
case "$1" in
    web) cat reporter/__init__.py reporter/settings.py reporter/stations.py reporter/stations.csv reporter_web/*.py reporter_web/style.css reporter_web/static/* \
             deploy/reporter_web_*.py deploy/reporter-web* deploy/reporter-requests* ;;
    inbox) cat deploy/receipt_inbox.py deploy/receipt-inbox.* ;;
    *) exit 1 ;;
esac | sha256sum | cut -d' ' -f1
