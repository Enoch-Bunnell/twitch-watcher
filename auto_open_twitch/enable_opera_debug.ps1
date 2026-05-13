# Copyright 2026 Enoch Bunnell, AlyxiC
# SPDX-License-Identifier: Apache-2.0
# See LICENSE in the project root for the full Apache License 2.0 text.

# enable_opera_debug.ps1
#
# Adds --remote-debugging-port=9222 to every Opera GX shortcut found in the
# standard shortcut locations, so the browser always starts with the Chrome
# DevTools Protocol port open. The watcher then sees your tabs (and opens
# new ones in the background) without you needing launch_opera.bat first.
#
# Idempotent — safe to re-run. Restart Opera after running for the flag to
# take effect.
#
# To undo a specific shortcut: right-click it -> Properties -> remove
# "--remote-debugging-port=9222" from the Target/Arguments field.

$flag = "--remote-debugging-port=9222"

$searchRoots = @(
    "$env:APPDATA\Microsoft\Windows\Start Menu",
    "$env:PROGRAMDATA\Microsoft\Windows\Start Menu",
    "$env:USERPROFILE\Desktop",
    "$env:PUBLIC\Desktop",
    "$env:APPDATA\Microsoft\Internet Explorer\Quick Launch"
)

$ws = New-Object -ComObject WScript.Shell
$found = @()

foreach ($root in $searchRoots) {
    if (-not (Test-Path $root)) { continue }
    Get-ChildItem -Path $root -Filter *.lnk -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
        $sc = $ws.CreateShortcut($_.FullName)
        $target = $sc.TargetPath
        $looksLikeOperaExe = ($target -like "*\opera.exe") -or ($target -like "*\launcher.exe")
        $pathSaysOpera = ($target -like "*Opera*") -or ($_.FullName -like "*Opera*")
        if ($looksLikeOperaExe -and $pathSaysOpera) {
            $found += [PSCustomObject]@{ Path = $_.FullName; Shortcut = $sc }
        }
    }
}

if ($found.Count -eq 0) {
    Write-Host "No Opera GX shortcuts found in the standard locations."
    Write-Host "You can still use launch_opera.bat manually, or right-click your"
    Write-Host "Opera shortcut -> Properties -> add '$flag' to the Target."
    exit 0
}

$updated = 0
$skipped = 0

foreach ($item in $found) {
    if ($item.Shortcut.Arguments -like "*$flag*") {
        Write-Host "[skip]    already has flag: $($item.Path)"
        $skipped += 1
        continue
    }
    if ([string]::IsNullOrWhiteSpace($item.Shortcut.Arguments)) {
        $item.Shortcut.Arguments = $flag
    }
    else {
        $item.Shortcut.Arguments = "$($item.Shortcut.Arguments) $flag"
    }
    $item.Shortcut.Save()
    Write-Host "[updated] $($item.Path)"
    Write-Host "          Arguments now: $($item.Shortcut.Arguments)"
    $updated += 1
}

Write-Host ""
Write-Host "Summary: $updated updated, $skipped already-flagged."
if ($updated -gt 0) {
    Write-Host ""
    Write-Host "Close ALL Opera windows and relaunch for the flag to take effect."
    Write-Host "(Opera only enables the debug port at a cold startup.)"
}
