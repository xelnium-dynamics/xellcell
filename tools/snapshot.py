#!/usr/bin/env python3
"""
snapshot.py — copy-only, append-only snapshot of a folder, with a SHA-256 manifest.

Never overwrites, never deletes, never follows symlinks. Python 3.9+ stdlib only.

Copy:
    python3 -I snapshot.py copy --src "<vault>" --dest "<brain>/raw/obsidian-vault" \
        --manifest "<brain>/raw/manifests/obsidian-vault-YYYY-MM-DD.json"
Verify (re-hash the copy against a manifest; add --src to compare the source too):
    python3 -I snapshot.py verify --manifest <manifest.json> [--src "<vault>"]

Rules:
  - a destination file that already exists with the SAME hash is skipped (re-runs are safe)
  - a destination file that exists with a DIFFERENT hash is a conflict: it is not touched,
    it is listed, and the exit code is 2
  - the manifest is created exclusively (an existing manifest is never replaced)
  - skipped by default: .obsidian/ .trash/ .git/ __pycache__/ .DS_Store ; symlinks are listed, not copied
Exit codes: 0 ok · 1 usage/IO error · 2 conflicts or verify mismatches
"""
import argparse, hashlib, json, os, sys, time

SKIP_DIRS = {".obsidian", ".trash", ".git", "__pycache__"}
SKIP_FILES = {".DS_Store"}
CHUNK = 1 << 20


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def walk(src, extra_skip):
    skip = SKIP_DIRS | set(extra_skip)
    for root, dirs, files in os.walk(src, followlinks=False):
        links = [d for d in dirs if os.path.islink(os.path.join(root, d))]
        dirs[:] = sorted(d for d in dirs if d not in skip and d not in links)
        for d in links:
            yield os.path.join(root, d), "symlink"
        for f in sorted(files):
            if f in SKIP_FILES:
                continue
            p = os.path.join(root, f)
            yield p, ("symlink" if os.path.islink(p) else "file")


def copy_exclusive(src_path, dst_path):
    """Copy bytes into a file that must not exist yet ('xb' = exclusive create)."""
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    h = hashlib.sha256()
    with open(src_path, "rb") as fi, open(dst_path, "xb") as fo:
        while True:
            b = fi.read(CHUNK)
            if not b:
                break
            h.update(b)
            fo.write(b)
    st = os.stat(src_path)
    os.utime(dst_path, (st.st_atime, st.st_mtime))
    return h.hexdigest()


def cmd_copy(a):
    src = os.path.realpath(os.path.expanduser(a.src))
    dest = os.path.realpath(os.path.expanduser(a.dest))
    manifest = os.path.realpath(os.path.expanduser(a.manifest))
    if not os.path.isdir(src):
        sys.exit(f"source not found: {src}")
    if dest == src or dest.startswith(src + os.sep) or src.startswith(dest + os.sep):
        sys.exit("refusing: source and destination must not contain each other")
    if os.path.exists(manifest):
        sys.exit(f"refusing: manifest already exists (never overwritten): {manifest}")
    files, symlinks, conflicts, errors = [], [], [], []
    copied = skipped_same = 0
    for p, kind in walk(src, a.skip):
        rel = os.path.relpath(p, src).replace(os.sep, "/")
        if kind == "symlink":
            symlinks.append({"path": rel, "target": os.readlink(p)})
            continue
        dst = os.path.join(dest, rel)
        try:
            st = os.stat(p)
            if os.path.lexists(dst):
                h_src, h_dst = sha256_file(p), sha256_file(dst)
                if h_src == h_dst:
                    skipped_same += 1
                    files.append({"path": rel, "bytes": st.st_size, "sha256": h_src, "mtime": int(st.st_mtime)})
                else:
                    conflicts.append({"path": rel, "src_sha256": h_src, "dest_sha256": h_dst})
                continue
            h = copy_exclusive(p, dst)
            if sha256_file(dst) != h:
                errors.append({"path": rel, "error": "hash mismatch after copy"})
                continue
            copied += 1
            files.append({"path": rel, "bytes": st.st_size, "sha256": h, "mtime": int(st.st_mtime)})
        except OSError as e:
            errors.append({"path": rel, "error": str(e)})
    data = {"tool": "snapshot.py", "created": time.strftime("%Y-%m-%d %H:%M:%S"), "src": src, "dest": dest,
            "skipped_dirs": sorted(SKIP_DIRS | set(a.skip)), "files": files, "symlinks": symlinks,
            "conflicts": conflicts, "errors": errors,
            "totals": {"files": len(files), "copied": copied, "already_identical": skipped_same,
                       "bytes": sum(f["bytes"] for f in files), "symlinks": len(symlinks),
                       "conflicts": len(conflicts), "errors": len(errors)}}
    os.makedirs(os.path.dirname(manifest), exist_ok=True)
    with open(manifest, "x", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print(json.dumps(data["totals"]))
    return 2 if (conflicts or errors) else 0


def cmd_verify(a):
    with open(os.path.expanduser(a.manifest), encoding="utf-8") as fh:
        m = json.load(fh)
    bad = []
    for f in m["files"]:
        for root, label in ((m["dest"], "dest"), (os.path.realpath(os.path.expanduser(a.src)) if a.src else None, "src")):
            if root is None:
                continue
            p = os.path.join(root, f["path"])
            if not os.path.isfile(p):
                bad.append({"path": f["path"], "where": label, "problem": "missing"})
            elif sha256_file(p) != f["sha256"]:
                bad.append({"path": f["path"], "where": label, "problem": "changed"})
    print(json.dumps({"checked": len(m["files"]), "problems": len(bad), "first": bad[:10]}, ensure_ascii=False))
    return 2 if bad else 0


def main():
    ap = argparse.ArgumentParser(description="Copy-only snapshot with SHA-256 manifest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("copy")
    c.add_argument("--src", required=True)
    c.add_argument("--dest", required=True)
    c.add_argument("--manifest", required=True)
    c.add_argument("--skip", action="append", default=[], help="extra directory name to skip")
    v = sub.add_parser("verify")
    v.add_argument("--manifest", required=True)
    v.add_argument("--src")
    a = ap.parse_args()
    sys.exit(cmd_copy(a) if a.cmd == "copy" else cmd_verify(a))


if __name__ == "__main__":
    main()
