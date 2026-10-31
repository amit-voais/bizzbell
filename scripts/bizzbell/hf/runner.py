"""Run the pinned HyperFrames CLI (`npx -y hyperframes@<pin> ...`) and find its headless Chrome.

The pin lives in bizzbell.json "hyperframes": {"version": "..."}; it must be a plain x.y.z version at least two
weeks old that renders locally. HyperFrames telemetry, update checks and skill installs are switched off for
every call. Nothing here opens a window: HyperFrames renders with chrome-headless-shell."""
import json
import os
import re
import shutil
import subprocess

from .. import project
from ..errors import BBError, ConfigError

_CACHE = {}
QUIET_ENV = {"HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1", "HYPERFRAMES_NO_UPDATE_CHECK": "1",
             "HYPERFRAMES_SKIP_SKILLS": "1", "HYPERFRAMES_NO_AUTO_INSTALL": "1", "NO_COLOR": "1",
             "FORCE_COLOR": "0"}


class Unavailable(BBError):
    """Node/npx or the pinned HyperFrames could not run (offline, not installed)."""


def pin(root=None):
    """The pinned HyperFrames version from bizzbell.json (default project.HYPERFRAMES_VERSION)."""
    v = str((project.load_settings(root).get("hyperframes") or {}).get("version") or project.HYPERFRAMES_VERSION)
    if not re.match(r"^\d+\.\d+\.\d+$", v):
        raise ConfigError("bizzbell.json hyperframes.version must be an exact version like %s, not %r"
                          % (project.HYPERFRAMES_VERSION, v))
    return v


def npx():
    """Path to npx, or None."""
    return shutil.which("npx") or next((p for p in ("/opt/homebrew/bin/npx", "/usr/local/bin/npx")
                                        if os.path.exists(p)), None)


def env():
    """The environment for npx: quiet HyperFrames, and no HIDROGEN_* variable (the key stays out of third-party
    code that does not need it)."""
    e = {k: v for k, v in os.environ.items() if not k.upper().startswith("HIDROGEN_")}
    e.update(QUIET_ENV)
    path = e.get("PATH", "")
    for extra in ("/opt/homebrew/bin", "/usr/local/bin"):
        if extra not in path.split(os.pathsep) and os.path.isdir(extra):
            path = path + os.pathsep + extra
    e["PATH"] = path
    return e


def run(args, root=None, cwd=None, timeout=900, check=True):
    """Run `npx -y hyperframes@<pin> <args>`. Returns CompletedProcess (text). Raises Unavailable without npx,
    BBError on a timeout, or on a non-zero exit when check=True."""
    exe = npx()
    if not exe:
        raise Unavailable("npx was not found: install Node.js 22+ (https://nodejs.org) to make Version B")
    cmd = [exe, "-y", "hyperframes@%s" % pin(root)] + list(args)
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env(), capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise BBError("hyperframes %s did not finish within %d s" % (args[0] if args else "", timeout))
    if check and r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-6:]
        raise BBError("hyperframes %s failed (exit %d): %s" % (args[0] if args else "", r.returncode,
                                                                " | ".join(tail)))
    return r


def run_json(args, root=None, cwd=None, timeout=900):
    """Run a `--json` command and parse its stdout (the JSON object; log lines around it are ignored)."""
    r = run(list(args) + ["--json"], root=root, cwd=cwd, timeout=timeout, check=False)
    out = r.stdout or ""
    start = out.find("{")
    end = out.rfind("}")
    if start < 0 or end < start:
        tail = (r.stderr or out).strip().splitlines()[-6:]
        raise BBError("hyperframes %s gave no JSON (exit %d): %s" % (args[0], r.returncode, " | ".join(tail)))
    try:
        return json.loads(out[start:end + 1])
    except ValueError as e:
        raise BBError("hyperframes %s gave unreadable JSON: %s" % (args[0], e))


def available(root=None, timeout=240):
    """(True, version) when the pinned HyperFrames runs here, else (False, reason). Cached per pin."""
    try:
        v = pin(root)
    except ConfigError as e:
        return False, str(e)
    if v in _CACHE:
        return _CACHE[v]
    if not npx():
        res = (False, "npx not found (install Node.js 22+)")
    else:
        try:
            r = run(["--version"], root=root, timeout=timeout, check=False)
            got = (r.stdout or "").strip().splitlines()
            ok = r.returncode == 0 and got and got[-1].strip() == v
            res = (True, v) if ok else (False, "npx could not run hyperframes@%s (offline?): %s"
                                        % (v, " ".join((r.stderr or "").strip().splitlines()[-2:])[:300]))
        except BBError as e:
            res = (False, str(e))
    _CACHE[v] = res
    return res


def _last_line(r):
    return ((r.stdout or "").strip().splitlines() or [""])[-1].strip()


def headless_shell(p):
    """True when `p` is chrome-headless-shell (what HyperFrames downloads), not a full desktop Chrome."""
    return os.path.basename(p or "").lower().startswith("chrome-headless-shell")


def browser_path(root=None):
    """HyperFrames' chrome-headless-shell (downloaded on first use). $HYPERFRAMES_BROWSER_PATH wins.

    `hyperframes browser path` falls back to a system Google Chrome when nothing is cached yet, and full Chrome
    hangs on the DOM bounds check (--virtual-time-budget), so a full Chrome is replaced by a headless-shell
    download (`browser ensure --force`, which only downloads; plain `ensure` would settle for the system one)."""
    if "browser" in _CACHE:
        return _CACHE["browser"]
    p = os.environ.get("HYPERFRAMES_BROWSER_PATH", "")
    if not (p and os.path.exists(p)):
        p = _last_line(run(["browser", "path"], root=root, timeout=300, check=False))
        if not (p and os.path.exists(p) and headless_shell(p)):
            fallback = p if (p and os.path.exists(p)) else ""
            run(["browser", "ensure", "--force"], root=root, timeout=900, check=not fallback)
            p = _last_line(run(["browser", "path"], root=root, timeout=300, check=False))
            if not (p and os.path.exists(p)):
                p = fallback
    if not (p and os.path.exists(p)):
        raise Unavailable("HyperFrames' headless Chrome was not found (try: npx hyperframes browser ensure --force)")
    _CACHE["browser"] = p
    return p
