@echo off
REM Copyright 2026 Enoch Bunnell, AlyxiC
REM SPDX-License-Identifier: Apache-2.0
REM See LICENSE in the project root for the full Apache License 2.0 text.

REM Launches Opera GX with --remote-debugging-port=9222 so watcher.py can
REM detect whether a streamer's tab is already open. Opera GX is Chromium-
REM based so it speaks the standard Chrome DevTools Protocol on port 9222.
REM
REM Close ALL Opera GX windows first -- Opera silently ignores the debug
REM flag if an existing instance is already using the same profile.

setlocal

set "OPERA="
if exist "%LOCALAPPDATA%\Programs\Opera GX\launcher.exe" set "OPERA=%LOCALAPPDATA%\Programs\Opera GX\launcher.exe"
if not defined OPERA if exist "%LOCALAPPDATA%\Programs\Opera GX\opera.exe" set "OPERA=%LOCALAPPDATA%\Programs\Opera GX\opera.exe"
if not defined OPERA if exist "%PROGRAMFILES%\Opera GX\launcher.exe" set "OPERA=%PROGRAMFILES%\Opera GX\launcher.exe"
if not defined OPERA if exist "%PROGRAMFILES(X86)%\Opera GX\launcher.exe" set "OPERA=%PROGRAMFILES(X86)%\Opera GX\launcher.exe"

if not defined OPERA (
    echo Could not find Opera GX. Edit launch_opera.bat and set OPERA to the right path.
    echo Typical install path: %%LOCALAPPDATA%%\Programs\Opera GX\launcher.exe
    pause
    exit /b 1
)

tasklist /FI "IMAGENAME eq opera.exe" 2>nul | find /I "opera.exe" >nul
if not errorlevel 1 (
    echo.
    echo Opera GX is already running. Close ALL Opera GX windows first, then run this again.
    echo Opera only enables the debugging port at startup.
    pause
    exit /b 1
)

echo Launching Opera GX with remote debugging on port 9222...
start "" "%OPERA%" --remote-debugging-port=9222
endlocal
