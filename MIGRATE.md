# Migrate Huizen Zoeker to a new project location

One-off guide for switching the working copy from
`C:\Users\milov\PhpstormProjects\huizen-zoeker` to
`C:\Users\milov\PersonalProjects\huizen-zoeker` on Windows. Delete this file
once the move is done.

> **Direction:** push from PhpstormProjects → delete PersonalProjects →
> re-clone into PersonalProjects → set up the background task there.

## What breaks on a move

- **Scheduled Task `HuizenZoeker Worker`** — currently registered for the
  `PersonalProjects` path that you're about to wipe. After the delete it will
  silently fail on next logon until re-registered.
- **The `.venv` folder** — Windows virtualenvs are path-bound; the fresh clone
  won't have one, so it must be created from scratch.

## What survives the clone (no action needed)

- All code in `huizenzoeker/` uses `__file__`-relative paths
- Database — `DATABASE_URL` points at `127.0.0.1`, MySQL data doesn't move
- The `install_worker_task.ps1` script uses `$PSScriptRoot`, so it auto-detects
  whatever path it's run from

## Local-only files that AREN'T in git

These hold secrets / browser state and must be copied across by hand. Source
of truth is the PhpstormProjects copy (the one being pushed):

- `.env`
- `cookies/funda.txt`
- `cookies/pw_profile/`   *(Playwright persistent profile — keeps you logged in
  so the cookie refresh job doesn't have to clear the cookie banner again)*

## Migration steps

Run these from PowerShell.

### 1. Push the PhpstormProjects copy to git

```powershell
cd C:\Users\milov\PhpstormProjects\huizen-zoeker
git status
git add -A
git commit -m "Migration prep"
git push
```

### 2. Stop and unregister the current scheduled task

It points at `PersonalProjects\...\pythonw.exe` — that path is about to
disappear. Clean it up before the delete so it doesn't keep retrying.

```powershell
Stop-ScheduledTask       -TaskName 'HuizenZoeker Worker' -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'HuizenZoeker Worker' -Confirm:$false
```

Verify it's gone:

```powershell
Get-ScheduledTask -TaskName 'HuizenZoeker*' -ErrorAction SilentlyContinue
```

### 3. Make sure no worker process is holding the old folder

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*run_worker.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

### 4. Stash the local-only files somewhere safe

Copy from PhpstormProjects to a temp folder, since PersonalProjects is about to
be wiped and we need them again afterwards. (PhpstormProjects keeps a copy too,
but a separate stash is one less thing to think about.)

```powershell
$stash = "$env:TEMP\huizen-zoeker-local"
New-Item -ItemType Directory -Force $stash | Out-Null
Copy-Item "C:\Users\milov\PhpstormProjects\huizen-zoeker\.env"     "$stash\.env"
Copy-Item "C:\Users\milov\PhpstormProjects\huizen-zoeker\cookies"  "$stash\cookies" -Recurse
```

### 5. Delete the old PersonalProjects folder

```powershell
Remove-Item -Recurse -Force C:\Users\milov\PersonalProjects\huizen-zoeker
```

### 6. Clone the repo into PersonalProjects

```powershell
cd C:\Users\milov\PersonalProjects
git clone <repo-url> huizen-zoeker
cd huizen-zoeker
```

### 7. Restore the stashed local-only files

```powershell
$stash = "$env:TEMP\huizen-zoeker-local"
Copy-Item "$stash\.env"     ".\.env"
Copy-Item "$stash\cookies"  ".\cookies" -Recurse -Force
```

### 8. Create the venv + install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

### 9. Run database migrations

If the schema is already up to date (same MySQL DB as before), this is a no-op
but safe to run.

```powershell
alembic upgrade head
```

### 10. Register the scheduled task at the new path

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_worker_task.ps1
Start-ScheduledTask -TaskName 'HuizenZoeker Worker'
```

### 11. Verify

```powershell
# Status (LastTaskResult 267009 = SCHED_S_TASK_RUNNING = good)
Get-ScheduledTaskInfo -TaskName 'HuizenZoeker Worker'

# Two pythonw.exe rows expected (venv launcher + real interpreter), both
# with ExecutablePath under PersonalProjects\huizen-zoeker
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Select-Object ProcessId, ParentProcessId, ExecutablePath |
    Format-Table -AutoSize

# Tail the worker log
Get-Content .\logs\worker.log -Tail 30 -Wait -Encoding UTF8
```

You should see a fresh `Worker starting` line followed by `Scheduler started —
times=...`. If `SCRAPE_ON_STARTUP=true` in `.env`, the first scrape kicks off
~10 seconds later.

### 12. Clean up

Once step 11 confirms everything works:

```powershell
# Remove the local-only file stash
Remove-Item -Recurse -Force "$env:TEMP\huizen-zoeker-local"

# Delete this migration guide
Remove-Item .\MIGRATE.md
git add MIGRATE.md
git commit -m "Remove one-off migration guide"
git push
```

Optionally also delete the old PhpstormProjects working copy now that
PersonalProjects is the live one:

```powershell
Remove-Item -Recurse -Force C:\Users\milov\PhpstormProjects\huizen-zoeker
```

## Rollback

If something goes wrong between step 5 and step 11, the PhpstormProjects copy
still has all your files (including `.env` and `cookies/`). Re-register the
task pointing there:

```powershell
cd C:\Users\milov\PhpstormProjects\huizen-zoeker
powershell -ExecutionPolicy Bypass -File scripts\install_worker_task.ps1
Start-ScheduledTask -TaskName 'HuizenZoeker Worker'
```

You can resume the migration later, or stay on PhpstormProjects.
