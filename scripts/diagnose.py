# -*- coding: utf-8 -*-
r"""
WorkBuddy dual-edition health check (READ-ONLY, changes nothing).

Checks, in order:
  1. Locate both editions: install dirs (via uninstall registry keys), data dirs,
     running processes.
  2. Replicate the official install-dir guard against the DOMESTIC install dir.
  3. Is the international edition's defaultWorkspacePath inside a domestic
     install dir? (the root cause of guard trips)
  4. Update staging dirs: deny ACL present? installers left on disk?
  5. startupForceAutoUpdate status in both editions.

Usage:
  python diagnose.py [--domestic-install D:\WorkBuddy] [--international-install D:\Programs\WorkBuddy]
                     [--domestic-data ~/.workbuddy] [--international-data ~/.workbuddy-ai]

Exit code 0 = all checks pass, 1 = at least one FAIL.
"""
import argparse
import json
import os
import re
import subprocess
import sys

WHITELIST = {"bin", "locales", "resources", "tools", "log", "logs",
             "_", "share-target", "assets"}

results = []  # (status, item, detail)


def check(status, item, detail=""):
    results.append((status, item, detail))
    icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]", "INFO": "[INFO]"}[status]
    print(f"{icon} {item}" + (f"\n       {detail}" if detail else ""))


def is_known_app_directory(name):
    """Verbatim port of isKnownAppDirectory() from UpdateServiceWin32 (app.asar)."""
    t = name.lower()
    return t in WHITELIST or t.startswith("$") or t.startswith("nsis")


def guard_scan(install_dir):
    """Verbatim port of hasUserContentInInstallDir(): first-level dirs only, names only."""
    if not install_dir or not os.path.isdir(install_dir):
        return None, []
    blocked = []
    for e in sorted(os.listdir(install_dir)):
        if os.path.isdir(os.path.join(install_dir, e)) and not is_known_app_directory(e):
            blocked.append(e)
    return install_dir, blocked


def read_json(path):
    try:
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except Exception:
        return None


def find_install_dirs():
    """Find install locations from uninstall registry keys via PowerShell."""
    ps = r"""
$keys = Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
                        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
                        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall' -ErrorAction SilentlyContinue |
        Where-Object { $_.GetValue('DisplayName') -like '*WorkBuddy*' }
foreach ($k in $keys) {
  $n = $k.GetValue('DisplayName')
  $l = $k.GetValue('InstallLocation')
  $i = $k.GetValue('DisplayIcon')
  if (-not $l -and $i) { $l = Split-Path $i -Parent }
  "$n | $l"
}"""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, timeout=60)
        lines = [l.strip() for l in out.stdout.decode("utf-8", "ignore").splitlines() if "|" in l]
    except Exception:
        lines = []
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domestic-install", default=r"D:\WorkBuddy")
    ap.add_argument("--international-install", default=r"D:\Programs\WorkBuddy")
    ap.add_argument("--domestic-data", default=os.path.expanduser(r"~\.workbuddy"))
    ap.add_argument("--international-data", default=os.path.expanduser(r"~\.workbuddy-ai"))
    args = ap.parse_args()

    print("=" * 72)
    print("WorkBuddy dual-edition health check (read-only)")
    print("=" * 72)

    # ---- 1. locate editions ----
    print("\n--- 1. editions ---")
    for line in find_install_dirs():
        check("INFO", "registry", line)
    tl = subprocess.run(["tasklist"], capture_output=True).stdout
    dom_running = b"WorkBuddy.exe" in tl
    intl_running = b"WorkBuddyAI.exe" in tl
    check("INFO", "processes",
          f"domestic(WorkBuddy.exe) running={dom_running}, international(WorkBuddyAI.exe) running={intl_running}")
    check("INFO", "install dirs",
          f"domestic={args.domestic_install} (exists={os.path.isdir(args.domestic_install)}), "
          f"international={args.international_install} (exists={os.path.isdir(args.international_install)})")

    # ---- 2. install-dir guard on domestic ----
    print("\n--- 2. install-dir guard (domestic) ---")
    d, blocked = guard_scan(args.domestic_install)
    if d is None:
        check("FAIL", "domestic install dir", f"{args.domestic_install} not found")
    elif blocked:
        check("FAIL", "domestic install dir has non-whitelisted subdirs",
              f"{args.domestic_install}: {blocked} -> update WILL be blocked")
    else:
        check("PASS", "domestic install dir clean",
              f"only whitelisted subdirs in {args.domestic_install}")

    # also scan international install dir for completeness
    di, blocked_i = guard_scan(args.international_install)
    if di and blocked_i:
        check("WARN", "international install dir has non-whitelisted subdirs",
              f"{args.international_install}: {blocked_i}")

    # ---- 3. international workspace root ----
    print("\n--- 3. international defaultWorkspacePath ---")
    cfg = read_json(os.path.join(args.international_data, "app", "app-config.json"))
    if cfg is None:
        check("WARN", "international app-config.json", "missing or unreadable (using system default ~/WorkBuddy)")
        ws_root = os.path.expanduser(r"~\WorkBuddy")
    else:
        ws_root = cfg.get("defaultWorkspacePath") or os.path.expanduser(r"~\WorkBuddy")
    check("INFO", "international workspace root", ws_root)
    for label, inst in (("domestic", args.domestic_install), ("international", args.international_install)):
        if inst and os.path.normcase(ws_root).startswith(os.path.normcase(inst) + os.sep):
            check("FAIL", f"workspace root is inside the {label} install dir",
                  f"{ws_root} -> the international edition will recreate Claw/session dirs "
                  f"there on every launch, tripping the domestic update guard. "
                  f"Fix: scripts/fix_workspace_root.py")
    else:
        check("PASS", "workspace root is outside both install dirs")

    # ---- 4. staging dirs ----
    print("\n--- 4. update staging dirs ---")
    local = os.environ.get("LOCALAPPDATA", "")
    temp = os.environ.get("TEMP", "")
    staging = [os.path.normpath(os.path.join(local, "@genieworkbuddy-desktop-updater")),
               os.path.normpath(os.path.join(temp, "workbuddy-update-x64"))]
    ps_acl = "; ".join(f'if (Test-Path -LiteralPath "{p}") {{ '
                       f'$d = (icacls "{p}") -match "DENY"; '
                       f'"$([bool]$d)|{p}|" + ((icacls "{p}") -match "\\(DENY\\)" | Out-String).Trim() }}'
                       for p in staging)
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_acl],
                             capture_output=True, timeout=60)
        acl_lines = [l for l in out.stdout.decode("utf-8", "ignore").splitlines() if "|" in l]
    except Exception:
        acl_lines = []
    for line in acl_lines:
        parts = line.split("|", 2)
        denied = parts[0].strip() == "True"
        path = parts[1] if len(parts) > 1 else "?"
        detail = parts[2].replace("\n", " / ").strip() if len(parts) > 2 else ""
        if denied:
            check("FAIL", f"staging dir has deny ACL: {path}",
                  f"{detail} -> downloads will fail with EPERM. Fix: scripts/fix_staging_acl.ps1")
        else:
            check("PASS", f"staging dir writable: {path}")
        # leftover installers?
        try:
            leftovers = [f for f in os.listdir(path) if f.lower().endswith((".exe", ".tmp"))]
            if leftovers:
                check("WARN", f"leftover installers in {path}", str(leftovers[:5]))
        except Exception:
            pass

    # ---- 5. startupForceAutoUpdate ----
    print("\n--- 5. startupForceAutoUpdate ---")
    for label, data, inst in (("domestic", args.domestic_data, args.domestic_install),
                              ("international", args.international_data, args.international_install)):
        vals = {}
        pj = os.path.join(inst, "resources", "app.asar.unpacked", "cli", "product.json")
        c = read_json(pj)
        if c is not None:
            vals["product.json"] = c.get("startupForceAutoUpdate")
        c = read_json(os.path.join(data, "cache", "acc-product-config-v3.json"))
        if c is not None:
            vals["acc-product-config-v3.json"] = c.get("startupForceAutoUpdate")
        if not vals:
            check("INFO", f"{label}: no force-auto-update config found", "(nothing to disable)")
        else:
            for k, v in vals.items():
                if v is True:
                    check("WARN", f"{label}: startupForceAutoUpdate=true in {k}",
                          "silent forced install on every launch - set false if you want manual updates")
                else:
                    check("PASS", f"{label}: startupForceAutoUpdate={v} in {k}")

    # ---- summary ----
    fails = sum(1 for s, _, _ in results if s == "FAIL")
    warns = sum(1 for s, _, _ in results if s == "WARN")
    print("\n" + "=" * 72)
    print(f"SUMMARY: {len(results)} checks, {fails} FAIL, {warns} WARN")
    if fails:
        print("Fix order: root cause A (workspace root) -> delete blocker dirs -> "
              "root cause B (staging ACL) -> verify -> update.")
        return 1
    print("All clear - update check should proceed normally.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
