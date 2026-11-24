# The web interface

`https://printer.example.com:8444`, on the home network only, behind a password. It chooses
what the receipt shows and when, the weather place, the Tube line, headlines, trains, what
the button does and how dark it prints. It can print, and show a preview without paper. On a
phone, Share > Add to Home Screen gives it an icon.

## Setting it up

1. Do sections 1 to 3 of [calendar.md](calendar.md) first: the web interface uses the same
   name and certificate, and devices must be able to find the name.
2. On your computer, in a terminal: `./deploy.sh --web`. It asks for the Pi's password and for
   a new password for the pages (at least 12 characters), and tests itself at the end.
3. Open the address above.

If you want the pages but not the calendar, take Calendar off under Receipt, or every receipt
says "Calendar not received". Leave the drop box on: the health page reads the certificate's
last day through it.

- Change the password, make a new phone token, enter the train token: *Keys*, at the top of
  every page. The same on the Pi: `setup-web.sh --new-password`, `setup-calendar.sh
  --new-token`, `rail-setup`. The Cloudflare token is only there: whoever has it can change
  every record of the domain.
- **Forgotten the password of the pages?** On your computer, in a terminal:

      ssh -t user@printer.local 'bash reporter/deploy/setup-web.sh --new-password'

  It asks for the Pi's own password and then for the new one, twice. Every device is signed
  out; settings, tokens and the calendar stay as they are. The button and the daily receipt
  work all the time.
- **Forgotten the Pi's own password too?** Nothing can be changed on it without that. Set up a
  new card: [rebuild.md](rebuild.md). If your SSH key still works, save the settings first, as
  it says there.
- Update it after changing the code: `./deploy.sh --web` again. A plain `./deploy.sh` says if
  this is needed, because the pages run from a copy that only root can change.
- Switch it off:
  `sudo systemctl disable --now reporter-web-tls.socket reporter-web-tls.service reporter-web.socket reporter-web.service`
  Its choices stay in force; to drop them too,
  `sudo rm /var/lib/reporter-web/settings/settings.json`. On again: `./deploy.sh --web`.

## The pages

| Page | What is there |
|---|---|
| Today | when the next receipt comes, print buttons, health, preview |
| Receipt | which blocks, in which order |
| Times | a time for each day, and how long to keep trying |
| Content | weather place, warnings region, pollen, lines, feeds, trains, sudoku |
| Button | taps and holds for any block; several can share one |
| Heat | how dark it prints, and a strip to compare |
| Phone | how to set up the calendar and reminders on an iPhone, and whether a list has come |
| Keys | the password, a new phone token, the train token |

"Go back to the original" on any form returns to what `config.toml` and `config.local.toml`
say.

## How it works

    browser --HTTPS--> reporter-tls --local socket--> reporter-web --settings.json--> reporter
                       (has the key)                  (has the pages) --empty file--> reporter requests
                                                       <-- status.json, previews (read only) --

- **reporter-tls** holds the certificate and passes bytes on; it understands nothing of them
  and can write nothing. **reporter-web** has the pages, but no network and no key (the key
  also protects the calendar drop box). Each is its own account in its own sandbox.
- The web program cannot print, fetch anything, or see the home folder, the calendar list or
  the printer. It writes one settings file, its password if changed on the page, the
  fingerprint of a phone token it has just made, and files named after what it wants
  (`receipt`, `preview`...). They are empty but for one: a train token on its way to the
  reporter, which deletes it at once, tries it and keeps it where the pages cannot read. A systemd path unit then runs
  `reporter requests` as the normal account, which does only what is on its own list. No sudo
  is involved.
- All it can write to is a 16 MB disk of its own (`/var/lib/reporter-web.img`), so it cannot
  fill the SD card.
- `settings.json` (in `/var/lib/reporter-web/settings`) lies over the configuration files, so
  a deploy does not undo what was chosen here.
- Every value is checked by `reporter/settings.py` when saved and again when read. A group
  that is wrong is ignored, the configuration file is used instead, and the health page says
  so.
- `reporter.timer` runs every five minutes and nearly always ends at once; the program
  decides from the settings whether a receipt is due. That is how times change without root.
- Switching and moving blocks shows on the paper at once: every block is drawn once, and the
  page puts them together. A picture that is being made is waited for, up to 30 seconds, so
  that nothing has to be reloaded.
- Previews show an example calendar and example reminders. Real titles only ever go on paper,
  and the Wi-Fi details, a stored train token and the password are never shown on a page. A
  new phone token is shown once.

## The look

1930s railway posters. Every drawing says something: the train is the chosen blocks in order,
the clock shows the next print, a lowered signal a source in use, the gauge the heat. The sky
follows the sun at the weather place (`sun.py`, worked out on the Pi) and the engine takes the
highlighted line's colour.

- `art.py` drawings and icons, `pages.py` the pages, `style.css` colours and movement. No
  scripts: what reacts at once does so with CSS `:has()`. Design notes: [design.md](design.md).
- `static/` fonts and the home-screen icon.
- `tools/make_pictures.py` draws the printed poster, the icon and the pictures in these
  guides from the same art; `tools/make_renders.py` the strips of paper in the README. Both
  need Chrome on a Mac; run them after changing the art or a block.

## Safety

- Password stored as scrypt; five free tries, then each costs more waiting, up to 2 minutes.
  The waiting is for everybody, so somebody on the home network can keep you from signing in
  (not from using the button, and not if you are signed in already).
- Sessions are kept in memory, end after 30 idle minutes or 12 hours, and are lost when the
  service restarts (sign in again). Changing the password ends all but the one
  that changed it.
- Every request must name exactly this host and port; every form needs a session, its own
  token and an Origin that is exactly this site.
- No scripts at all, nothing from outside, a strict content policy, no page cached. The log
  says who changed which group, never the contents.
- At most 10 prints a day can be asked for here, so a program gone wrong cannot use up the
  roll. The button and the daily receipt do not count.
- Feeds and other sites are given up after a fixed time however slowly they answer. Feeds must
  be public https addresses, and no site can redirect to anything else.
- If you suspect that somebody has been in: `bash deploy/setup-web.sh --new-password` on the
  Pi. A deploy alone keeps a password that was changed on the page.
- What it does not prevent: the web program has no network of its own, but it can choose feed
  addresses, which the reporter then fetches. Taken over, it could pass on in such an address
  whatever the pages show, and the password or token you type, and make itself a phone token.

## When something is wrong

| What you see | What it means |
|---|---|
| "That was not the password" | Forgotten it? See *Setting it up* above. After several tries you have to wait up to two minutes |
| The page does not open | The device cannot find the name ([calendar.md](calendar.md), section 3), or the Pi is off |
| "Waiting for the printer program" | `journalctl -u reporter-requests`; then `./deploy.sh --web` |
| "Settings to put right" | A value in `config.local.toml` is not one the pages offer: correct it and deploy |
| It opens and drops at once | `systemctl --failed`; then `./deploy.sh --web` |
| "The printer program is not answering" | `systemctl status reporter-requests.path` |
| "Some settings were ignored" | They were damaged or out of range: save that page again |
| It does not start after a changed password | The password file is damaged, and an old password is never used instead. On the Pi: `cd reporter && bash deploy/setup-web.sh --new-password` |

    journalctl -u reporter-web-tls -u reporter-web -u reporter-requests   # what happened
