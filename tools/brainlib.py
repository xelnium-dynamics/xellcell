"""brainlib.py — shared helpers for the Agent Brain tools (Python 3.9+ standard library only).

Every tool adds its own folder to sys.path before importing this module, because `python3 -I`
does not put the script's folder on the import path.
"""
import hashlib, json, os, re, subprocess, tempfile, time

ROOT = os.environ.get("BRAIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT = os.environ.get("BRAIN_VAULT") or os.path.join(ROOT, "Brain System")  # the Obsidian vault folder
SESSIONS = os.path.join(ROOT, "sessions")
QUEUE = os.path.join(ROOT, "queue")
INDEX_DB = os.environ.get("BRAIN_INDEX_DB") or os.path.join(ROOT, "index", "brain.db")
STATE = os.path.join(ROOT, "state")
JUDGE = os.path.join(ROOT, "judge")
TOOLS = os.path.dirname(os.path.abspath(__file__))  # v2.1: the code folder itself (same as ROOT/tools on the live brain;
#                                                   in a test brain under BRAIN_ROOT the scripts still resolve)
SKIP_DIRS = {".obsidian", ".trash", ".git", "__pycache__", ".smart-env", ".makemd"}

# Which vault collections a task class may read (layer 3). "self" never appears unless listed.
SCOPES = {
    "cv_official": ["self", "capabilities", "domains", "projects/job-search", "system", "lessons"],
    "personal": ["self", "domains", "capabilities", "lessons"],
    "engineering": ["projects", "domains", "capabilities", "history", "system", "lessons"],
    "website": ["projects", "domains", "capabilities", "history", "system", "lessons"],
    "brand": ["projects", "domains", "capabilities", "history", "system", "lessons"],
    "research": ["domains", "capabilities", "projects", "history", "system", "lessons"],
    "system": ["system", "capabilities", "history", "lessons"],
    "general": ["projects", "domains", "capabilities", "history", "system", "lessons"],
}
PRIVATE_SCOPES = ("cv_official", "personal")
LANES = ("fast", "standard", "deep")


def today():
    return time.strftime("%Y-%m-%d")


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path, text, exclusive=False):
    """Write text so readers never see half a file. exclusive=True refuses to replace an existing file."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if exclusive:
            os.link(tmp, path)  # fails if path exists: atomic "create only"
        else:
            os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class LockBusy(Exception):
    """Another brain process holds the lock longer than we were willing to wait."""


import contextlib  # noqa: E402


@contextlib.contextmanager
def lock(name="repo", timeout_s=30.0):
    """Advisory cross-process lock on state/<name>.lock (v2.1, O1). Every tool that writes shared state
    (index + TOC, live-links, git commits by sleep/gym) takes it, so two sessions never interleave writes.
    Raises LockBusy after timeout_s. The lock dies with the process, so a crash never leaves it stuck."""
    import fcntl
    os.makedirs(STATE, exist_ok=True)
    fd = os.open(os.path.join(STATE, f"{name}.lock"), os.O_RDWR | os.O_CREAT, 0o644)
    t0 = time.time()
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() - t0 >= timeout_s:
                    raise LockBusy(name)
                time.sleep(0.05)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()} {now()}\n".encode())
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def git_commit_paths(paths, message, root=None):
    """Commit ONLY `paths` (their working-tree content) without touching anything the owner or another session
    has staged (v2.1, O1). Uses a private index file seeded from HEAD, then moves the branch with a
    compare-and-swap update-ref. Returns the new commit sha, or None when nothing changed / git refused."""
    root = root or ROOT
    paths = [p for p in paths if os.path.exists(os.path.join(root, p))]
    if not paths:
        return None
    g = lambda *a, env=None: subprocess.run(["git", "-C", root] + list(a), capture_output=True, text=True, env=env)
    head = g("rev-parse", "-q", "--verify", "HEAD").stdout.strip()
    ref = g("symbolic-ref", "-q", "HEAD").stdout.strip()
    if not head or not ref:
        return None
    with lock("repo"):
        fd, tmp_index = tempfile.mkstemp(prefix="brain-index-", dir=STATE)
        os.close(fd)
        os.unlink(tmp_index)
        env = dict(os.environ, GIT_INDEX_FILE=tmp_index)
        try:
            if g("read-tree", head, env=env).returncode != 0:
                return None
            g("add", "-A", "--", *paths, env=env)
            if g("diff", "--cached", "--quiet", head, "--", *paths, env=env).returncode == 0:
                return None
            tree = g("write-tree", env=env).stdout.strip()
            commit = g("commit-tree", tree, "-p", head, "-m", message).stdout.strip()
            if not commit or g("update-ref", "-m", message.splitlines()[0][:80], ref, commit, head).returncode != 0:
                return None
        finally:
            if os.path.exists(tmp_index):
                os.unlink(tmp_index)
        # keep the real index in step for these paths only (so git status does not show them as staged reversals)
        g("reset", "-q", "--", *paths)
        return commit


def next_release_tag(root=None):
    root = root or ROOT
    day = time.strftime("%Y%m%d")
    tags = subprocess.run(["git", "-C", root, "tag", "--list", f"rel-{day}-*"], capture_output=True, text=True).stdout.split()
    n = 1 + max([int(t.rsplit("-", 1)[1]) for t in tags if t.rsplit("-", 1)[1].isdigit()] or [0])
    return f"rel-{day}-{n}"


def last_json(raw, accept=lambda o: True):
    """The LAST JSON object in raw text that accept() takes (v2.1, O14): CLI output may carry banners, warnings
    or prose with braces before or after the verdict, which a greedy regex turns into invalid JSON."""
    dec = json.JSONDecoder()
    i = len(raw or "")
    while True:
        i = raw.rfind("{", 0, i)
        if i < 0:
            return None
        try:
            obj, _ = dec.raw_decode(raw, i)
        except ValueError:
            continue
        if isinstance(obj, dict) and accept(obj):
            return obj


def write_if_changed(path, text):
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == text:
                return False
    except OSError:
        pass
    atomic_write(path, text)
    return True


def split_frontmatter(text):
    if not text.startswith("---"):
        return None, text
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(\r?\n|$)", text, re.S)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def parse_frontmatter(fm):
    """Minimal YAML reader: top-level scalars and simple lists. Never raises."""
    data, current = {}, None
    for line in (fm or "").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        km = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
        if km and not line.startswith((" ", "\t", "-")):
            current = km.group(1).lower()
            val = km.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                data[current] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            elif val in ("", "|", ">", "|-", ">-"):
                data[current] = [] if val == "" else ""
            else:
                data[current] = val.strip("'\"")
            continue
        lm = re.match(r"^\s*-\s+(.*)$", line)
        if lm and current is not None:
            if not isinstance(data.get(current), list):
                data[current] = [] if not data.get(current) else [data[current]]
            data[current].append(lm.group(1).strip().strip("'\""))
        elif current is not None and isinstance(data.get(current), str) and line.startswith((" ", "\t")):
            data[current] = (data[current] + " " + line.strip()).strip()
    return data


def read_note(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    fm, body = split_frontmatter(text)
    meta = parse_frontmatter(fm) if fm is not None else {}
    heads = re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.sub(r"```.*?```", "", body, flags=re.S), re.M)
    title = meta.get("title") if isinstance(meta.get("title"), str) and meta.get("title") else (
        heads[0] if heads else os.path.splitext(os.path.basename(path))[0])
    return {"meta": meta, "body": body, "headings": heads, "title": title, "has_frontmatter": fm is not None}


def iter_notes(root=None):
    root = root or VAULT
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        for f in sorted(files):
            if f.endswith(".md") and not f.startswith("."):
                yield os.path.join(d, f)


def collection_of(path):
    """('projects', 'client-a') for Brain System/projects/client-a/x.md; ('domains', 'web-design'); ('self', '')."""
    r = os.path.relpath(path, VAULT).replace(os.sep, "/").split("/")
    top = r[0] if len(r) > 1 else "(root)"
    sub = r[1] if len(r) > 2 else ""
    return top, sub


def allowed(collection, sub, scope_class):
    rules = SCOPES.get(scope_class or "general", SCOPES["general"])
    full = f"{collection}/{sub}" if sub else collection
    return any(full == r or full.startswith(r + "/") or collection == r for r in rules)


def lesson_visible(path, scope_class):
    """v3 (C1): a lesson is routed only once the owner released it (candidates and retired ones stay out), and a lesson
    learned in a private session (cv_official, personal) is shown only to a private session."""
    try:
        with open(path if os.path.isabs(path) else os.path.join(ROOT, path), encoding="utf-8", errors="replace") as fh:
            fm, _ = split_frontmatter(fh.read(4000))
    except OSError:
        return False
    meta = parse_frontmatter(fm) if fm else {}
    if str(meta.get("status", "")).strip() != "released":
        return False
    return str(meta.get("scope_class", "")).strip() not in PRIVATE_SCOPES or scope_class in PRIVATE_SCOPES


def local_epoch(stamp):
    """'2026-11-10 01:05:23' (local time, as B.now() writes it) -> epoch seconds, or None."""
    try:
        return time.mktime(time.strptime(str(stamp)[:19], "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return None


def hook_errors(days=7):
    """(count, last line) of state/analysis/hook-errors.log within `days` (v3, A5): a gate that errors lets the call
    through, so the card and the digest must show it."""
    n, last, cut = 0, "", time.time() - days * 86400
    try:
        with open(os.path.join(STATE, "analysis", "hook-errors.log"), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                t = local_epoch(line[:19])
                if t and t >= cut:
                    n, last = n + 1, line.strip()
    except OSError:
        pass
    return n, last


def git_release(root=None):
    root = root or ROOT
    try:
        out = subprocess.run(["git", "-C", root, "describe", "--tags", "--always", "--dirty"],
                             capture_output=True, text=True, timeout=3)
        return out.stdout.strip() or "no-release"
    except Exception:
        return "no-git"


def vault_max_mtime(root=None):
    m = 0.0
    for p in iter_notes(root):
        if "/00-toc/" in p.replace(os.sep, "/"):
            continue
        try:
            m = max(m, os.path.getmtime(p))
        except OSError:
            pass
    return m


def language_policy(root=None):
    """Optional state/vault-policy.json (public release): which writing scripts the vault forbids, which rules count as
    errors, whether skill descriptions are shown in English only. Missing file = every language is allowed.
        {"disallowed_scripts": {"Name": "<regex>"}, "warn_scripts": {"Name": "<regex>"},
         "forbidden_rules": ["<regex>"], "english_only_descriptions": false}"""
    return load_json(os.path.join(root or ROOT, "state", "vault-policy.json"), {}) or {}


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def project_for_cwd(cwd):
    """Longest matching folder prefix in state/folder-projects.json, else None."""
    mapping = load_json(os.path.join(STATE, "folder-projects.json"), {})
    cwd = os.path.realpath(os.path.expanduser(cwd or os.getcwd()))
    best, slug = "", None
    for prefix, proj in mapping.items():
        p = os.path.realpath(os.path.expanduser(prefix))
        if (cwd == p or cwd.startswith(p + os.sep)) and len(p) > len(best):
            best, slug = p, proj
    return slug


def slugify(text, maxlen=48):
    s = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.U).strip()
    s = re.sub(r"[\s_]+", "-", s)
    return (s[:maxlen].strip("-")) or "untitled"
