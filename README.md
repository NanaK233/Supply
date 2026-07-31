# Supply Restock

A small self-contained site for Eddie & Danilo to track weekly supply restocking,
flag items running low off-schedule, and get email alerts before deadlines.
Runs on the Python 3 that's already on your Mac — **nothing to install.**

## Run it

```bash
cd ~/Desktop/Supply
python3 app.py
```

Then open **http://localhost:8765** in your browser. Leave the terminal window
open while you're using it; press `Ctrl+C` to stop.

## Two logins (roles)

Everyone opens the same site and signs in with a **passcode**. The passcode decides
what they can do:

- **Admin (you)** — full control: edit schedules, delete items, approve smart
  suggestions, and configure/send alerts.
- **Staff (Eddie & Danilo)** — see all items and how much stock is left, add new
  items, update stock levels, flag items low, and mark items restocked.

Set both passcodes in `config.json` (`admin_passcode`, `staff_passcode`). The
starter file ships with demo passcodes — **change them before real use:**

- Admin: `boss-1234`
- Staff: `team-5678`

Roles are enforced on the server, so staff can't perform admin actions even if they
try — it's not just hidden in the screen.

## What it does

- **Add / edit items** — name, owner (Eddie / Danilo / Shared), quantity, category,
  and how often it should be restocked (the cadence, in days).
- **Status at a glance** — every item is color-coded: Running low, Overdue, Due today,
  Coming up, or On track. The four cards at the top count each.
- **✓ Restocked** — resets the clock; next due date = today + cadence.
- **⚠ Flag low** — reports an item is running low *before* its scheduled date.
- **Smart schedule suggestions** — if an item keeps getting flagged low early, the
  site suggests a tighter cadence. You **Approve** or **Dismiss** — it never changes
  the schedule on its own.
- **Email alerts** — a daily digest of what needs attention (see below).

## WhatsApp alerts to you (one-time setup)

Set `"channels": ["whatsapp"]` (or `["email","whatsapp"]` for both) in `config.json`,
then fill in the `whatsapp` block. Two provider options:

**Option 1 — CallMeBot (simplest, free, sends to *your own* number):**
1. Add the CallMeBot number **+34 644 51 95 23** to your phone contacts.
2. Send it this WhatsApp message: `I allow callmebot to send me messages`.
3. You'll get a reply with your personal **API key**.
4. Put your number and that key in `config.json`:
   ```json
   "whatsapp": { "provider": "callmebot",
                 "callmebot_phone": "+1XXXXXXXXXX",
                 "callmebot_apikey": "123456" }
   ```

**Option 2 — Twilio (more robust, can message multiple people, has a free trial):**
Fill in `twilio_sid`, `twilio_token`, `twilio_from`, and `twilio_to`. Use the Twilio
WhatsApp Sandbox to test immediately.

Then use **Alerts → Send now** in the site (admin only) to fire a test.

## Email alerts (one-time setup)

1. Copy the template and fill in your email details:
   ```bash
   cp config.example.json config.json
   ```
2. Edit `config.json`. For Gmail / Google Workspace (business@propgda.com), you need
   an **App Password** (Google Account → Security → 2-Step Verification → App
   passwords), not your normal password. Put Eddie's and Danilo's addresses in
   `recipients`.
3. Use **Preview alert → Send now** in the site to send a test.

`config.json` holds a password — keep it private, don't email or commit it.

## Automatic daily 8am send (already set up)

This is running via a macOS **LaunchAgent** (launchd), not cron — launchd runs the
job when your Mac wakes even if it was asleep at 8am, which cron doesn't do.

- Schedule definition: `~/Library/LaunchAgents/com.propgda.restock.daily.plist`
- It runs `notify.py` daily at 08:00, which reads the same database and sends on
  your configured channels. The website does **not** need to be open for this.
- Output/errors are logged to `restock.log` in this folder.

Useful commands:

```bash
# See it registered (exit code 0 = healthy):
launchctl list | grep restock

# Send right now to test:
launchctl start com.propgda.restock.daily

# Change the time: edit the plist's Hour/Minute, then reload:
launchctl unload ~/Library/LaunchAgents/com.propgda.restock.daily.plist
launchctl load -w ~/Library/LaunchAgents/com.propgda.restock.daily.plist
```

Note: the digest only sends when something actually needs attention (due soon,
overdue, running low, or a pending suggestion) — so no daily "all clear" spam.
Your Mac must be on/awake at (or after) 8am for that day's send.

**Note:** this folder lives at `~/Desktop/Supply`. macOS blocks *background* jobs
(launchd/cron) from reading Desktop/Documents/Downloads, so a **local** scheduled
send won't work here — but the daily digest now runs in the cloud (GitHub Actions,
below), which is unaffected. If you ever switch back to a local Mac scheduler, move
this folder out of the Desktop first.

## Cloud daily digest (free — GitHub Actions)

The daily WhatsApp is sent from the cloud by GitHub Actions, so it fires even when
your Mac is off. The website still runs locally; the app auto-syncs its data
(`restock.db`) up to GitHub so the cloud digest always has your latest schedule.

- Workflow: `.github/workflows/daily-digest.yml` (runs 04:00 UTC = 08:00 UAE).
- Secrets (set in the GitHub repo, **not** in code): `CALLMEBOT_PHONE`,
  `CALLMEBOT_APIKEY`.
- Local data sync: run the site with `RESTOCK_GIT_SYNC=1` and it pushes `restock.db`
  to GitHub whenever it changes. Push auth uses your saved GitHub credentials.

Test the cloud send anytime: GitHub repo → **Actions** tab → *Daily restock digest*
→ **Run workflow**.

Limitations of the free route: the website isn't hosted 24/7 (local only), and the
cloud digest is only as current as the last successful data sync. For an always-on
hosted website too, move to a paid host (~$5/mo) — ask me.

## Files

| File | What it is |
|------|-----------|
| `app.py` | The web server + API |
| `store.py` | Database logic (items, events, adaptive suggestions) |
| `notify.py` | Builds and emails the digest |
| `static/` | The web page (HTML / CSS / JS) |
| `restock.db` | Your data (created automatically) |
| `config.json` | Your email settings (you create this; keep private) |

## Notes & next steps

- **Access:** right now anyone who can reach the link can edit. Ask me to add a
  shared password when you're ready.
- **Always-on notifications:** cron works while your Mac is awake. For alerts that
  fire even when your computer is off, the app can be deployed to a small cloud host —
  ask me and I'll walk through it.
- **SMS/Slack alerts** can be added on top of email later.
