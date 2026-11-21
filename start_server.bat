@echo off
:: =====================================================================
:: Scholar Vision v2.1 - one-click launcher
::   1) API window   2) analysis worker (only when Redis is up)
::   3) cloudflared tunnel (project-local cloudflared.exe)
::   4) connection_guardian watchdog
::
:: IMPORTANT: this file is deliberately ASCII-only. cmd.exe tracks batch
:: files by byte offset; multibyte characters (e.g. Chinese comments) can
:: shift the offset and make cmd re-parse half a comment as a command.
:: Keep this file in English.
::
:: Queue mode: worker.py only matters when Redis is reachable. The script
:: probes port 6379:
::   - Redis up   -> worker window opens, analyses run out-of-process
::   - Redis down   -> skipped; API falls back to in-process execution
:: Easiest Redis: docker compose up -d redis
::
:: Note: we no longer run "taskkill /F /IM python.exe" (that killed EVERY
:: python process on the box). We only kill the stale listener on :8000.
:: =====================================================================

cd /d "%~dp0"

:: 1. Remove last run's tunnel log
if exist tunnel_log.txt del tunnel_log.txt

:: 2. Kill only whatever is listening on port 8000 (precise, no python.exe massacre)
::    NOTE: never put literal ( ) inside the echo of a parenthesized block -
::    cmd ends the block at the first ), which broke startup with
::    "... was unexpected at this time." Keep this message paren-free.
echo Cleaning up port 8000...
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo Killing stale listener on :8000 PID %%p ...
    taskkill /F /PID %%p >nul 2>&1
)

:: 3. FastAPI backend in its own window (--reload now only affects the API;
::    long analyses live in the worker, so code saves can't cut them off)
echo Starting FastAPI Backend...
start "ScholarVision-API" cmd /k "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

:: 4. Probe Redis (1.5s TCP connect); only then launch the worker
echo Checking Redis on 127.0.0.1:6379...
powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient;$r=$c.BeginConnect('127.0.0.1',6379,$null,$null);$ok=$r.AsyncWaitHandle.WaitOne(1500);$c.Close();exit $(if($ok){0}else{1})"
if %errorlevel%==0 (
    echo Redis detected. Starting analysis worker...
    start "ScholarVision-Worker" cmd /k "python worker.py"
) else (
    echo Redis not running. Skipping worker. API falls back to in-process execution.
    echo Tip: docker compose up -d redis  enables Redis queue mode
)

:: 5. Cloudflare tunnel via the project-local cloudflared.exe
::    (the old ..\Dev-Toolbox\code_tools path is dead; tunnel_log.txt used to
::    contain nothing but "The system cannot find the path specified")
echo Starting Cloudflared Tunnel...
if not exist "%~dp0cloudflared.exe" (
    echo [ERROR] cloudflared.exe not found next to this script.
    echo         Put cloudflared.exe into the ScholarVision folder, then rerun.
    goto :after_tunnel
)
start /b cmd /c ""%~dp0cloudflared.exe" tunnel --url http://127.0.0.1:8000 --protocol http2 > tunnel_log.txt 2>&1"

:: 6. Watchdog, 3s later (gives cloudflared time to write the URL into the log).
::    NOTE: use ping, not "timeout /t": timeout.exe errors out when stdin is
::    redirected, which would silently skip the watchdog launch.
echo Starting connection_guardian...
start /b cmd /c "ping -n 4 127.0.0.1 >nul && python connection_guardian.py"

:after_tunnel
echo ====================================================
echo Services Started.
echo 1. Backend window: check it for errors!
echo 2. Worker window: only opens when Redis is up (queue mode).
echo 3. Your public URL: see tunnel_log.txt, or the watchdog window
echo    prints it after "Weblink:". It changes on every restart
echo    (free quick tunnels get a random subdomain).
echo ====================================================
pause
