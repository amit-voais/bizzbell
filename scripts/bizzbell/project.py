"""A Bizzbell project folder: layout, project.json (state), bizzbell.json (settings), stage order.

project.json   stage (next to do), status, stages{id: {status, gate_runs, last_gate, restructure_rounds, ...}},
               scores{id: last score}, spend{cap_inr, spent_inr, reserved_inr} (mirrored by the ledger)
bizzbell.json  models{role: id|"auto"}, models_chosen{role: {id, reason, at}}, budget{cap_inr, approved, ...},
               gate{pass_score, max_rounds, passes, disagree_points}, hyperframes{version}, endpoints{...}

Stage status values: todo, made, passed, failed, restructured, skipped (stored), and changed (computed: passed,
but a file its gate scored was changed or removed since)."""
import glob
import hashlib
import os
import re

from . import util
from .errors import ConfigError, OutOfOrder, UsageError

ROLES = ("writer", "judge", "restructure", "image", "video", "voice", "music")
TEXT_ROLES = ("writer", "judge", "restructure")

HYPERFRAMES_VERSION = "0.8.150"

# Stage order of the spec (section 5). "outputs" are globs relative to the project; a stage counts as made when
# every output glob matches at least one file, and for characters and keyframes also when every item the screenplay
# asks for is in place (media.layers.items_present), so a failed make never shows as made. "gated" stages need
# `bb gate <id>` to pass.
STAGES = [
    {"id": "brief", "n": "0", "title": "Brief + budget", "outputs": ["brief.md"], "gated": False},
    {"id": "research", "n": "1", "title": "Research", "outputs": ["research.md"], "gated": True},
    {"id": "story", "n": "2", "title": "Story", "outputs": ["story.md"], "gated": True},
    {"id": "humanize", "n": "3", "title": "Humanize", "outputs": ["story_humanized.md"], "gated": True},
    {"id": "screenplay", "n": "4", "title": "Screenplay, every second",
     "outputs": ["screenplay.md", "screenplay.json"], "gated": True},
    {"id": "characters", "n": "5", "title": "Characters", "outputs": ["characters/bible.md"], "gated": True},
    {"id": "keyframes", "n": "6", "title": "Keyframes", "outputs": ["keyframes/*.png"], "gated": True},
    {"id": "audio", "n": "7", "title": "Voice + music", "outputs": ["audio/mix.wav"], "gated": True},
    {"id": "video_a", "n": "8A", "title": "Version A: Hidrogen video", "outputs": ["out/A/*.mp4"], "gated": True},
    {"id": "video_b", "n": "8B", "title": "Version B: HyperFrames", "outputs": ["out/B/*.mp4"], "gated": True},
    {"id": "final", "n": "9", "title": "Final", "outputs": ["out/report.md"], "gated": False},
]
STAGE_IDS = [s["id"] for s in STAGES]
# Media sub-layers gated on their own (bb gate voice ...) and rolled up into their stage.
LAYER_PARENT = {"voice": "audio", "music": "audio", "mix": "audio", "clips": "video_a", "version_a": "video_a"}
STAGE_PARTS = {"audio": ("voice", "music", "mix"), "video_a": ("clips", "version_a")}
# The gated layers a paid stage builds on: they must be done (passed, accepted or skipped) before it spends.
_TEXT = ("research", "story", "humanize", "screenplay")
REQUIRES = {"characters": _TEXT, "keyframes": _TEXT + ("characters",), "audio": _TEXT,
            "video_a": _TEXT + ("characters", "keyframes")}
DIRS = ["characters", "keyframes", "audio", "clips", "out/A", "out/B", "gates", "rubrics", "refs"]

DEFAULT_SETTINGS = {
    "bizzbell": 1,
    "models": {"writer": "auto", "judge": "auto", "restructure": "auto", "image": "image-pro", "video": "video",
               "voice": "voice-studio", "music": "music"},
    "models_chosen": {},
    "budget": {"cap_inr": 0, "approved": False, "max_takes": 3,
               "rates_inr": {"chat": 2.0, "judge": 3.0, "image": 6.0, "video_second": 8.0, "voice": 1.0,
                             "music": 5.0, "chat_per_1k_tokens": 2.5}},
    "gate": {"pass_score": 95, "max_rounds": 3, "passes": 2, "disagree_points": 10},
    "hyperframes": {"version": HYPERFRAMES_VERSION},
    "voice": {"name": "priya"},
    "endpoints": {},
}


# ---------------------------------------------------------------- locating
def is_project(path):
    data = util.read_json(os.path.join(path, "project.json"))
    return isinstance(data, dict) and "bizzbell" in data


def find_project(arg=None):
    """Absolute project folder: `arg`, else $BB_PROJECT, else the nearest folder at/above cwd with project.json."""
    arg = arg or os.environ.get("BB_PROJECT")
    if arg:
        p = os.path.abspath(arg)
        if not is_project(p):
            raise UsageError("%s is not a Bizzbell project (no project.json). Make one with: "
                             "python3 scripts/bb.py init <folder> --brief \"...\"" % p)
        return p
    d = os.getcwd()
    while True:
        if is_project(d):
            return d
        up = os.path.dirname(d)
        if up == d:
            raise UsageError("no Bizzbell project here or above: pass --project <folder>")
        d = up


def path(root, *parts):
    return os.path.join(root, *parts)


# ---------------------------------------------------------------- settings + state
def user_settings_path():
    """User-level defaults (written by `bb doctor` without a project): ~/.config/bizzbell/settings.json."""
    return os.path.join(os.path.expanduser("~"), ".config", "bizzbell", "settings.json")


def load_settings(root=None):
    """bizzbell.json merged over the defaults (and over the user-level settings, if any)."""
    s = util.deep_merge(DEFAULT_SETTINGS, util.read_json(user_settings_path(), {}) or {})
    if root:
        s = util.deep_merge(s, util.read_json(path(root, "bizzbell.json"), {}) or {})
    return s


def save_settings(root, settings):
    util.write_json(path(root, "bizzbell.json"), settings)


def update_settings(root, fn):
    """Locked read-modify-write of bizzbell.json; fn(settings) edits in place. Returns the settings."""
    p = path(root, "bizzbell.json") if root else user_settings_path()
    with util.locked(p):
        s = util.read_json(p, {}) or {}
        fn(s)
        util.write_json(p, s)
    return s


def load_state(root):
    return util.read_json(path(root, "project.json"), {}) or {}


def update_state(root, fn):
    """Locked read-modify-write of project.json; fn(state) edits in place. Returns the state."""
    p = path(root, "project.json")
    with util.locked(p):
        st = util.read_json(p, {}) or {}
        fn(st)
        util.write_json(p, st)
    return st


def stage(stage_id):
    """The STAGES entry for `stage_id`. Raises UsageError for an unknown id."""
    for s in STAGES:
        if s["id"] == stage_id:
            return s
    raise UsageError("unknown stage %r (stages: %s)" % (stage_id, ", ".join(STAGE_IDS)))


def stage_state(root, stage_id):
    return dict(load_state(root).get("stages", {}).get(stage_id, {}))


def mark_stage(root, stage_id, status, **fields):
    """Set a stage's (or a media sub-layer's) status (todo|made|passed|failed|restructured|skipped) plus extra
    fields; refresh `stage`."""
    if stage_id not in STAGE_IDS and stage_id not in LAYER_PARENT:
        raise UsageError("unknown stage %r" % stage_id)

    def f(st):
        s = st.setdefault("stages", {}).setdefault(stage_id, {})
        s["status"] = status
        s["updated"] = util.now()
        s.update(fields)
    update_state(root, f)
    refresh(root)


# ---------------------------------------------------------------- layer snapshots
_HASHES = {}


def _file_sha(p):
    st = os.stat(p)
    key = (p, st.st_size, st.st_mtime_ns)
    if key not in _HASHES:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _HASHES[key] = h.digest()
    return _HASHES[key]


def files_hash(root, rel_files):
    """Short content hash of the given project files (names + bytes), or None when one of them is missing."""
    h = hashlib.sha256()
    for rel in rel_files:
        p = path(root, rel)
        if not os.path.isfile(p):
            return None
        h.update(rel.encode())
        h.update(_file_sha(p))
    return h.hexdigest()[:16]


def layer_changed(root, rec):
    """True when a stage record's layer snapshot (the files a gate scored or the user accepted) no longer matches
    the files on disk: one was changed, moved away or deleted. New files do not count (bb final adds sizes)."""
    snap = (rec or {}).get("layer") or {}
    if not snap.get("files") or not snap.get("hash"):
        return False
    return files_hash(root, snap["files"]) != snap["hash"]


def _changed(root, stage_id, state):
    stages = state.get("stages") or {}
    return any(layer_changed(root, stages.get(i)) for i in STAGE_PARTS.get(stage_id, (stage_id,)))


# ---------------------------------------------------------------- models
def model_for(root, role):
    """Model id for a role: $BB_<ROLE>_MODEL, else bizzbell.json models[role] (unless "auto"), else the id
    `bb doctor` chose. Raises ConfigError when nothing is set."""
    if role not in ROLES:
        raise ConfigError("unknown model role %r (roles: %s)" % (role, ", ".join(ROLES)))
    env = os.environ.get("BB_%s_MODEL" % role.upper(), "").strip()
    if env:
        return env
    s = load_settings(root)
    m = (s.get("models") or {}).get(role, "auto")
    if m and m != "auto":
        return m
    chosen = (s.get("models_chosen") or {}).get(role) or {}
    if chosen.get("id"):
        return chosen["id"]
    raise ConfigError("no model chosen for the %s role yet: run python3 scripts/bb.py doctor -p <folder> until it "
                      "says ready (it needs the key to read /v1/models), or set BB_%s_MODEL" % (role, role.upper()))


# ---------------------------------------------------------------- init + status
def slugify(text, fallback="film", limit=40):
    """A file-name slug of at most `limit` characters, cut at a word boundary (never mid-word)."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if len(s) > limit:
        cut = s[:limit + 1]
        s = cut.rsplit("-", 1)[0] if "-" in cut else s[:limit]
    return s.strip("-") or fallback


BRIEF_TEMPLATE = """# Brief

{brief}

- Language: {lang}
- Aspect (master): {aspect}
- Length: (seconds)
- Product / offer:
- Audience:
- Call to action:
- Must say / must not say:
- Budget cap (INR): not set yet. Nothing is spent before the user approves one (python3 scripts/bb.py budget set <inr>).
"""


def init(folder, brief, lang="en", aspect="9:16", slug=None):
    """Create the project layout. Refuses a folder that already holds a project. Returns the absolute path."""
    if not (brief or "").strip():
        raise UsageError("a brief is needed: --brief \"what the video is for\"")
    if aspect not in ("9:16", "16:9", "1:1", "4:5"):
        raise UsageError("aspect must be one of 9:16, 16:9, 1:1, 4:5")
    root = os.path.abspath(folder)
    if is_project(root):
        raise UsageError("%s already holds a Bizzbell project (see: bb status)" % root)
    os.makedirs(root, exist_ok=True)
    for d in DIRS:
        os.makedirs(path(root, d), exist_ok=True)
    tpl_path = os.path.join(util.ROOT_DIR, "templates", "brief.md")
    tpl = util.read_text(tpl_path) or BRIEF_TEMPLATE
    try:
        text = tpl.format(brief=brief.strip(), lang=lang, aspect=aspect)
    except (KeyError, IndexError, ValueError):
        text = BRIEF_TEMPLATE.format(brief=brief.strip(), lang=lang, aspect=aspect)
    util.write_text(path(root, "brief.md"), text)
    settings = util.deep_merge(DEFAULT_SETTINGS, {})
    save_settings(root, settings)
    state = {
        "bizzbell": 1, "slug": slug or slugify(brief), "created": util.now(), "lang": lang, "aspect": aspect,
        "brief": brief.strip(), "stage": "brief", "status": "in_progress",
        "stages": {s["id"]: {"status": "todo", "gate_runs": 0, "restructure_rounds": 0} for s in STAGES},
        "scores": {}, "spend": {"cap_inr": 0, "spent_inr": 0.0, "reserved_inr": 0.0},
    }
    util.write_json(path(root, "project.json"), state)
    refresh(root)
    return root


def outputs_present(root, stage_id):
    """True when every output glob of the stage matches at least one file and, for a media stage with items
    (characters, keyframes), every item the screenplay asks for is in place."""
    if not all(glob.glob(path(root, g)) for g in stage(stage_id)["outputs"]):
        return False
    if stage_id in ("characters", "keyframes"):
        from .media import layers
        return layers.items_present(root, stage_id)
    return True


def stage_status(root, stage_id, state=None, settings=None):
    """Effective status: the recorded one, upgraded todo -> made when the outputs exist (brief also needs a budget),
    and passed -> changed when a file the gate scored was changed or removed since (gate it again)."""
    state = state if state is not None else load_state(root)
    rec = (state.get("stages") or {}).get(stage_id, {})
    st = rec.get("status", "todo")
    if st == "todo" and outputs_present(root, stage_id):
        st = "made"
    if st == "passed" and _changed(root, stage_id, state):
        st = "changed"
    if stage_id == "brief" and st == "made":
        settings = settings or load_settings(root)
        if settings.get("budget", {}).get("approved") and settings["budget"].get("cap_inr", 0) > 0:
            st = "passed"
    return st


def done(stage_id, status):
    """True when a stage needs no more work (brief needs the approved budget; gated stages need a pass)."""
    if status in ("passed", "skipped"):
        return True
    if stage_id == "brief":
        return False
    return status == "made" and not stage(stage_id)["gated"]


def require_done(root, stage_id):
    """Raise OutOfOrder unless every layer `stage_id` builds on is done (spec: a later layer is made and judged
    against passed earlier ones). Called before a paid stage spends; dry runs skip it."""
    state, settings = load_state(root), load_settings(root)
    open_ = [(s, stage_status(root, s, state, settings)) for s in REQUIRES.get(stage_id, ())]
    open_ = [(s, st) for s, st in open_ if not done(s, st)]
    if open_:
        raise OutOfOrder(
            "%s builds on layers that have not passed their gate: %s. Nothing was sent. Gate them first "
            "(python3 scripts/bb.py gate <layer>, restructure on a fail), or, if the user accepts one as it is, "
            "python3 scripts/bb.py mark <layer> passed --note \"accepted by the user\"."
            % (stage_id, ", ".join("%s (%s)" % x for x in open_)))


def next_stage(root):
    """Id of the first stage that is not done, or None when everything is done."""
    state, settings = load_state(root), load_settings(root)
    for s in STAGES:
        if not done(s["id"], stage_status(root, s["id"], state, settings)):
            return s["id"]
    return None


def refresh(root):
    """Recompute project.json "stage" (next to do) and "status"."""
    nxt = next_stage(root)

    def f(st):
        st["stage"] = nxt or "final"
        st["status"] = "done" if nxt is None else "in_progress"
    update_state(root, f)
    return nxt


NEXT_HINT = {
    "brief": "agree a budget with the user, then: bb budget set <inr>",
    "research": "write research.md (sources with URL + date read), then: bb gate research",
    "story": "write story.md (2-3 directions, one chosen), then: bb gate story",
    "humanize": "write story_humanized.md, then: bb gate humanize",
    "screenplay": "write screenplay.md + screenplay.json (one row per second), then: bb gate screenplay",
    "characters": "write characters/bible.md, then: bb characters make; bb gate characters",
    "keyframes": "bb keyframes make, then: bb gate keyframes",
    "audio": "bb voice audition; bb voice takes; bb voice place; bb music make; bb mix build; "
             "then: bb gate voice; bb gate music; bb gate mix",
    "video_a": "bb clips make; bb gate clips; bb version_a build; bb gate version_a "
               "(or bb mark video_a skipped --note ... if /v1/videos is not live)",
    "video_b": "bb version_b, then: bb gate video_b",
    "final": "bb final (every size, share copies, the final gate of each version, out/report.md)",
}


def status_report(root):
    """Dict for `bb status`: per-stage rows, next stage + hint, scores, spend."""
    state, settings = load_state(root), load_settings(root)
    rows = []
    for s in STAGES:
        rec = (state.get("stages") or {}).get(s["id"], {})
        rows.append({"id": s["id"], "n": s["n"], "title": s["title"],
                     "status": stage_status(root, s["id"], state, settings),
                     "score": (state.get("scores") or {}).get(s["id"]),
                     "gate_runs": rec.get("gate_runs", 0), "rounds": rec.get("restructure_rounds", 0),
                     "note": rec.get("note", "")})
    nxt = next_stage(root)
    from . import ledger as ledger_mod
    spend = ledger_mod.Ledger(root).summary()
    return {"project": root, "slug": state.get("slug"), "lang": state.get("lang"), "aspect": state.get("aspect"),
            "stages": rows, "next": nxt, "hint": NEXT_HINT.get(nxt, "all stages done"), "spend": spend}
