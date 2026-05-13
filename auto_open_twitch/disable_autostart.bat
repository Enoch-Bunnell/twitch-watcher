@echo off
REM Copyright 2026 Enoch Bunnell, AlyxiC
REM SPDX-License-Identifier: Apache-2.0
REM See LICENSE in the project root for the full Apache License 2.0 text.

REM Removes the watcher's Startup-folder shortcut so it stops auto-launching.

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT=%STARTUP%\Twitch Watcher.lnk"

if not exist "%SHORTCUT%" (
    echo No Startup shortcut found.
    echo The watcher is not currently set to autostart.
    pause
    exit /b 0
)

del "%SHORTCUT%"
if not exist "%SHORTCUT%" (
    echo Removed: %SHORTCUT%
    echo Watcher will no longer autostart at login.
) else (
    echo Failed to remove the shortcut. You may need to delete it manually:
    echo   %SHORTCUT%
)
pause
