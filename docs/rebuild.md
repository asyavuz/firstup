# A new SD card

Half an hour. Keep the old card: swapping it back is the quickest way to recover.

**Before**, if the old card still works, save what is only there (on your computer, in the
project folder; git ignores files ending in `.backup.json`):

    scp user@printer.local:/var/lib/reporter-web/settings/settings.json settings.backup.json

If there is no such file, nothing was changed in the web interface. If you no longer have the
project folder, also save your settings: `scp user@printer.local:reporter/config.local.toml .`

Nothing else is worth copying. The Wi-Fi details, the train token, the phone token, the
certificate and the web password are quicker, and safer, to make again than to carry about.

**Then:**

1. Sections 3 to 6 of [install.md](install.md), without cloning again. Use the same hostname
   and user. The Pi has a new identity, so first: `ssh-keygen -R printer.local`
2. Check that it has its old address (`ip -4 -br a show wlan0`). A reservation in the router
   goes by the Pi's hardware, so a new card keeps it.
3. Wi-Fi details and train token: section 7 of [install.md](install.md).
4. Calendar: a new Cloudflare token (step 3 of section 1 of [calendar.md](calendar.md)), then
   its section 2, then the new phone token into the shortcut. Delete the old Cloudflare token.
5. Web interface: [web.md](web.md). Afterwards, put the saved settings back:

       scp settings.backup.json user@printer.local:
       ssh -t user@printer.local 'sudo install -o reporter-web -g "$(id -gn)" -m 640 settings.backup.json /var/lib/reporter-web/settings/settings.json && rm settings.backup.json'

Notes

- The button uses the system's `python3-gpiozero` and `python3-lgpio`. PyPI has no usable
  `lgpio` for this system, and pip would silently install an ancient 0.0.0.2.
- If `apt` ever reports an unsigned Raspberry Pi archive, update
  `raspberrypi-archive-keyring`; do not switch signature checks off.
- An old card holds your Wi-Fi password, your tokens, the certificate's key, your settings,
  the log and perhaps the last calendar. Deleting files does not remove them from a card:
  overwrite it, or destroy it, before it leaves the house.
