# -*- coding: utf-8 -*-
"""Sandbox test for fix_workspace_root.py core logic (no real data touched)."""
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "fwr", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "fix_workspace_root.py"))
fwr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fwr)

fails = []


def eq(got, want, label):
    status = "OK " if got == want else "FAIL"
    if got != want:
        fails.append(label)
    print(f"  [{status}] {label}: got={got!r} want={want!r}")


print("== encode_workspace_path ==")
eq(fwr.encode_workspace_path(r"D:\WorkBuddyProjects\2026-10-20-11-06-16"),
   "d-WorkBuddyProjects-2026-10-20-11-06-16", "ts session")
eq(fwr.encode_workspace_path("D:/WorkBuddy/Claw"), "d-WorkBuddy-Claw", "claw fwd slashes")
eq(fwr.encode_workspace_path(r"D:\WorkBuddy"), "d-WorkBuddy", "root itself")
eq(fwr.encode_workspace_path(r"C:\Users\七颜\WorkBuddy\2026-10-30-09-00-32"),
   "c-Users-七颜-WorkBuddy-2026-10-30-09-00-32", "cjk chars")

print("== has_old_ref / rewrite_value (no double-append) ==")
OLD_F, OLD_B, NEW_F = "D:/WorkBuddy", "D:\\WorkBuddy", "D:/WorkBuddyProjects"
eq(fwr.has_old_ref("D:\\WorkBuddy\\Claw", OLD_F, OLD_B), True, "detect old")
eq(fwr.has_old_ref("D:\\WorkBuddyProjects\\Claw", OLD_F, OLD_B), False, "no false positive on new")
eq(fwr.has_old_ref("D:\\WorkBuddy", OLD_F, OLD_B), True, "exact root")
eq(fwr.has_old_ref("D:\\WorkBuddyX\\y", OLD_F, OLD_B), False, "prefix must be followed by sep/eos")
eq(fwr.rewrite_value('{"p": "D:\\\\WorkBuddy\\\\Claw"}', OLD_F, OLD_B, NEW_F)[0],
   '{"p": "D:\\\\WorkBuddyProjects\\\\Claw"}', "json-escaped rewrite")
eq(fwr.has_old_ref('{"p": "D:\\\\WorkBuddy\\\\Claw"}', OLD_F, OLD_B), True, "detect json-escaped")
eq(fwr.has_old_ref('{"p": "D:\\\\WorkBuddyProjects\\\\Claw"}', OLD_F, OLD_B), False, "no false positive on json-escaped new")
eq(fwr.rewrite_value("D:/WorkBuddy/2026-10-20-11-06-16", OLD_F, OLD_B, NEW_F)[0],
   "D:/WorkBuddyProjects/2026-10-20-11-06-16", "fwd slash keeps style")
v, changed = fwr.rewrite_value("D:/WorkBuddyProjects/x", OLD_F, OLD_B, NEW_F)
eq((v, changed), ("D:/WorkBuddyProjects/x", False), "already-fixed untouched")
v, changed = fwr.rewrite_value("root=D:\\WorkBuddy", OLD_F, OLD_B, NEW_F)
eq((v, changed), ("root=D:\\WorkBuddyProjects", True), "exact root rewrite")

print("== sandbox db rewrite ==")
tmp = tempfile.mkdtemp(prefix="wb-test-")
try:
    db = os.path.join(tmp, "workbuddy.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, cwd TEXT, title TEXT)")
    con.execute("CREATE TABLE workspaces (path TEXT PRIMARY KEY, name TEXT)")
    con.execute("CREATE TABLE misc (k TEXT, v TEXT)")  # extra table with paths inside
    con.execute("INSERT INTO sessions VALUES ('s1','D:\\WorkBuddy\\2026-10-20-11-06-16','t1')")
    con.execute("INSERT INTO sessions VALUES ('s2','D:/WorkBuddy/Claw','t2')")
    con.execute("INSERT INTO sessions VALUES ('s3','D:\\WorkBuddyProjects\\keep','t3')")  # already fixed
    con.execute("INSERT INTO sessions VALUES ('s4','C:\\Users\\x\\WorkBuddy','t4')")      # unrelated
    con.execute("INSERT INTO sessions VALUES ('s5','{\"cwd\": \"D:\\\\WorkBuddy\\\\2026\"}','t5')")  # json-escaped
    con.execute("INSERT INTO workspaces VALUES ('D:\\WorkBuddy','root')")
    con.execute("INSERT INTO misc VALUES ('note','see D:\\WorkBuddy\\Claw')")
    con.commit()
    con.close()

    # replicate step 2 logic
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    for t in tables:
        cur.execute(f'PRAGMA table_info("{t}")')
        cols = [r[1] for r in cur.fetchall()]
        text_cols = []
        for c in cols:
            cur.execute(f'SELECT "{c}" FROM "{t}" LIMIT 5')
            if {type(r[0]).__name__ for r in cur.fetchall()} <= {"str", "NoneType"}:
                text_cols.append(c)
        if not text_cols:
            continue
        conds = " OR ".join(f'instr("{c}", ?) > 0' for c in text_cols for _ in (OLD_F, OLD_B, OLD_B.replace("\\", "\\\\")))
        params = []
        for c in text_cols:
            params += [OLD_F, OLD_B, OLD_B.replace("\\", "\\\\")]
        cur.execute(f'SELECT rowid, * FROM "{t}" WHERE {conds}', params)
        col_idx = {c: i + 1 for i, c in enumerate(cols)}
        pending = []
        for row in cur.fetchall():
            rid = row[0]
            nv = {}
            for c in text_cols:
                v = row[col_idx[c]]
                if isinstance(v, str) and fwr.has_old_ref(v, OLD_F, OLD_B):
                    n, ch = fwr.rewrite_value(v, OLD_F, OLD_B, NEW_F)
                    if ch:
                        nv[c] = n
            if nv:
                pending.append((rid, nv))
        for rid, nv in pending:
            sets = ", ".join(f'"{c}" = ?' for c in nv)
            cur.execute(f'UPDATE "{t}" SET {sets} WHERE rowid = ?', list(nv.values()) + [rid])
    con.commit()
    con.close()

    con = sqlite3.connect(db)
    rows = dict(con.execute("SELECT id, cwd FROM sessions").fetchall())
    eq(rows["s1"], "D:\\WorkBuddyProjects\\2026-10-20-11-06-16", "session s1 rewritten")
    eq(rows["s2"], "D:/WorkBuddyProjects/Claw", "session s2 rewritten")
    eq(rows["s3"], "D:\\WorkBuddyProjects\\keep", "session s3 untouched")
    eq(rows["s4"], "C:\\Users\\x\\WorkBuddy", "session s4 untouched")
    eq(rows["s5"], '{"cwd": "D:\\\\WorkBuddyProjects\\\\2026"}', "session s5 json-escaped rewritten")
    eq(con.execute("SELECT path FROM workspaces").fetchone()[0], "D:\\WorkBuddyProjects", "workspace root rewritten")
    eq(con.execute("SELECT v FROM misc").fetchone()[0], "see D:\\WorkBuddyProjects\\Claw", "misc table rewritten")
    con.close()

    print("== sandbox projects rename ==")
    projects = os.path.join(tmp, "projects")
    os.makedirs(os.path.join(projects, "d-WorkBuddy-2026-10-20-11-06-16"))
    os.makedirs(os.path.join(projects, "d-WorkBuddy-Claw"))
    os.makedirs(os.path.join(projects, "d-WorkBuddy"))
    os.makedirs(os.path.join(projects, "c-Users-x-WorkBuddy"))  # unrelated, must not rename
    old_prefix = fwr.encode_workspace_path(OLD_B)
    new_prefix = fwr.encode_workspace_path("D:\\WorkBuddyProjects")
    renamed = []
    for d in sorted(os.listdir(projects)):
        if d == old_prefix:
            suffix = ""
        elif d.startswith(old_prefix + "-"):
            suffix = d[len(old_prefix):]
        else:
            continue
        os.rename(os.path.join(projects, d), os.path.join(projects, new_prefix + suffix))
        renamed.append(d + " -> " + new_prefix + suffix)
    print("  " + "\n  ".join(renamed))
    after = sorted(os.listdir(projects))
    eq(after, ["c-Users-x-WorkBuddy", "d-WorkBuddyProjects",
               "d-WorkBuddyProjects-2026-10-20-11-06-16", "d-WorkBuddyProjects-Claw"],
       "projects dirs renamed correctly")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print(f"{len(fails)} FAILURES: {fails}")
    sys.exit(1)
print("ALL SANDBOX TESTS PASSED")
