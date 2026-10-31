# WorkBuddy dual-edition: unblock the update staging directories.
#
# Root cause this fixes: the ZenHG/workbuddy-dual-edition logon guard
# (block-update-staging.ps1) applies a (DENY)(W,DC) ACL to the two update
# staging dirs so installers cannot land there. A side effect: the NORMAL
# in-app updater (running as the standard user) then fails with
#   EPERM: operation not permitted, open '...\Temp\workbuddy-update-x64\....tmp'
# This script removes the deny ACL and disables the logon guard
# (renamed to .cmd.disabled - the script itself is preserved and can be
# re-enabled by renaming it back).
#
# When to KEEP the guard disabled: normal dual-edition life. The two editions
# are fully isolated (separate install dirs, data dirs, uninstall registry
# keys), so letting each update itself in-place is safe and desirable.
# Re-enable the guard only if you deliberately want to freeze updates.
#
# Run as the interactive user (NOT elevated): user-level deny ACLs are only
# visible/removable in the user's own context.

$ErrorActionPreference = 'SilentlyContinue'
$user  = "$env:USERDOMAIN\$env:USERNAME"
$paths = @(
  "$env:LOCALAPPDATA\@genieworkbuddy-desktop-updater",
  "$env:TEMP\workbuddy-update-x64"
)

Write-Host "=== 1. remove deny ACL from staging dirs (user: $user) ==="
foreach ($p in $paths) {
  if (-not (Test-Path -LiteralPath $p)) {
    Write-Host "  MISSING: $p"
    continue
  }
  $before = icacls $p
  icacls $p /remove:d $user | Out-Null
  $after = icacls $p
  if (($after | Out-String) -match "DENY") {
    Write-Host "  STILL DENIED: $p"
  } else {
    Write-Host "  CLEAN: $p"
  }
}

Write-Host ""
Write-Host "=== 2. drop leftover installers from staging (optional, frees ~450MB each) ==="
foreach ($p in $paths) {
  if (Test-Path -LiteralPath $p) {
    Get-ChildItem -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue |
      Remove-Item -Force -Recurse -ErrorAction SilentlyContinue
    Write-Host "  cleaned: $p"
  }
}

Write-Host ""
Write-Host "=== 3. disable the logon guard (rename, not delete) ==="
$guard = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\WorkBuddy-Staging-Guard.cmd"
if (Test-Path -LiteralPath $guard) {
  Rename-Item -LiteralPath $guard -NewName "WorkBuddy-Staging-Guard.cmd.disabled" -Force
  Write-Host "  disabled: $guard -> .cmd.disabled"
  Write-Host "  (re-enable any time by renaming it back; the guard script itself"
  Write-Host "   lives in D:\Programs\WorkBuddy-dual-edition\block-update-staging.ps1)"
} elseif (Test-Path -LiteralPath "$guard.disabled") {
  Write-Host "  already disabled: $guard.disabled"
} else {
  Write-Host "  no logon guard found in Startup - nothing to disable"
}

Write-Host ""
Write-Host "=== 4. write probe (must succeed now) ==="
foreach ($p in $paths) {
  $probe = Join-Path $p "__wb_probe.tmp"
  try {
    "x" | Set-Content -LiteralPath $probe -ErrorAction Stop
    Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
    Write-Host "  OK writable: $p"
  } catch {
    Write-Host "  FAIL still not writable: $p ($($_.Exception.Message))"
  }
}
