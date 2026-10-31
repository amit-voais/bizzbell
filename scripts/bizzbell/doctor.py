"""bb doctor: is this machine ready? Checks tools, the key (never shown), the gateway, the models, the media
endpoints, and picks the text models. Never makes a paid call.

Model choice for the "auto" text roles (written to bizzbell.json models_chosen with the reason):
  restructure = an id containing "opus" (highest version number first), else the strongest by TEXT_PREFERENCE;
  writer      = the strongest that is not the restructure model (cheaper drafts), else the same;
  judge       = the strongest that is neither the writer nor the restructure model (the judge must not score
                its own work), else the strongest that is not the writer."""
import os
import re
import shutil
import subprocess
import sys

from . import hidrogen, project, util

# Strongest first. Each entry is a substring matched case-insensitively against the model id.
TEXT_PREFERENCE = ["opus", "gpt-5", "gemini-3-pro", "gemini-2.5-pro", "sonnet", "o3", "gpt-4.1", "gpt-4o",
                   "gemini-3-flash", "gemini-2.5-flash", "flash", "haiku", "mini"]
NOT_TEXT = ("image", "video", "voice", "music", "tts", "speech", "embed", "whisper", "transcribe", "judge",
            "moderation")
MEDIA_ENDPOINTS = {"images": "/v1/images/generations", "videos": "/v1/videos", "voice": "/v1/audio/speech",
                   "music": "/v1/music", "media_judge": "/v1/media/judge", "quote": "/v1/media/quote"}
INSTALL = {"darwin": "brew install ffmpeg node", "linux": "sudo apt-get install ffmpeg nodejs npm",
           "win32": "winget install Gyan.FFmpeg OpenJS.NodeJS"}


def _version_key(mid):
    return [int(x) for x in re.findall(r"\d+", mid)][:4]


def rank(mid):
    """Lower is stronger; ids matching nothing rank last."""
    low = mid.lower()
    for i, pat in enumerate(TEXT_PREFERENCE):
        if pat in low:
            return i
    return len(TEXT_PREFERENCE)


def text_models(ids):
    """Model ids that look like text/chat models, strongest first."""
    ids = [i for i in ids if not any(n in i.lower() for n in NOT_TEXT)]
    by_version = sorted(ids, key=_version_key, reverse=True)
    return sorted(by_version, key=rank)          # stable: same rank -> higher version first


def pick_models(ids):
    """{role: (id, reason)} for restructure, writer, judge from the ids /v1/models returned."""
    tm = text_models(ids)
    if not tm:
        return {}
    out = {}
    opus = [i for i in tm if "opus" in i.lower()]
    if opus:
        out["restructure"] = (opus[0], "an Opus-class model is available to this key")
    else:
        out["restructure"] = (tm[0], "no Opus model on this key; strongest available by the preference list")
    rest = [i for i in tm if i != out["restructure"][0]]
    out["writer"] = (rest[0], "strongest model other than the restructure model") if rest else \
        (tm[0], "only one text model on this key")
    judges = [i for i in tm if i not in (out["writer"][0], out["restructure"][0])]
    if judges:
        out["judge"] = (judges[0], "strongest model that is neither the writer nor the restructure model")
    else:
        others = [i for i in tm if i != out["writer"][0]]
        out["judge"] = (others[0], "strongest model that is not the writer") if others else \
            (tm[0], "only one text model on this key: the judge is also the writer")
    return out


def _tool(name):
    p = shutil.which(name)
    if not p and os.path.exists("/opt/homebrew/bin/" + name):
        p = "/opt/homebrew/bin/" + name
    return p


def _ver(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (r.stdout or r.stderr).strip().splitlines()[0][:80]
    except Exception:
        return ""


def run(root=None, write=True):
    """Run every check. Returns {"checks": [{name, ok, detail}], "models": {...}, "endpoints": {...}, "saved"}."""
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": ok, "detail": hidrogen.redact(detail)})

    add("python", sys.version_info >= (3, 9), "Python %d.%d.%d" % sys.version_info[:3])
    hint = INSTALL.get(sys.platform, INSTALL["linux"])
    for t in ("ffmpeg", "ffprobe"):
        p = _tool(t)
        add(t, bool(p), _ver([p, "-version"]) if p else "missing: install with `%s`" % hint)
    node = _tool("node")
    nv = _ver([node, "--version"]) if node else ""
    node_ok = bool(node) and bool(re.match(r"v?(\d+)", nv)) and int(re.match(r"v?(\d+)", nv).group(1)) >= 18
    add("node", node_ok, ("Node %s" % nv) if node else "missing (needed for HyperFrames): install with `%s`" % hint)
    add("npx", bool(_tool("npx")), "present" if _tool("npx") else "missing (comes with Node)")
    has = hidrogen.has_key()
    add("key", has, "present (not shown)" if has else "missing: run python3 scripts/bb.py key")
    result = {"checks": checks, "models": {}, "endpoints": {}, "saved": None}
    if not has:
        return result
    try:
        ids = [m.get("id", "") for m in hidrogen.models()]
        add("gateway", True, "%s answered; %d models for this key" % (hidrogen.api_url(), len(ids)))
    except hidrogen.HidrogenError as e:
        add("gateway", False, str(e))
        return result
    picks = pick_models(ids)
    result["models"] = {r: {"id": i, "reason": why} for r, (i, why) in picks.items()}
    if "restructure" in picks:
        add("restructure model", True, "%s (%s)" % picks["restructure"])
    else:
        add("restructure model", False, "no text model on this key")
    eps = {name: hidrogen.probe(p) for name, p in MEDIA_ENDPOINTS.items()}
    result["endpoints"] = eps
    missing = [n for n, v in eps.items() if v == "missing"]
    add("media endpoints", not missing, "all live" if not missing else
        "not live: %s (Version A is skipped when videos is not live; Version B still runs)" % ", ".join(missing))
    if write:
        result["saved"] = save(root, result)
    return result


def save(root, result):
    """Write models_chosen + endpoints into bizzbell.json (or the user settings without a project)."""
    def f(s):
        mc = s.setdefault("models_chosen", {})
        for role, v in result["models"].items():
            mc[role] = dict(v, at=util.now())
        s["endpoints"] = dict(result["endpoints"], checked=util.now())
    project.update_settings(root, f)
    return os.path.join(root, "bizzbell.json") if root else project.user_settings_path()


def format_result(res):
    lines = []
    for c in res["checks"]:
        lines.append("  %s %-18s %s" % ("ok  " if c["ok"] else "FAIL", c["name"], c["detail"]))
    for role, v in sorted(res["models"].items()):
        lines.append("  model %-12s %s  (%s)" % (role, v["id"], v["reason"]))
    if res.get("saved"):
        lines.append("saved to %s" % res["saved"])
    bad = [c["name"] for c in res["checks"] if not c["ok"]]
    lines.append("ready" if not bad else "not ready: " + ", ".join(bad))
    return "\n".join(lines)
