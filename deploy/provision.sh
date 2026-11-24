#!/bin/bash
# Turns a fresh Raspberry Pi OS Lite into the receipt printer. Safe to run again.
# Everything that used to be set up by hand lives here, not on the SD card.
# Asks for your sudo password, possibly more than once, and restarts the Pi at the end.
set -euo pipefail
cd "$(dirname "$0")/.."
BOOT=${BOOT:-/boot/firmware}
[ -f "$BOOT/config.txt" ] || BOOT=/boot
export DEBIAN_FRONTEND=noninteractive

echo "== packages"
sudo apt-get update -q
sudo -E apt-get -yq -o Dpkg::Options::=--force-confold full-upgrade
sudo -E apt-get -yq install python3-venv python3-gpiozero python3-lgpio rsync ufw fail2ban unattended-upgrades

echo "== printer on the full UART, nothing else talking to it"
if ! grep -q '^dtoverlay=disable-bt' "$BOOT/config.txt"; then
    printf '\n[all]\n# Receipt printer on the full UART (PL011), whose clock does not change under load.\nenable_uart=1\ndtoverlay=disable-bt\n' |
        sudo tee -a "$BOOT/config.txt" >/dev/null
fi
sudo sed -i -E 's/console=(serial0|ttyAMA0|ttyS0),[0-9]+ ?//g' "$BOOT/cmdline.txt"
for unit in hciuart.service serial-getty@ttyAMA0.service serial-getty@ttyS0.service; do
    sudo systemctl disable --now "$unit" >/dev/null 2>&1 || true
done
sudo usermod -aG dialout,gpio "$USER"

echo "== logs, Wi-Fi"
sudo install -d /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\nSystemMaxUse=100M\nMaxRetentionSec=1month\n' | sudo tee /etc/systemd/journald.conf.d/reporter.conf >/dev/null
if [ -d /etc/NetworkManager/conf.d ]; then  # power saving makes the Pi drop off the network
    printf '[connection]\nwifi.powersave = 2\n' | sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf >/dev/null
fi

echo "== automatic security updates"
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' |
    sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null
sudo tee /etc/apt/apt.conf.d/52raspberrypi-origins >/dev/null <<'CONF'
Unattended-Upgrade::Origins-Pattern {
        "origin=Raspbian,codename=${distro_codename},label=Raspbian";
        "origin=Raspberry Pi Foundation,codename=${distro_codename},label=Raspberry Pi Foundation";
};
CONF

echo "== SSH: keys only"
if [ -s "$HOME/.ssh/authorized_keys" ]; then
    sudo tee /etc/ssh/sshd_config.d/10-hardening.conf >/dev/null <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
X11Forwarding no
LoginGraceTime 30
CONF
    sudo sshd -t
    sudo systemctl reload ssh
else
    echo "!! no SSH key installed for $USER: leaving password login on" >&2
fi

echo "== firewall: SSH from private networks only"
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 fe80::/10 fc00::/7; do
    sudo ufw allow from "$net" to any port 22 proto tcp comment "SSH from the home network" >/dev/null
done
sudo ufw default deny incoming >/dev/null
sudo ufw default allow outgoing >/dev/null
sudo ufw --force enable >/dev/null

echo "== the only two commands that may run without a password"
RULE=$(mktemp)
echo "$USER ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff, /usr/bin/systemctl restart reporter-button.service" > "$RULE"
sudo visudo -cqf "$RULE"
sudo install -o root -g root -m 440 "$RULE" /etc/sudoers.d/reporter
rm -f "$RULE"
if sudo -k -n true 2>/dev/null; then
    echo "!! $USER may run everything without a password, as on older systems. To have it asked for:" >&2
    echo "!!     sudo rm /etc/sudoers.d/010_pi-nopasswd    (first make sure that you know the password)" >&2
fi

echo "== reporter"
bash deploy/install.sh
sudo timedatectl set-timezone "$(.venv/bin/python -c 'from reporter import config; print(config.load().timezone)')"
if [ "${REBOOT:-yes}" = yes ]; then
    echo "== all done, restarting so the printer port change takes effect"
    sudo systemctl reboot
fi
