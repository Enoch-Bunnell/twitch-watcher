@echo off
REM Copyright 2026 Enoch Bunnell, AlyxiC
REM SPDX-License-Identifier: Apache-2.0
REM See LICENSE in the project root for the full Apache License 2.0 text.

REM Wrapper that runs enable_opera_debug.ps1 with the right PowerShell flags
REM so you don't have to fiddle with Windows execution policy. Double-click
REM this once. Re-run if Opera ever updates and resets its shortcuts.

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable_opera_debug.ps1"
pause
