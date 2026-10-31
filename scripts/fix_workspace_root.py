# -*- coding: utf-8 -*-
r"""
WorkBuddy dual-edition fix: move the INTERNATIONAL edition's workspace root out of
the DOMESTIC install directory.

Root cause this fixes: the international edition's `defaultWorkspacePath`
(~\.workbuddy-ai\app\app-config.json) points at the domestic install dir, so every
launch recreates `Claw/` + timestamped session dirs there, tripping the domestic
edition's install-dir update guard ("Update blocked by install dir guard").

What it does (every step backs up first, script is idempotent):
  1. app-config.json                  defaultWorkspacePath rewrite
  2. workbuddy.db                     path rewrite in EVERY table / text column
                                     (sessions.cwd, workspaces.path, anything else)
  3. sidebar-list-snapshot.json       rewrite (auto-discovered per user id)
  4. skills-installed-store.json      rewrite (auto-discovered per user id)
  5. other small json/config files    rewrite (auto-discovered; skips logs/cache/blobs)
  6. projects/<encoded>/ dirs         rename to match the new root (history preserved)
  7. verify                           every session cwd maps to an existing projects dir

Usage:
  python fix_workspace_root.py --ai-dir "C:\Users\<user>\.workbuddy-ai" ^
      --old-root "D:\WorkBuddy" --new-root "D:\WorkBuddyProjects" [--backup-dir DIR]
      [--rewrite-history]

Notes:
  * Quit ALL international-edition processes first (tasklist | findstr WorkBuddyAI),
    otherwise workbuddy.db is locked.
  * Path matching requires a trailing separator or end-of-string, so rewriting
    D:\WorkBuddy -> D:\WorkBuddyProjects never double-appends to already-fixed values.
  * Conversation history (.jsonl) is NOT rewritten by default: those files are
    content records, keyed by directory name; pass --rewrite-history to also fix
    path strings inside them (cosmetic only).
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

SKIP_DIRS = {"blobs", "cache", "CodeCache", "Crashpad", "clipboard-images",
             "file-history", "artifact-index", "changes-detail", "changes-index",
             "audit-log", "appearance-resources", "binaries", "playbook-covers",
             "session", "cli-env", "file-tree-manifests", "editor-sdk-sandbox-ws",
             "logs", "traces", "GPUCache", "DawnGraphCache", "DawnWebGPUCache"}
MAX_FILE = 3 * 1024 * 1024

report = []


def log(s):
    print(s)
    report.append(s)


def norm_seps(p):
    return p.replace("\\", "/")


def old_forms(old_fwd, old_back):
    """All textual forms the old root can appear in: fwd-slash, backslash,
    JSON-escaped (double backslash)."""
    return (old_fwd, old_back, old_back.replace("\\", "\\\\"))


def has_old_ref(value, old_fwd, old_back):
    """True if value references old root with a trailing separator or as the whole value."""
    for old in old_forms(old_fwd, old_back):
        for m in re.finditer(re.escape(old), value):
            end = m.end()
            if end == len(value) or value[end] in "/\\":
                return True
    return False


def rewrite_value(value, old_fwd, old_back, new_fwd):
    """Replace old-root references (trailing sep or whole value) with new root,
    keeping the original separator style of each occurrence. Never double-appends
    to already-fixed values (a match must end at a separator or end-of-string)."""
    new_back = new_fwd.replace("/", "\\")
    pairs = [(o, n) for o, n in zip(old_forms(old_fwd, old_back),
                                    (new_fwd, new_back, new_back.replace("\\", "\\\\")))]
    out = []
    i = 0
    changed = False
    while i < len(value):
        hit = None
        for old, new in pairs:
            if value.startswith(old, i):
                end = i + len(old)
                if end == len(value) or value[end] in "/\\":
                    hit = (old, new)
                    break
        if hit:
            out.append(hit[1])
            i += len(hit[0])
            changed = True
        else:
            out.append(value[i])
            i += 1
    return "".join(out), changed


def encode_workspace_path(path):
    """Port of compressWorkspacePathName(): replace [/\\:] with '-', fold runs,
    strip edges, lowercase first char."""
    e = re.sub(r"-+", "-", re.sub(r"^-+|-+$", "", re.sub(r"[/\\:]", "-", path)))
    return e[0].lower() + e[1:] if e else e


def read_json(path):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai-dir", required=True, help="international edition data dir (e.g. ~/.workbuddy-ai)")
    ap.add_argument("--old-root", required=True, help="current (wrong) workspace root")
    ap.add_argument("--new-root", required=True, help="target workspace root (must NOT be inside any install dir)")
    ap.add_argument("--backup-dir", default=None)
    ap.add_argument("--rewrite-history", action="store_true",
                    help="also rewrite path strings inside .jsonl conversation history")
    args = ap.parse_args()

    ai_dir = os.path.abspath(args.ai_dir)
    old_fwd = norm_seps(args.old_root).rstrip("/")
    old_back = args.old_root.replace("/", "\\").rstrip("\\")
    new_fwd = norm_seps(args.new_root).rstrip("/")
    backup = args.backup_dir or (new_fwd.replace("/", "\\") + "-fix-backup-" + time.strftime("%Y%m%d"))

    log("=== PRE-FLIGHT ===")
    # international edition must not be running
    out = subprocess.run(["tasklist"], capture_output=True).stdout
    if b"WorkBuddyAI.exe" in out:
        log("!! ABORT: international edition is running - quit it first")
        return 1
    log("international edition not running: OK")

    # new root must not live inside a typical install dir
    for inst in (r"D:\WorkBuddy", r"D:\Programs\WorkBuddy",
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "WorkBuddy")):
        if inst and os.path.normcase(new_fwd).startswith(os.path.normcase(inst) + os.sep):
            log(f"!! ABORT: new root {new_fwd} is inside install dir {inst}")
            return 1
    log(f"new root outside install dirs: OK ({new_fwd})")

    os.makedirs(backup, exist_ok=True)
    log(f"backup dir: {backup}")

    def backup_file(p):
        if os.path.isfile(p):
            dst = os.path.join(backup, os.path.basename(p) + ".bak")
            shutil.copy2(p, dst)
            log(f"  backup {p} -> {dst}")

    # ---------- 1. app-config.json ----------
    log("\n=== 1. app-config.json ===")
    cfg_path = os.path.join(ai_dir, "app", "app-config.json")
    if not os.path.isfile(cfg_path):
        log("  missing (using system default workspace root) - nothing to do")
    else:
        raw = open(cfg_path, "rb").read().decode("utf-8")
        if has_old_ref(raw, old_fwd, old_back):
            backup_file(cfg_path)
            new_raw, _ = rewrite_value(raw, old_fwd, old_back, new_fwd)
            open(cfg_path, "w", encoding="utf-8").write(new_raw)
            log(f"  rewritten: {new_raw.strip()}")
        else:
            log("  no old-root reference - skipping")
        cfg = read_json(cfg_path)
        log(f"  now defaultWorkspacePath = {cfg.get('defaultWorkspacePath')!r}")

    # ---------- 2. workbuddy.db ----------
    log("\n=== 2. workbuddy.db ===")
    db = os.path.join(ai_dir, "workbuddy.db")
    if not os.path.isfile(db):
        log("  missing - skipping")
    else:
        backup_file(db)
        con = sqlite3.connect(db)
        con.execute("PRAGMA foreign_keys=OFF")
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        total_rows = 0
        for t in tables:
            try:
                cur.execute(f'PRAGMA table_info("{t}")')
                cols = [r[1] for r in cur.fetchall()]
                text_cols = []
                for c in cols:
                    cur.execute(f'SELECT typeof("{c}") FROM "{t}" LIMIT 1')
                    # typeof on empty table returns nothing; probe a couple of rows instead
                    cur.execute(f'SELECT "{c}" FROM "{t}" LIMIT 5')
                    kinds = {type(r[0]).__name__ for r in cur.fetchall()}
                    if kinds <= {"str", "NoneType"}:
                        text_cols.append(c)
                if not text_cols:
                    continue
                # find rows containing old refs (any textual form)
                forms = old_forms(old_fwd, old_back)
                conds = " OR ".join(f'instr("{c}", ?) > 0' for c in text_cols for _ in forms)
                params = []
                for c in text_cols:
                    params += list(forms)
                cur.execute(f'SELECT rowid, * FROM "{t}" WHERE {conds}', params)
                col_idx = {c: i + 1 for i, c in enumerate(cols)}
                pending = []
                for row in cur.fetchall():
                    rid = row[0]
                    new_vals = {}
                    for c in text_cols:
                        v = row[col_idx[c]]
                        if isinstance(v, str) and has_old_ref(v, old_fwd, old_back):
                            nv, changed = rewrite_value(v, old_fwd, old_back, new_fwd)
                            if changed:
                                new_vals[c] = nv
                    if new_vals:
                        pending.append((rid, new_vals))
                for rid, new_vals in pending:
                    sets = ", ".join(f'"{c}" = ?' for c in new_vals)
                    cur.execute(f'UPDATE "{t}" SET {sets} WHERE rowid = ?',
                                list(new_vals.values()) + [rid])
                if pending:
                    total_rows += len(pending)
                    log(f"  {t}: rewrote {len(pending)} rows (cols: {', '.join(text_cols)})")
            except Exception as e:
                log(f"  !! {t}: {e}")
        con.commit()
        # verify no remaining old refs
        remaining = 0
        for t in tables:
            try:
                cur.execute(f'SELECT * FROM "{t}"')
                for row in cur.fetchall():
                    for v in row:
                        if isinstance(v, str) and has_old_ref(v, old_fwd, old_back):
                            remaining += 1
            except Exception:
                pass
        con.close()
        log(f"  total rows rewritten: {total_rows}; remaining old refs: {remaining}")

    # ---------- 3/4/5. small config files ----------
    log("\n=== 3-5. config/snapshot/skills files ===")
    hits = []
    for dirpath, dirnames, filenames in os.walk(ai_dir):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".jsonl") and not args.rewrite_history:
                continue
            fp = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(fp) > MAX_FILE:
                    continue
                data = open(fp, "rb").read()
            except Exception:
                continue
            if not (old_fwd.encode() in data or old_back.encode() in data
                    or old_back.replace("\\", "\\\\").encode() in data):
                continue
            try:
                text = data.decode("utf-8")
            except Exception:
                continue
            if not has_old_ref(text, old_fwd, old_back):
                continue
            hits.append(fp)
    for fp in hits:
        backup_file(fp)
        text = open(fp, "rb").read().decode("utf-8")
        new_text, _ = rewrite_value(text, old_fwd, old_back, new_fwd)
        open(fp, "w", encoding="utf-8").write(new_text)
        if fp.endswith(".json"):
            try:
                read_json(fp)
                log(f"  rewritten + json valid: {fp}")
            except Exception as e:
                log(f"  !! rewritten but json INVALID: {fp} ({e}) - restore from backup!")
        else:
            log(f"  rewritten: {fp}")
    if not hits:
        log("  no files with old-root references")

    # ---------- 6. rename projects dirs ----------
    log("\n=== 6. projects dirs rename ===")
    projects = os.path.join(ai_dir, "projects")
    old_prefix = encode_workspace_path(old_back)          # e.g. d-WorkBuddy
    new_prefix = encode_workspace_path(args.new_root.replace("/", "\\"))  # e.g. d-WorkBuddyProjects
    if not os.path.isdir(projects):
        log("  no projects dir - skipping")
    else:
        renamed = skipped = 0
        for d in sorted(os.listdir(projects)):
            if d == old_prefix:
                suffix = ""
            elif d.startswith(old_prefix + "-"):
                suffix = d[len(old_prefix):]
            else:
                continue
            new_name = new_prefix + suffix
            src = os.path.join(projects, d)
            dst = os.path.join(projects, new_name)
            if not os.path.isdir(src):
                continue
            if os.path.exists(dst):
                log(f"  SKIP (target exists): {d} -> {new_name}")
                skipped += 1
                continue
            os.rename(src, dst)
            renamed += 1
            log(f"  {d} -> {new_name}")
        log(f"  renamed {renamed}, skipped {skipped}")

    # ---------- 7. verify ----------
    log("\n=== 7. verify session mapping ===")
    db = os.path.join(ai_dir, "workbuddy.db")
    if os.path.isfile(db) and os.path.isdir(projects):
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = con.cursor()
        try:
            cur.execute("SELECT id, cwd FROM sessions")
            sess = cur.fetchall()
        except Exception:
            sess = []
        con.close()
        ok = 0
        for sid, cwd in sess:
            key = encode_workspace_path(cwd)
            pdir = os.path.join(projects, key)
            exists = os.path.isdir(pdir)
            hist = os.path.isfile(os.path.join(pdir, sid + ".jsonl"))
            log(f"  {'OK  ' if exists else 'MISS'} {cwd} -> {key} (history={hist})")
            ok += 1 if exists else 0
        log(f"  {ok}/{len(sess)} sessions mapped to existing projects dirs")

    log("\n=== DONE ===")
    with open(os.path.join(backup, "fix-report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    log(f"report + backups in {backup}")
    log("NEXT: python verify_guard.py --install-dir <domestic install dir> --clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
