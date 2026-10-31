# -*- coding: utf-8 -*-
r"""
Replicate the official install-dir guard (hasUserContentInInstallDir from
UpdateServiceWin32 in app.asar) against any install directory, and optionally
remove EMPTY blocker dirs.

Guard rule (verbatim logic):
  first-level entries of the install dir that are directories AND whose
  lowercased name is NOT in {bin, locales, resources, tools, log, logs, _,
  share-target, assets} AND does not start with '$' or 'nsis'  ->  update blocked.
  Empty dirs count. Names only, no recursion, no content inspection.

Usage:
  python verify_guard.py --install-dir "D:\WorkBuddy" [--clean] [--yes]
      --clean   delete blocker dirs (refuses non-empty dirs, exits 1)
      --yes     skip the confirmation prompt

Exit code 0 = guard passes (update check will proceed), 1 = still blocked.
"""
import argparse
import os
import sys

WHITELIST = {"bin", "locales", "resources", "tools", "log", "logs",
             "_", "share-target", "assets"}


def is_known_app_directory(name):
    t = name.lower()
    return t in WHITELIST or t.startswith("$") or t.startswith("nsis")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--install-dir", required=True)
    ap.add_argument("--clean", action="store_true", help="delete EMPTY blocker dirs")
    ap.add_argument("--yes", action="store_true", help="skip confirmation")
    args = ap.parse_args()

    install_dir = args.install_dir
    if not os.path.isdir(install_dir):
        print(f"!! not a directory: {install_dir}")
        return 1

    print(f"=== SCAN {install_dir} (first-level entries) ===")
    blocked = []
    for e in sorted(os.listdir(install_dir)):
        full = os.path.join(install_dir, e)
        if os.path.isdir(full):
            if is_known_app_directory(e):
                print(f"  [PASS ] {e}/  (whitelisted dir)")
            else:
                print(f"  [BLOCK] {e}/  (non-whitelisted dir)")
                blocked.append(e)
        else:
            print(f"  [file ] {e}")

    if blocked and args.clean:
        print(f"\n=== CLEAN ===")
        if not args.yes:
            ans = input(f"delete EMPTY blocker dirs {blocked} in {install_dir}? [y/N] ")
            if ans.strip().lower() != "y":
                print("aborted")
                return 1
        for d in blocked:
            p = os.path.join(install_dir, d)
            try:
                entries = os.listdir(p)
            except Exception as e:
                print(f"  !! {p}: {e}")
                return 1
            if entries:
                print(f"  !! {p} NOT EMPTY ({entries[:5]}{'...' if len(entries) > 5 else ''}) - refusing")
                print("     MIGRATE the content first (fix_workspace_root.py moves the workspace root),")
                print("     quit all app processes, then re-run.")
                return 1
            os.rmdir(p)  # empty dirs only - safe by construction
            print(f"  removed empty dir: {p}")

    print()
    if blocked:
        print(f"GUARD RESULT: STILL BLOCKED by {blocked}")
        print("-> these dirs will trip 'Update blocked by install dir guard'.")
        print("-> if a dir keeps coming back after deletion, its creator's workspace root")
        print("   still points inside the install dir: run fix_workspace_root.py.")
        return 1
    print("GUARD RESULT: PASS - no user-content dirs in install dir")
    print("-> 'Check for updates' in the app will proceed past the guard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
