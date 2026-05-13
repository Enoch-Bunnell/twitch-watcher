@echo off
REM Adds a shortcut to start_watcher.bat into your Windows Startup folder so
REM the watcher launches automatically each time you log in. Idempotent: if
REM the shortcut already exists, it's left alone.

cd /d "%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT=%STARTUP%\Twitch Watcher.lnk"
set "TARGET=%~dp0start_watcher.bat"

if exist "%SHORTCUT%" (
    echo Already in Startup:
    echo   %SHORTCUT%
    pause
    exit /b 0
)

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%SHORTCUT%'); $sc.TargetPath = '%TARGET%'; $sc.WorkingDirectory = '%~dp0'; $sc.Save()"

if exist "%SHORTCUT%" (
    echo.
    echo Added: %SHORTCUT%
    echo Target: %TARGET%
    echo.
    echo The watcher will start automatically when you log in.
    echo Run disable_autostart.bat to turn this off.
) else (
    echo Failed to create the Startup shortcut. PowerShell may have errored above.
)
pause
