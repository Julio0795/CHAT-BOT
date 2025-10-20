@echo off
REM ── make sure we’re sitting in the script’s own folder
cd /d "%~dp0"

echo 🚀 Starting Python backend…
start "Python Backend" cmd /k "python bot.py"

echo 🚀 Starting WhatsApp client…
start "WhatsApp Client" cmd /k "node index.js"

pause
