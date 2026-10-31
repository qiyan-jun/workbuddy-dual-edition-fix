# -*- coding: utf-8 -*-
r"""
Watch a WorkBuddy edition's update flow in real time (run it, THEN click
"Check for updates" in the app). Prints a timeline of everything that matters:

  * "Update blocked by install dir guard" occurrences (the popup cause)
  * update state machine transitions (checking -> downloading -> ready -> ...)
  * EPERM / ACL errors (staging dir deny)
  * installer download progress in the staging dirs
  * the install dir gaining non-whitelisted subdirs (regression check)
  * edition process count changes (installer taking over)

Usage:
  python watch_update.py --data-dir "C:\Users\<user>\.workbuddy" [--seconds 180]
                         [--install-dir "D:\WorkBuddy"] [--process WorkBuddy.exe]

Ctrl-C stops early and prints the summary anyway.
"""
import argparse
import os
import re
import subprocess
import sys
import time

WHITELIST = {"bin", "locales", "resources", "tools", "log", "logs",
             "_", "share-target", "assets"}
STATE_RE = re.compile(r"State changed: (\w+)")
GUARD_RE = re.compile(r"Update blocked by install dir guard")
EPERM_RE = re.compile(r"EPERM|operation not permitted|EACCES")


def is_known(name):
    t = name.lower()
    return t in WHITELIST or t.startswith("$") or t.startswith("nsis")


def install_dir_dirs(install_dir):
    if not install_dir or not os.path.isdir(install_dir):
        return []
    return [e for e in sorted(os.listdir(install_dir))
            if os.path.isdir(os.path.join(install_dir, e))]


def proc_count(name):
    out = subprocess.run(["tasklist"], capture_output=True).stdout.decode("utf-8", "ignore")
    return sum(1 for l in out.splitlines() if l.strip().lower().startswith(name.lower()))


def staging_sizes():
    local = os.environ.get("LOCALAPPDATA", "")
    temp = os.environ.get("TEMP", "")
    sizes = {}
    for p in (os.path.normpath(os.path.join(local, "@genieworkbuddy-desktop-updater")),
              os.path.normpath(os.path.join(temp, "workbuddy-update-x64"))):
        total = 0
        files = []
        if os.path.isdir(p):
            for dirpath, _, filenames in os.walk(p):
                for fn in filenames:
                    fp = os.path.join(dirpath, fn)
                    try:
                        sz = os.path.getsize(fp)
                    except OSError:
                        continue
                    total += sz
                    files.append((fn, sz))
        sizes[p] = (total, files)
    return sizes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, help="edition data dir, e.g. ~/.workbuddy or ~/.workbuddy-ai")
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--install-dir", default=None, help="install dir to watch for regressions")
    ap.add_argument("--process", default=None, help="process name to count, e.g. WorkBuddy.exe")
    args = ap.parse_args()

    logdir = os.path.join(args.data_dir, "logs", "update")
    if not os.path.isdir(logdir):
        print(f"!! no update log dir: {logdir}")
        return 1
    # pick today's log (or the newest)
    today = time.strftime("%Y%m%d")
    logf = os.path.join(logdir, f"update-{today}.log")
    if not os.path.isfile(logf):
        logs = sorted((os.path.join(logdir, f) for f in os.listdir(logdir)
                       if f.startswith("update-") and f.endswith(".log")),
                      key=os.path.getmtime)
        if not logs:
            print("!! no update logs found")
            return 1
        logf = logs[-1]
    print(f"watching {logf} for {args.seconds}s ...")
    print(">>> NOW click 'Check for updates' in the app <<<\n")

    pos = os.path.getsize(logf) if os.path.isfile(logf) else 0
    guard_hits = 0
    eperm_hits = 0
    states = []
    seen_sizes = {}
    baseline_dirs = set(install_dir_dirs(args.install_dir)) if args.install_dir else set()
    baseline_procs = proc_count(args.process) if args.process else None
    t0 = time.time()

    try:
        while time.time() - t0 < args.seconds:
            # update log
            try:
                with open(logf, "rb") as f:
                    f.seek(pos)
                    chunk = f.read().decode("utf-8", "ignore")
                    pos = f.tell()
                for line in chunk.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    m = STATE_RE.search(line)
                    if m:
                        states.append(m.group(1))
                        print(f"  [state ] {m.group(1):<12} | {line[:150]}")
                    if GUARD_RE.search(line):
                        guard_hits += 1
                        print(f"  [GUARD!] install-dir guard BLOCKED | {line[:150]}")
                    if EPERM_RE.search(line):
                        eperm_hits += 1
                        print(f"  [EPERM!] staging dir write denied | {line[:150]}")
                    elif not m and ("version=" in line or "download" in line.lower()
                                    or "install" in line.lower()):
                        print(f"  [info  ] {line[:150]}")
            except OSError:
                pass
            # staging sizes
            for p, (total, files) in staging_sizes().items():
                prev = seen_sizes.get(p)
                if prev is not None and total != prev:
                    for fn, sz in files:
                        if sz > 1024 * 1024:
                            print(f"  [stage ] {fn} {sz/1048576:.0f}MB ({os.path.basename(p)})")
                seen_sizes[p] = total
            # install dir regression
            if args.install_dir:
                now = set(install_dir_dirs(args.install_dir))
                for new in sorted(now - baseline_dirs):
                    if not is_known(new):
                        print(f"  [REGRESS] install dir gained non-whitelisted dir: {new}/")
                baseline_dirs = now
            # process count
            if args.process:
                n = proc_count(args.process)
                if n != baseline_procs:
                    print(f"  [proc  ] {args.process}: {baseline_procs} -> {n}")
                    baseline_procs = n
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n(stopped early)")

    print("\n" + "=" * 60)
    print(f"guard popups : {guard_hits}  {'(!! popup cause)' if guard_hits else '(none - guard passed)'}")
    print(f"EPERM errors : {eperm_hits}  {'(!! staging ACL)' if eperm_hits else '(none)'}")
    print(f"states       : {' -> '.join(states) if states else '(none)'}")
    if states:
        last = states[-1]
        if last == "ready":
            print("RESULT: installer downloaded & verified - click 'Install and restart' in the app.")
        elif last == "error":
            print("RESULT: ended in error - see lines above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
