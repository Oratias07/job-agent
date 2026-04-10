@echo off
:: Job Agent Telegram Bot — local launcher
:: Reads secrets from .env in the same directory, then loops forever.

cd /d "%~dp0"

:: Load .env if it exists
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "%%A=%%B"
    )
)

:loop
echo [%DATE% %TIME%] Starting bot...
python bot_listener.py
echo [%DATE% %TIME%] Bot exited (code %ERRORLEVEL%). Restarting in 5s...
timeout /t 5 /nobreak >nul
goto loop
