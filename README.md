# Huizen Zoeker

Local app that monitors Dutch rental sites every hour for new listings in Oss
and Berghem, dedups by address in MySQL, and emails you when something new
within your max price shows up.

## Sites monitored

- directwonen.nl (Oss + Berghem)
- krabben.nl
- funda.nl (Oss + Berghem + Digimakelaars Oss)
- rncwonen.nl
- easyleasewonen.nl
- gapph.nl
- makelaardijdeleygraaf.nl

## Setup

```powershell
cd c:\Users\milov\PersonalProjects\huizen-zoeker

# 1. virtualenv + deps
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium

# 2. config
copy .env.example .env
# edit .env — fill DATABASE_URL, SMTP_*, FLASK_SECRET_KEY
```

### Create the MySQL database yourself

```sql
CREATE DATABASE huizen_zoeker CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'huizen'@'localhost' IDENTIFIED BY 'secret';
GRANT ALL ON huizen_zoeker.* TO 'huizen'@'localhost';
FLUSH PRIVILEGES;
```

Make sure `DATABASE_URL` in `.env` points to it. Format:
`mysql+pymysql://USER:PASSWORD@127.0.0.1:3306/huizen_zoeker`

### Run migrations

```powershell
alembic upgrade head
```

This creates 4 tables (`houses`, `settings`, `email_recipients`, `scrape_runs`)
and inserts a default settings row with max price €1500.

### Start the app

```powershell
python run.py
```

Open <http://127.0.0.1:5000>:

- **Woningen** — list of found houses (most recent first)
- **Instellingen** — set max price + manage notification email addresses
- **Runs** — scrape history per source; use this to debug

The first scrape kicks off ~10 seconds after startup, then every 60 minutes.
Hit **Nu draaien** on the Runs page to trigger manually.

## Run scraper + notifier in the background (Windows logon task)

If you don't need the Flask UI all the time, you can run only the
scraper/notifier scheduler as a background process that starts every time you
log in. There's a headless entry point `run_worker.py` (no Flask, no console
window) and an installer script that registers a Windows Scheduled Task.

```powershell
cd c:\Users\milov\PersonalProjects\huizen-zoeker

# One-time install — registers a task called "HuizenZoeker Worker"
powershell -ExecutionPolicy Bypass -File scripts\install_worker_task.ps1

# Start it immediately (otherwise it starts on next logon)
Start-ScheduledTask -TaskName 'HuizenZoeker Worker'
```

The task runs `.venv\Scripts\pythonw.exe run_worker.py`, restarts up to 3× on
failure, and writes rotating logs to `logs\worker.log`.

Trigger is **At logon** (not system startup) because the funda cookie refresh
job needs an interactive desktop session for the Playwright browser window.

Day-to-day:

```powershell
# Status
Get-ScheduledTaskInfo -TaskName 'HuizenZoeker Worker'

# Tail the log (use -Encoding UTF8 if em-dashes show as â€”)
Get-Content .\logs\worker.log -Tail 30 -Wait -Encoding UTF8

# Stop / start manually
Stop-ScheduledTask  -TaskName 'HuizenZoeker Worker'
Start-ScheduledTask -TaskName 'HuizenZoeker Worker'

# Uninstall
Unregister-ScheduledTask -TaskName 'HuizenZoeker Worker' -Confirm:$false
```

You can still launch `python run.py` separately whenever you want the web UI —
the two won't conflict as long as the schedule times in `.env` aren't running a
scrape at the exact same second on both processes (in practice, just stop the
task while debugging in the UI: `Stop-ScheduledTask -TaskName 'HuizenZoeker Worker'`).

### Finding the worker process in Task Manager

Task Manager doesn't show command lines by default, so the worker just appears
as **`pythonw.exe`** under the *Details* tab. To tell it apart from other
Python processes:

- In Task Manager → *Details* tab → right-click any column header → *Select
  columns* → tick **Command line**. The worker is the row whose command line
  ends with `run_worker.py`.
- Or from PowerShell:

  ```powershell
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
      Select-Object ProcessId, CommandLine
  ```

## Configuration (`.env`)

| Var | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy MySQL URL |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` / `SMTP_USE_TLS` | Outgoing email |
| `FLASK_HOST` / `FLASK_PORT` / `FLASK_SECRET_KEY` | Web UI binding |
| `SCRAPE_TIMES` | Comma-separated HH:MM 24h slots (default `09:00,12:00,17:00,20:00`) |
| `AUTO_REFRESH_FUNDA_COOKIES` | If `true`, refresh `cookies/funda.txt` before each slot via a Playwright session (see below) |
| `FUNDA_COOKIE_REFRESH_LEAD_MINUTES` | Minutes before each scrape to run the refresh (default 30) |
| `SCRAPE_ON_STARTUP` | Run once shortly after startup (default true) |
| `HEADLESS` | Set to `false` to watch the browser (debugging) |
| `SCRAPE_TIMEOUT` | Per-page timeout in seconds (default 45) |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` |

Settings exposed in the UI (max price + email list) live in the database, not
`.env`.

## How dedup works

`address_normalized` is the unique key. The raw address is lowercased,
diacritics stripped, non-alphanumerics removed, whitespace collapsed. The same
physical address from two sites collapses to one row — only the first sighting
fires a notification.

## Tuning the scrapers

I couldn't visit the target sites while writing this, so each scraper's CSS
selectors are best-effort guesses. After the first run, check the **Runs** page
— if a source shows `0 found`, open the corresponding file in
`huizenzoeker/scrapers/` and adjust:

- `LISTING_CONTAINER_SELECTOR` — CSS for one listing card
- `ADDRESS_SELECTOR` / `PRICE_SELECTOR` / `TITLE_SELECTOR` — within a card
- `LISTING_LINK_REGEX` — regex on `href` if you want the anchor-based fallback

Tip: set `HEADLESS=false` in `.env` and trigger a manual run to watch what the
browser actually loads. Funda is Cloudflare-protected and may occasionally
block — failed runs get recorded with the error message rather than crashing
the cycle.

## Funda cookies

Funda sits behind Akamai/Cloudflare bot protection, so the scraper rides a real
browser session by injecting `cookies/funda.txt` (a `name=value; …` dump) before
navigating. Those cookies expire, so they get refreshed by
`scripts/refresh_funda_cookies.py`.

The script launches **Playwright's own Chromium** with a persistent profile
(`cookies/pw_profile/`), navigates funda, accepts the cookie banner, lets Akamai
set its `bm_*`/`ak_bmsc` tokens, then reads the cookies straight from the browser
context. No admin rights and no decryption are needed — Chrome 127+ app-bound
encryption doesn't apply because the cookies never leave the Playwright session.
It reuses the scraper's user-agent + stealth tweaks so the fingerprint matches
when the cookies are injected back in.

Three ways it runs:

- **Automatically** before each scrape slot when `AUTO_REFRESH_FUNDA_COOKIES=true`
  (lead time `FUNDA_COOKIE_REFRESH_LEAD_MINUTES`, default 30). Works under the
  background logon task — the refresh opens a visible Playwright window, which is
  why the task triggers *At logon* (interactive desktop required).
- **Manually from the UI** — the **Funda-cookies verversen** button on the *Runs*
  page fires the same job on the background scheduler.
- **From the command line:**

  ```powershell
  .\scripts\refresh_funda_cookies.ps1              # visible window (default)
  .\scripts\refresh_funda_cookies.ps1 --headless   # no window (less reliable vs Akamai)
  .\scripts\refresh_funda_cookies.ps1 --wait=45    # longer settle time
  ```

> Note: the refresh always runs headed unless you pass `--headless`; the
> `HEADLESS` env var only affects the *scraper*, not the refresh.

**Legacy fallback.** Passing `--use-system-browser` reverts to reading cookies
out of your real browser's store (via CDP → rookiepy → browser-cookie3). That
path needs `scripts\start_funda_chrome.ps1` first (launches Chrome with
`--remote-debugging-port=9222`) and is only kept as a fallback — the default
Playwright session needs none of it.

## Project layout

```
huizen-zoeker/
├── run.py                          # entry point (Flask UI + scheduler)
├── run_worker.py                   # headless entry point (scheduler only)
├── scripts/
│   ├── install_worker_task.ps1     # registers the Windows logon task
│   ├── refresh_funda_cookies.py    # refresh cookies/funda.txt via Playwright session
│   ├── refresh_funda_cookies.ps1   # venv-activating wrapper for the above
│   └── start_funda_chrome.ps1      # legacy: Chrome w/ debug port (--use-system-browser only)
├── .env.example
├── requirements.txt
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/0001_initial.py
└── huizenzoeker/
    ├── __init__.py                 # Flask app factory
    ├── config.py                   # .env loader
    ├── db.py                       # SQLAlchemy engine + session_scope()
    ├── models.py                   # House, Settings, EmailRecipient, ScrapeRun
    ├── normalize.py                # address normalization + price parser
    ├── notifier.py                 # SMTP + email rendering
    ├── scheduler.py                # APScheduler hourly job
    ├── routes.py                   # Flask views
    ├── templates/                  # base, houses, settings, runs, email_notification
    └── scrapers/
        ├── base.py                 # BaseScraper, fetch via Playwright/requests
        ├── runner.py               # orchestrates one cycle, dedup, notify
        ├── directwonen.py
        ├── krabben.py
        ├── funda.py
        ├── rncwonen.py
        ├── easyleasewonen.py
        ├── gapph.py
        └── deleygraaf.py
```
