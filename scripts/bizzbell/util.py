"""Small shared helpers: atomic JSON files, a file lock, timestamps, package paths."""
import contextlib
import fcntl
import json
import os
import time

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(PKG_DIR)
ROOT_DIR = os.path.dirname(SCRIPTS_DIR)          # the skill folder (SKILL.md, rubrics/, templates/ ...)


def now():
    """Local time as 'YYYY-MM-DD HH:MM:SS'."""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_json(path, default=None):
    """Parsed JSON at `path`, or `default` when the file does not exist."""
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    """Write JSON atomically (tmp file + rename), UTF-8, indented."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def read_text(path, default=""):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def write_text(path, text):
    """Write text atomically."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


@contextlib.contextmanager
def locked(path):
    """Exclusive advisory lock on `<path>.lock` for the duration of the block."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


@contextlib.contextmanager
def updating_json(path, default=None):
    """Lock, load, yield the dict for in-place edits, then save. `default` is used when missing."""
    with locked(path):
        data = read_json(path, default if default is not None else {})
        yield data
        write_json(path, data)


def deep_merge(base, extra):
    """Return a copy of `base` with `extra` merged in (dicts recursively, everything else replaced)."""
    out = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out
