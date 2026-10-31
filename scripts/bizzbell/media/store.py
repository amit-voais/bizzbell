"""Per-stage records kept in the project (all JSON, file-locked):

  <dir>/registry.json   {"items": {id: {"status", "file", "take", "source", "prompt_hash", "score", "note",
                                         "takes": [{"n", "file", "status", "local", "score", "failed", "note",
                                                    "time"}]}}, ...}
  <dir>/prompts.json    {id: "prompt text" | {...}}: what is sent for each item. Written from the screenplay the
                        first time; after that it is the source of truth (bb restructure rewrites it for a media
                        layer, and items whose prompt changed are made again on the next run).

Item status: accepted (passed the take checks), approved (the user said yes / imported), flagged (no take passed
within max_takes: the best one is in place and marked), rejected, blocked, skipped."""
import hashlib
import json
import os
import re
import shutil

from .. import project, util
from ..errors import UsageError

GOOD = ("accepted", "approved")


def reg_path(root, d):
    return os.path.join(root, d, "registry.json")


def load_registry(root, d):
    return util.read_json(reg_path(root, d), None) or {"items": {}}


def update_registry(root, d, fn):
    """Locked read-modify-write of <dir>/registry.json; fn(reg) edits in place. Returns the registry."""
    p = reg_path(root, d)
    with util.updating_json(p, {"items": {}}) as reg:
        reg.setdefault("items", {})
        fn(reg)
    return util.read_json(p)


def item(reg, iid):
    return reg.setdefault("items", {}).setdefault(iid, {"status": "todo", "takes": []})


def takes_used(it, prompt_hash=None):
    """Takes that count toward max_takes: blocked calls (charged 0) do not count, and when `prompt_hash` is given
    only takes made from that prompt count (a restructured prompt starts a fresh set of takes)."""
    return len([t for t in it.get("takes", []) if t.get("status") != "blocked" and
                (prompt_hash is None or t.get("ph", prompt_hash) == prompt_hash)])


MEDIA_DEFAULTS = {"fps": 24, "width": None, "image_size": "2K", "resolution": "720p", "clip_seconds": 6,
                  "clip_start": 0.3, "voice_onset": 0.15, "line_gap": 0.25, "vo_lufs": -18.0, "bed_lufs": -30.0,
                  "target_lufs": -14.0, "true_peak": -1.5, "caption_chars": 42}


def media_settings(root):
    """bizzbell.json "media" merged over MEDIA_DEFAULTS."""
    return util.deep_merge(MEDIA_DEFAULTS, project.load_settings(root).get("media") or {})


def max_takes(root):
    b = project.load_settings(root).get("budget", {})
    try:
        return max(1, int(b.get("max_takes", 3)))
    except (TypeError, ValueError):
        return 3


def needs_work(root, it, ph, redo=False):
    """True when an item must be (re)made: asked to redo, nothing usable in place, or (for an item the take loop
    accepted or flagged) its prompt changed since. Items the user approved or imported are never remade unasked."""
    if redo:
        return True
    have = it.get("status") in GOOD + ("flagged",) and it.get("file") and os.path.exists(os.path.join(root,
                                                                                                    it["file"]))
    if not have:
        return True
    return it.get("status") in ("accepted", "flagged") and it.get("prompt_hash") not in (None, ph)


# ---------------------------------------------------------------- prompts
def prompts_path(root, d):
    return os.path.join(root, d, "prompts.json")


def load_prompts(root, d):
    try:
        return util.read_json(prompts_path(root, d), None) or {}
    except ValueError as e:
        raise UsageError("%s/prompts.json is not valid JSON (%s): fix it or rebuild it with --rebuild-prompts"
                         % (d, e))


def sync_prompts(root, d, built, rebuild=False):
    """Add prompts for new items (all of them when rebuild). Keeps edited/restructured ones. Returns the dict."""
    p = prompts_path(root, d)
    with util.locked(p):
        cur = {} if rebuild else (util.read_json(p, None) or {})
        changed = False
        for k, v in built.items():
            if k not in cur:
                cur[k] = v
                changed = True
        if changed or rebuild or not os.path.exists(p):
            util.write_json(p, cur)
    return cur


def phash(value):
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def idem(root, *parts):
    """A stable Idempotency-Key for one take: a re-run after a crash replays instead of paying twice."""
    slug = project.load_state(root).get("slug", "")
    raw = "|".join([slug, os.path.basename(root)] + [str(p) for p in parts])
    return "bb-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------- files
def safe(name):
    """A file-name-safe version of an id."""
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", str(name))


def rel(root, p):
    return os.path.relpath(p, root)


def move_to(root, src_rel, dest_dir_rel, name=None):
    """Move a project file into dest_dir (made if needed), never overwriting. Returns the new relative path."""
    src = os.path.join(root, src_rel)
    if not os.path.exists(src):
        return None
    d = os.path.join(root, dest_dir_rel)
    os.makedirs(d, exist_ok=True)
    base = name or os.path.basename(src)
    stem, ext = os.path.splitext(base)
    dst = os.path.join(d, base)
    i = 2
    while os.path.exists(dst):
        dst = os.path.join(d, "%s_%d%s" % (stem, i, ext))
        i += 1
    shutil.move(src, dst)
    return rel(root, dst)


def write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


# ---------------------------------------------------------------- consent + bible.md
def consent_problem(root, names=()):
    """None when CONSENT.md names each real person in `names`, the film, the channels, how long, and a date
    (YYYY-MM-DD) - the same rule as the consent_for_real_faces gate check; else why not."""
    p = os.path.join(root, "CONSENT.md")
    text = util.read_text(p)
    if not text.strip():
        return ("a real person's face needs CONSENT.md in the project first (who, which film, channels, how long, "
                "the date as YYYY-MM-DD; the voice stays synthetic). Nothing was sent.")
    low = text.lower()
    missing = ["the name %s" % n for n in names if n and n.lower() not in low]
    missing += [k for k in ("film", "channel", "how long") if k not in low]
    if not re.search(r"\d{4}-\d{2}-\d{2}", text):
        missing.append("a date (YYYY-MM-DD)")
    if missing:
        return "CONSENT.md does not say: %s. Add it, then run this again. Nothing was sent." % ", ".join(missing)
    return None


def bible_sections(root):
    """{heading (lower case): text} of characters/bible.md (## / ### headings). Raises UsageError if missing."""
    p = os.path.join(root, "characters", "bible.md")
    if not os.path.exists(p):
        raise UsageError("characters/bible.md is missing: write the in-depth character bible from the screenplay "
                         "first (face, skin, hair, build, wardrobe per scene, fixed details)")
    out, cur, buf = {}, None, []
    for line in util.read_text(p).splitlines():
        m = re.match(r"^#{2,4}\s+(.+?)\s*$", line)
        if m:
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1).strip().lower(), []
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def bible_for(sections, *names):
    """The bible.md section whose heading mentions one of `names` (case-insensitive), or ''."""
    for n in names:
        n = (n or "").lower().strip()
        if not n:
            continue
        for head, text in sections.items():
            if re.search(r"(?<!\w)%s(?!\w)" % re.escape(n), head):
                return text
    return ""
