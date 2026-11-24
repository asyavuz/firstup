# Calendar and reminders, from an iPhone

    iPhone (Shortcuts) --HTTPS--> Pi, port 8443 --> one text file --> receipt

The Pi never has a calendar login or link. The phone sends one day's times and titles, over
your own Wi-Fi. A list is kept for its day, so that the button can print it again, and is
deleted within 10 minutes of midnight, or when the Pi next runs. A list for a later day is
kept.

You need a domain name of your own (any will do), because an iPhone only talks to a server
with a real certificate. A name costs about £10 a year; Let's Encrypt and Cloudflare's DNS
are free. Buy it anywhere, then add it at Cloudflare, which tells you which name servers to
set. The examples use `printer.example.com` and `192.168.1.50`.

## 1. Name

1. **Reserve the Pi's address in the router** (often called *DHCP reservation* or *static
   lease*) and restart the Pi (`sudo reboot`). Without it the router may one day hand out another address,
   and the phone's list would go to some other device.
2. At your DNS provider, add an **A record**: `printer` -> `192.168.1.50`. At Cloudflare:
   **DNS only** (grey cloud).
3. At Cloudflare, make an **API token** (here: the *Cloudflare token*): My Profile > API Tokens > Create > *Edit zone DNS*,
   Zone Resources: that one domain. Let's Encrypt cannot reach the Pi from the internet, so
   it checks a temporary DNS record; the token lets the Pi add and remove it.
4. Put the name in `config.local.toml` and run `./deploy.sh`:

       [events]
       host = "printer.example.com"

The token stays on the Pi (`/etc/letsencrypt/cloudflare.ini`, root only) so that the
certificate can renew itself. Cloudflare cannot limit a token to one record: anyone who is
root on the Pi could change any record of that domain, including mail. A domain used for
nothing else avoids that. To revoke the token, delete it at Cloudflare; the certificate then
stops renewing.

The name will be public, in the lists of issued certificates, and so will be the number it
leads to (192.168.1.50), which means nothing outside your home.

**Another DNS provider:** get the certificate yourself first, on the Pi, with
[certbot](https://certbot.eff.org/) and the plugin for your provider, under exactly that name
(`/etc/letsencrypt/live/printer.example.com/`), and check that it renews itself. Section 2
then uses it and asks for no token.

## 2. Drop box

On your computer, in a terminal:

    ssh -t user@printer.local 'bash reporter/deploy/setup-calendar.sh printer.example.com'

It asks for the Pi's password, the Cloudflare token (hidden) and `yes` to Let's Encrypt's
terms, then shows the **phone token once**. Only a fingerprint of it (SHA-256) is kept.
After changing `deploy/receipt_inbox.py`, run `./deploy.sh`, then this again; it keeps the
certificate and the token.

- New phone token: add `--new-token`, or use *Keys* in the web interface (then that one
  counts, at once). Change the shortcut afterwards.
- Other Cloudflare token: change it in `/etc/letsencrypt/cloudflare.ini` (with sudo).
- Switch it off: `sudo systemctl disable --now receipt-inbox.socket`, and take `events` out of
  the blocks. Leave it on if you have the web interface.
- Log (who sent when, never what): `journalctl -u receipt-inbox`
- Renewal of the certificate: `systemctl list-timers certbot.timer`, `sudo certbot renew --dry-run`

| Reply | Meaning |
|---|---|
| 200 Stored 3 events for Wednesday 25 November | accepted |
| 400 | the first line is not a date from today to two days ahead |
| 401 | wrong token |
| 404, 405, 411, 413 | wrong path, wrong method, no length, too long (8 KB) |

What is sent, to `/calendar` or `/reminders`:

    POST /calendar
    Authorization: Bearer <phone token>
    {"list": "2026-11-25\n09:30-10:00 Dentist\nAll day Parents visiting"}

Anything that can send this can take the place of the iPhone.

## 3. Finding the name

Many routers hide public names that lead to home addresses (*DNS rebinding protection*).
Then the phone cannot find the Pi, and Shortcuts just says **"bad URL"**, which really means
"cannot connect"; the address in the shortcut is almost never wrong. Either

- in the router, exempt `printer.example.com` from that protection, or give it a local DNS
  entry for `192.168.1.50`; or
- on the phone: Settings > Wi-Fi > (i) > Configure DNS > Manual: `1.1.1.1` and `1.0.0.1`.
  *Limit IP Address Tracking* can stay on.

## 4. Shortcut "Post Calendar To Printer"

The web interface shows these steps too, under *Phone*, with your own address filled in.

1. **Get Network Details**: Network Name of Wi-Fi
2. **If** Network Name **is** your home Wi-Fi; everything below goes inside, Otherwise empty
3. **Adjust Date**: add **0 days** to Current Date
4. **Format Date** (Adjusted Date): Custom `yyyy-MM-dd`; **Set Variable** `Day`
5. **Find Calendar Events**: Start Date **is today**; sort by Start Date, Oldest First; no
   limit. Add a Calendar filter to leave calendars out; without one it uses them all.
6. **Repeat with each** Calendar Event
   - **Format Date**: the Repeat Item's **Start Date** (not the item itself), Custom `yyyy-MM-dd`
   - **If** Formatted Date **is** `Day`
     - **If** the Repeat Item's *Is All Day* is Yes: **Text** `All day [Title]`
     - **Otherwise**: **Text** `[Start Date]-[End Date] [Title]`, both dates Custom `HH:mm`
7. **Combine Text**: Repeat Results, New Lines
8. **Text**: `[Day]`, then `[Combined Text]` on the next line
9. **URL**: `https://printer.example.com:8443/calendar`
10. **Get Contents of URL** (that URL): POST; header `Authorization` = `Bearer <phone token>`;
    Request Body JSON with one Text field `list` = the Text from step 8
11. **Show Notification**: Contents of URL

Run it once by hand and allow everything it asks, with *Always Allow*. Until then an
automation may stop without a word.

Automations: Time of Day, before the receipt and once more to be sure (07:00 and 07:30 for a
receipt at 08:00), every day, Run Immediately. The list waits on the Pi until its day is over.
Sending twice is harmless. It works with the phone locked. *Allow Running Scripts* is not
needed; leave it off. To test an automation: Charger > Is Connected, then plug it in. The
shortcut holds the phone token and your domain, so do not share it.

It sends the events that **start** on the day, so a trip that began earlier shows only on its
first day. To send the evening before instead: Adjust Date 1 day, Start Date *is in the next 2
days*. Do not mix the two: the Pi keeps one list, so tomorrow's replaces today's.

## 5. Reminders

Add these to the end of the same shortcut, still inside the If:

1. **Find Reminders**: **Is Not Completed**, and **List** is the one you want on paper; no
   limit. Leave the due date out of it: the printer chooses by that. Without a List every open
   reminder is sent, and more than 8 KB is refused.
2. **Repeat with each** Reminder: **Text** `[Due Date] [Title]`, which is the Repeat Item twice
   with a space between
   - tap the first: *Due Date*, with the date format Custom `yyyy-MM-dd HH:mm`
   - tap the second: *Title*

   One without a due date is just its title; one without a time gets 00:00, which the printer
   takes as "today".
3. **Combine Text**: Repeat Results, New Lines
4. **Text**: `[Day]`, then `[Combined Text]` on the next line
5. **URL**: `https://printer.example.com:8443/reminders`
6. **Get Contents of URL**: as in step 10 above, with the same token and the Text from step 4
7. **Show Notification**: Contents of URL

They print with a box to tick, up to 12 of them: first what is **overdue**, then today's by
time, then the rest of **today**'s, then those without a due date. Later ones are left out
until their day. With none, or none sent, the block is left out. Only today's, and nothing
overdue or undated: add *Due Date is today* to step 1. No deadlines on paper: only `[Title]`
in step 2. Run the shortcut by hand once more: it asks to see your reminders.

## If the receipt says "Calendar not received"

| Check | How |
|---|---|
| Did the shortcut run? | Run it by hand and read the reply |
| "bad URL" or a timeout, worked before | The Pi has moved: `ping printer.local` should be 192.168.1.50. Check the reservation, restart the Pi |
| "bad URL" on a new phone or network | Section 3 |
| "Stored no events" on a busy day | Step 5 filter; step 6 must use Start Date |
| 400 | Step 4 format, and step 10 must send the Text from step 8 |
| Phone restarted overnight | Unlock it once; before that it may not read the calendar |
| Nothing in the log | Not on home Wi-Fi, or the Pi has moved (above) |

## Safety

- Reachable from the home network only (firewall, and again in the unit). TLS 1.2 or newer.
- Runs as its own account in a systemd sandbox: it can write into one folder, and is started
  only when something connects. Replies hold nothing but a date and a count of what was just
  sent. The token has 256 bits and is kept only as a fingerprint.
- What that does not prevent: taken over, it could fill the SD card.
- A list is treated as untrusted: limited in size, cleaned, and printed as a picture, so that
  nothing in it can be taken as a command.
