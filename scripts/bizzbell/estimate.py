"""`bb budget estimate`: the cost of a whole film per stage, before the user is asked for a budget (permission
point 1). Nothing is paid: prices come from /v1/media/quote (free) where it answers, else from bizzbell.json
budget.rates_inr, and the output says which.

Counts come from screenplay.json when it exists, else from the film's length (--seconds): about one live shot per
2.5 s, one VO line per 4 s, two characters and two locations. "likely" is one take per item, two judge passes
per gate and typical reply lengths; "worst" is max_takes per item, three judge passes at max_tokens and every
restructure round used (re-making the items a media restructure changes is not included)."""
import math

from . import gate, ledger as ledger_mod, project, restructure
from .errors import BBError, ConfigError

JUDGE_CHARS = 20000        # a typical judge prompt: the layer, its references and the questions
RESTRUCTURE_CHARS = 30000
JUDGE_LIKELY_TOKENS = 2500        # a typical judge reply (the ledger reserves for max_tokens)


def counts(root, seconds=None):
    """{seconds, live, refs, lines, source} for the estimate."""
    from .media import screenplay
    if seconds is None:
        try:
            sp = screenplay.load(root)
            refs = len(sp.bibles["characters"]) + len(sp.bibles["locations"])
            return {"seconds": float(sp.duration), "live": len(sp.live_shots()), "refs": refs,
                    "lines": len(sp.lines), "source": "screenplay.json"}
        except (BBError, ValueError, KeyError, TypeError):
            seconds = 30.0
    seconds = float(seconds)
    return {"seconds": seconds, "live": int(math.ceil(seconds / 2.5)), "refs": 4,
            "lines": int(math.ceil(seconds / 4.0)), "source": "a %g s film (guessed counts)" % seconds}


class _Prices(object):
    """One price per kind of call, from the quote endpoint (cached) or the rates."""

    def __init__(self, root, quote=True):
        self.led = ledger_mod.Ledger(root)
        self.root = root
        self.quote = quote
        self.sources = set()
        self._cache = {}

    def _model(self, role):
        try:
            return project.model_for(self.root, role)
        except ConfigError:
            return None

    def price(self, kind, role=None, units=1, params=None):
        key = (kind, role, units, tuple(sorted((params or {}).items())))
        if key not in self._cache:
            inr, src = self.led.estimate(kind, self._model(role) if role else None, units, dict(params or {}),
                                         ask_quote=self.quote)
            self.sources.add(src)
            self._cache[key] = round(inr, 2)
        return self._cache[key]


def estimate(root, seconds=None, quote=True):
    """{"counts", "rows": [{stage, likely, worst, what}], "likely", "worst", "source"}."""
    from .media import clips, store
    c = counts(root, seconds)
    p = _Prices(root, quote)
    s = project.load_settings(root)
    passes = int(s.get("gate", {}).get("passes", 2))
    rounds = int(s.get("gate", {}).get("max_rounds", 3))
    takes = store.max_takes(root)
    ms = store.media_settings(root)
    judge_likely = p.price("chat", "judge", params={"max_tokens": JUDGE_LIKELY_TOKENS, "chars": JUDGE_CHARS})
    judge_chat = p.price("chat", "judge", params={"max_tokens": gate.JUDGE_MAX_TOKENS, "chars": JUDGE_CHARS})
    fix_worst = p.price("chat", "restructure", params={"max_tokens": restructure.MAX_TOKENS,
                                                       "chars": RESTRUCTURE_CHARS})
    media_judge = p.price("judge", None, params={"files": 4})
    image = p.price("image", "image", params={"count": 1, "size": ms["image_size"], "aspect_ratio": "9:16"})
    voice = p.price("voice", "voice", params={"chars": 80})
    secs = int(min(180, math.ceil(c["seconds"]) + 2))
    music = p.price("music", "music", params={"seconds": secs})
    clip_s = clips.plan_seconds(ms, 2.0)
    video = p.price("video", "video", units=clip_s, params={"seconds": clip_s, "resolution": ms["resolution"],
                                                             "aspect_ratio": "9:16"})

    def text_gate():
        return passes * judge_likely, (1 + rounds) * 3 * judge_chat + rounds * fix_worst

    def media_gate():
        return passes * media_judge, (1 + rounds) * 3 * media_judge + rounds * fix_worst

    def items(n, unit):
        per = unit + passes * media_judge
        return n * per, n * takes * per

    rows = []

    def add(stage, what, *parts):
        rows.append({"stage": stage, "what": what, "likely": round(sum(x[0] for x in parts), 2),
                     "worst": round(sum(x[1] for x in parts), 2)})

    for st in ("research", "story", "humanize", "screenplay"):
        add(st, "text gate (judge passes; restructure rounds in the worst case)", text_gate())
    add("characters", "%d sheets/plates x image + per-take judge, gate" % c["refs"], items(c["refs"], image),
        media_gate())
    add("keyframes", "%d keyframes x image + per-take judge, gate" % c["live"], items(c["live"], image), media_gate())
    add("audio", "audition %d voices, %d VO lines, a %d s music bed, gates voice/music/mix"
        % (3, c["lines"], secs), items(3, voice), items(c["lines"], voice), items(1, music), media_gate(),
        media_gate(), media_gate())
    add("video_a", "%d clips x %d s video + per-take judge, gates clips/version_a (only if /v1/videos is live)"
        % (c["live"], clip_s), items(c["live"], video), media_gate(), media_gate())
    add("video_b", "HyperFrames renders locally (no video seconds), gate", media_gate())
    add("final", "final gate of each version", media_gate(), media_gate())
    src = "quote" if p.sources == {"quote"} else ("rates" if p.sources == {"rate"} else "quote where it answered, "
                                                                                       "else rates")
    return {"counts": c, "rows": rows, "likely": round(sum(r["likely"] for r in rows), 2),
            "worst": round(sum(r["worst"] for r in rows), 2), "source": src, "max_takes": takes}


def format_estimate(est):
    c = est["counts"]
    lines = ["Estimate for %s: %d live shots, %d characters+locations, %d VO lines (INR; prices from %s)"
             % (c["source"], c["live"], c["refs"], c["lines"], est["source"]),
             "  %-11s %9s %9s  %s" % ("stage", "likely", "worst", "what")]
    for r in est["rows"]:
        lines.append("  %-11s %9.2f %9.2f  %s" % (r["stage"], r["likely"], r["worst"], r["what"]))
    lines.append("  %-11s %9.2f %9.2f  (max_takes %d)" % ("total", est["likely"], est["worst"], est["max_takes"]))
    lines.append("Nothing was paid. Without Version A: subtract the video_a row. Show this to the user and ask for "
                 "a cap: python3 scripts/bb.py budget set <inr> --note \"...\"")
    return "\n".join(lines)
