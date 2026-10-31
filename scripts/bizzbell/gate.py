"""The gate engine (spec section 6): score one layer with weighted yes/partly/no questions against its reference.

Flow of run(root, stage):
  1. load the rubric (<project>/rubrics/<stage>.json overrides <skill>/rubrics/<stage>.json) and validate it;
  2. answer every question that has a "check" with a registered local Python check (no model call);
  3. ask the judge model the rest - text layers via hidrogen.chat(), media layers via hidrogen.media_judge() -
     as strict JSON {answers: [{id, answer, evidence}]}; invalid replies are re-asked (max 2 more times);
  4. two passes; a third when they differ by more than `disagree_points` or disagree on a hard question;
  5. per question the final value is the mean of 2 passes / the median of 3 (yes 1, partly 0.5, no 0);
     score = weighted %; a hard question whose final value is 0 fails the gate whatever the score;
  6. passed = score >= pass_score (95) and no hard fail; saved to gates/<stage>.<n>.json; project.json updated.

Rubric schema: see docs/extending.md and validate_rubric(). Every question is phrased so "yes" is good.
Text layers: a "yes" whose quoted evidence is not found in the layer or its references is downgraded to
"partly" (questions with "quote": false are exempt), so a judge cannot pass a layer on a vibe."""
import glob
import hashlib
import importlib
import json
import os
import pkgutil
import re

from . import hidrogen, ledger as ledger_mod, project, util
from .errors import BBError, ConfigError, UsageError

ANSWERS = {"yes": 1.0, "partly": 0.5, "no": 0.0}
MAX_TEXT_CHARS = 200000
MAX_FILES_DEFAULT = 8

# ---------------------------------------------------------------- local checks registry
_CHECKS = {}
_LOADED = [False]


def check(name):
    """Decorator: register a local check under `name` (used by a rubric question's "check" field).

    The function is called as fn(ctx, **question.get("args", {})) and returns ("yes"|"partly"|"no", evidence)
    or a bool (True = yes) or a dict {"answer", "evidence"}."""
    def deco(fn):
        _CHECKS[name] = fn
        return fn
    return deco


def load_checks():
    """Import every module in bizzbell/checks/ once, so their @check functions register."""
    if _LOADED[0]:
        return _CHECKS
    _LOADED[0] = True
    from . import checks as pkg
    for m in pkgutil.iter_modules(pkg.__path__):
        if not m.name.startswith("_"):
            importlib.import_module("%s.%s" % (pkg.__name__, m.name))
    return _CHECKS


def registered_checks():
    return dict(load_checks())


# ---------------------------------------------------------------- rubric
def rubric_path(root, stage_id):
    """Project override first, then the skill's rubrics/ folder. Raises UsageError if neither exists."""
    for p in (os.path.join(root, "rubrics", stage_id + ".json") if root else None,
              os.path.join(util.ROOT_DIR, "rubrics", stage_id + ".json")):
        if p and os.path.exists(p):
            return p
    raise UsageError("no rubric for stage %r (looked in the project's rubrics/ and the skill's rubrics/)" % stage_id)


def load_rubric(root, stage_id):
    """The validated rubric dict for a stage."""
    p = rubric_path(root, stage_id)
    try:
        r = util.read_json(p)
    except ValueError as e:
        raise ConfigError("%s is not valid JSON: %s" % (p, e))
    validate_rubric(r, where=p)
    return r


def validate_rubric(r, where="rubric"):
    """Raise ConfigError if `r` does not follow the rubric schema. Returns r."""
    def bad(msg):
        raise ConfigError("%s: %s" % (where, msg))
    if not isinstance(r, dict):
        bad("must be a JSON object")
    for k in ("stage", "layer", "questions"):
        if k not in r:
            bad("missing %r" % k)
    layer = r["layer"]
    if not isinstance(layer, dict) or layer.get("kind") not in ("text", "media"):
        bad('layer.kind must be "text" or "media"')
    if not isinstance(layer.get("files"), list) or not layer["files"]:
        bad("layer.files must be a non-empty list of paths/globs")
    if not isinstance(r.get("references", []), list):
        bad("references must be a list of paths/globs")
    ps = r.get("pass_score", 95)
    if not isinstance(ps, (int, float)) or not 0 < ps <= 100:
        bad("pass_score must be a number in (0, 100]")
    qs = r["questions"]
    if not isinstance(qs, list) or not qs:
        bad("questions must be a non-empty list")
    seen = set()
    for q in qs:
        if not isinstance(q, dict):
            bad("every question must be an object")
        qid = q.get("id")
        if not isinstance(qid, str) or not re.match(r"^[A-Za-z0-9_.\-]+$", qid):
            bad("question id %r must be a short string of letters/digits/_.-" % (qid,))
        if qid in seen:
            bad("duplicate question id %r" % qid)
        seen.add(qid)
        if not isinstance(q.get("text"), str) or not q["text"].strip():
            bad("question %s needs text" % qid)
        w = q.get("weight", 1)
        if not isinstance(w, (int, float)) or isinstance(w, bool) or w <= 0:
            bad("question %s weight must be a positive number" % qid)
        if not isinstance(q.get("hard", False), bool):
            bad("question %s hard must be true/false" % qid)
        if "check" in q and not isinstance(q["check"], str):
            bad("question %s check must be a check name" % qid)
        if "args" in q and not isinstance(q["args"], dict):
            bad("question %s args must be an object" % qid)
    rs = r.get("restructure", {})
    if rs and not isinstance(rs.get("targets", []), list):
        bad("restructure.targets must be a list of file paths")
    return r


# ---------------------------------------------------------------- context
def _expand(root, patterns):
    out = []
    for p in patterns:
        hits = sorted(glob.glob(os.path.join(root, p)))
        for h in hits:
            if os.path.isfile(h) and h not in out:
                out.append(h)
    return out


def _is_textfile(p):
    return os.path.splitext(p)[1].lower() in (".md", ".txt", ".json", ".srt", ".vtt", ".csv", ".html", ".yaml",
                                              ".yml")


class GateContext(object):
    """What a local check (and the judge prompt) sees.

    root, stage, rubric, settings, state; layer_files / reference_files (absolute paths);
    layer_text / references (dict relative path -> text, text files only); rel(path)."""

    def __init__(self, root, stage_id, rubric):
        self.root = root
        self.stage = stage_id
        self.rubric = rubric
        self.settings = project.load_settings(root)
        self.state = project.load_state(root)
        self.layer_files = _expand(root, rubric["layer"]["files"])
        self.reference_files = _expand(root, rubric.get("references", []))
        self.layer = {self.rel(p): util.read_text(p) for p in self.layer_files if _is_textfile(p)}
        self.references = {self.rel(p): util.read_text(p) for p in self.reference_files if _is_textfile(p)}
        self.layer_text = "\n\n".join("=== %s ===\n%s" % (k, v) for k, v in self.layer.items())

    def rel(self, p):
        return os.path.relpath(p, self.root)

    def read(self, rel_path):
        return util.read_text(os.path.join(self.root, rel_path))

    def json(self, rel_path, default=None):
        try:
            return util.read_json(os.path.join(self.root, rel_path), default)
        except ValueError:
            return default


def layer_hash(ctx):
    h = hashlib.sha256()
    for p in ctx.layer_files:
        h.update(ctx.rel(p).encode())
        with open(p, "rb") as f:
            h.update(hashlib.sha256(f.read()).digest())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------- answers
def _norm_answer(a):
    a = str(a or "").strip().lower()
    return {"y": "yes", "true": "yes", "n": "no", "false": "no", "partial": "partly", "partially": "partly"}.get(a, a)


def _run_check(ctx, q):
    fn = load_checks().get(q["check"])
    if fn is None:
        return {"id": q["id"], "answer": "no", "evidence": "local check %r is not registered" % q["check"],
                "source": "check"}
    try:
        res = fn(ctx, **q.get("args", {}))
    except Exception as e:      # a broken check must not crash the gate; it answers no with the reason
        return {"id": q["id"], "answer": "no", "evidence": "check %s failed: %s" % (q["check"], hidrogen.redact(e)),
                "source": "check"}
    if isinstance(res, bool):
        ans, ev = ("yes" if res else "no"), ""
    elif isinstance(res, dict):
        ans, ev = res.get("answer"), res.get("evidence", "")
    else:
        ans, ev = res[0], (res[1] if len(res) > 1 else "")
    ans = _norm_answer(ans)
    if ans not in ANSWERS:
        ans, ev = "no", "check %s returned an invalid answer %r" % (q["check"], ans)
    return {"id": q["id"], "answer": ans, "evidence": str(ev)[:1000], "source": "check"}


def validate_answers(obj, questions):
    """Parsed judge reply -> {id: {answer, evidence}}. Raises ValueError naming what is wrong."""
    if isinstance(obj, dict):
        items = obj.get("answers")
    else:
        items = obj
    if not isinstance(items, list):
        raise ValueError('the reply must be {"answers": [...]}')
    want = [q["id"] for q in questions]
    out = {}
    for it in items:
        if not isinstance(it, dict):
            raise ValueError("every answer must be an object")
        qid = str(it.get("id", ""))
        if qid not in want:
            raise ValueError("unknown question id %r" % qid)
        if qid in out:
            raise ValueError("question %s answered twice" % qid)
        ans = _norm_answer(it.get("answer"))
        if ans not in ANSWERS:
            raise ValueError("question %s: answer must be yes, partly or no" % qid)
        ev = it.get("evidence")
        if not isinstance(ev, str) or not ev.strip():
            raise ValueError("question %s: evidence (a quote from the layer, or what is missing) is required" % qid)
        out[qid] = {"answer": ans, "evidence": ev.strip()[:1500]}
    missing = [q for q in want if q not in out]
    if missing:
        raise ValueError("questions not answered: %s" % ", ".join(missing))
    return out


def _norm_text(s):
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def evidence_found(evidence, haystack):
    """True when the quoted part(s) of `evidence` appear in `haystack` (case/whitespace-insensitive).

    Quoted spans ("..." or '...') are checked if present, else the whole evidence; '...' splits fragments;
    fragments shorter than 6 characters are ignored."""
    hay = _norm_text(haystack)
    spans = re.findall(r'"([^"]{6,})"', evidence) or re.findall(r"“([^”]{6,})”", evidence) \
        or [evidence]
    for span in spans:
        frags = [f.strip(" .,:;'\"") for f in re.split(r"\.\.\.|…", span)]
        frags = [f for f in frags if len(f) >= 6]
        if frags and all(_norm_text(f) in hay for f in frags):
            return True
    return False


# ---------------------------------------------------------------- judge prompts
JUDGE_SYSTEM = (
    "You are a strict quality judge for one layer of a short-video project. Answer EVERY question with "
    "\"yes\", \"partly\" or \"no\". Each question is phrased so that yes is good. Say yes only when the layer "
    "fully meets it. For every answer give evidence: quote the exact words from the LAYER (verbatim, in double "
    "quotes) that prove it, or for partly/no say precisely what is missing or wrong, quoting the closest text. "
    "Judge only against the layer and its references; do not reward intent. Reply with JSON only, no prose: "
    "{\"answers\": [{\"id\": \"<question id>\", \"answer\": \"yes|partly|no\", \"evidence\": \"...\"}]}")


def _questions_block(questions):
    rows = [{"id": q["id"], "question": q["text"], "evidence_hint": q.get("evidence", ""),
             "hard": bool(q.get("hard"))} for q in questions]
    return "<questions>\n%s\n</questions>" % json.dumps(rows, ensure_ascii=False, indent=1)


def build_judge_prompt(ctx, questions):
    """The user message for the judge (text and media layers)."""
    parts = ["Stage: %s (%s)" % (ctx.stage, ctx.rubric.get("title", ctx.stage))]
    if ctx.rubric.get("judge_notes"):
        parts.append("Notes for the judge: %s" % ctx.rubric["judge_notes"])
    for name, text in ctx.references.items():
        parts.append('<reference name="%s">\n%s\n</reference>' % (name, text[:MAX_TEXT_CHARS]))
    if ctx.rubric["layer"]["kind"] == "text":
        parts.append("<layer>\n%s\n</layer>" % ctx.layer_text[:MAX_TEXT_CHARS])
    else:
        names = [ctx.rel(p) for p in _media_files(ctx)]
        parts.append("<layer>\nThe attached media files, in order: %s\n%s\n</layer>"
                     % (", ".join(names), ctx.layer_text[:MAX_TEXT_CHARS]))
    parts.append(_questions_block(questions))
    parts.append('Answer all %d questions. JSON only: {"answers": [...]}' % len(questions))
    return "\n\n".join(parts)


def _media_files(ctx):
    n = int(ctx.rubric["layer"].get("max_files", MAX_FILES_DEFAULT))
    return [p for p in ctx.layer_files if os.path.splitext(p)[1].lower() in hidrogen.MIME][:n]


def _ask_judge(ctx, questions, model, led, pass_no):
    """One judge pass over the model questions -> ({id: answer}, cost_note). Re-asks up to 2x on bad JSON."""
    prompt = build_judge_prompt(ctx, questions)
    media = ctx.rubric["layer"]["kind"] == "media"
    err = ""
    for attempt in range(3):
        msg = prompt if not err else prompt + "\n\nYour previous reply was rejected: %s. Reply again, JSON only." % err
        if media:
            files = _media_files(ctx)
            reply = led.call("judge", lambda: hidrogen.media_judge(msg, files, system_prompt=JUDGE_SYSTEM,
                                                                   temperature=0.2),
                             model=model or "media-judge", purpose="gate %s pass %d" % (ctx.stage, pass_no),
                             quote_params={"files": len(files)})
            obj = reply.get("result")
            if obj is None:
                try:
                    obj = hidrogen.parse_json_text(reply.get("text", ""))
                except ValueError:
                    obj = None
        else:
            reply = led.call("chat", lambda: hidrogen.chat(msg, model, system_prompt=JUDGE_SYSTEM, temperature=0.2,
                                                           max_tokens=8192, json_mode=True),
                             model=model, purpose="gate %s pass %d" % (ctx.stage, pass_no))
            try:
                obj = hidrogen.parse_json_text(reply["text"])
            except ValueError:
                obj = None
        if obj is None:
            err = "it was not valid JSON"
            continue
        try:
            return validate_answers(obj, questions), reply.get("charged_inr")
        except ValueError as e:
            err = str(e)
    raise BBError("the judge did not return valid answers after 3 tries (%s). Run the gate again; if it keeps "
                  "failing, set another judge model with BB_JUDGE_MODEL." % err)


def _verify(ctx, questions, answers):
    """Downgrade a text-layer "yes" whose quote is not in the layer/references to "partly"."""
    if ctx.rubric["layer"]["kind"] != "text" or ctx.rubric.get("verify_evidence", True) is False:
        return answers
    hay = ctx.layer_text + "\n" + "\n".join(ctx.references.values())
    for q in questions:
        a = answers[q["id"]]
        if a["answer"] == "yes" and q.get("quote", True) and not evidence_found(a["evidence"], hay):
            a["answer"] = "partly"
            a["note"] = "downgraded from yes: the quoted evidence is not in the layer"
    return answers


# ---------------------------------------------------------------- scoring
def score(questions, values):
    """Weighted % (0-100, one decimal) from {id: value 0..1}."""
    tw = sum(float(q.get("weight", 1)) for q in questions)
    got = sum(float(q.get("weight", 1)) * values[q["id"]] for q in questions)
    return round(100.0 * got / tw, 1) if tw else 0.0


def _median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def combine(questions, passes):
    """Final {id: value} from 2 passes (mean) or 3+ passes (median per question)."""
    out = {}
    for q in questions:
        vals = [ANSWERS[p[q["id"]]["answer"]] for p in passes]
        out[q["id"]] = sum(vals) / len(vals) if len(vals) <= 2 else _median(vals)
    return out


def _needs_tiebreak(questions, p1, p2, points):
    if abs(score(questions, {k: ANSWERS[v["answer"]] for k, v in p1.items()}) -
           score(questions, {k: ANSWERS[v["answer"]] for k, v in p2.items()})) > points:
        return True
    for q in questions:
        if q.get("hard") and (p1[q["id"]]["answer"] == "no") != (p2[q["id"]]["answer"] == "no"):
            return True
    return False


# ---------------------------------------------------------------- run
def next_run_number(root, stage_id):
    n = 0
    for p in glob.glob(os.path.join(root, "gates", "%s.*.json" % stage_id)):
        m = re.match(r"^%s\.(\d+)\.json$" % re.escape(stage_id), os.path.basename(p))
        if m:
            n = max(n, int(m.group(1)))
    return n + 1


def latest(root, stage_id):
    """The latest saved gate record of a stage, or None."""
    n = next_run_number(root, stage_id) - 1
    if n < 1:
        return None
    return util.read_json(os.path.join(root, "gates", "%s.%d.json" % (stage_id, n)))


def run(root, stage_id, passes=None):
    """Gate one layer. Returns the saved record (see module docstring). Raises UsageError if the layer is missing."""
    rubric = load_rubric(root, stage_id)
    settings = project.load_settings(root)
    gcfg = settings.get("gate", {})
    pass_score = float(rubric.get("pass_score", gcfg.get("pass_score", 95)))
    n_passes = int(passes or gcfg.get("passes", 2))
    points = float(gcfg.get("disagree_points", 10))
    ctx = GateContext(root, stage_id, rubric)
    if not ctx.layer_files:
        raise UsageError("nothing to gate for %s: none of %s exists yet" % (stage_id, ", ".join(rubric["layer"]["files"])))
    questions = rubric["questions"]
    local_qs = [q for q in questions if q.get("check")]
    model_qs = [q for q in questions if not q.get("check")]
    local = {q["id"]: _run_check(ctx, q) for q in local_qs}

    led = ledger_mod.Ledger(root)
    judge_model = None
    if model_qs and rubric["layer"]["kind"] == "text":
        judge_model = project.model_for(root, "judge")
    passes_out = []
    spent_before = led.summary()["spent_inr"]
    if model_qs:
        for i in range(max(1, n_passes)):
            ans, _c = _ask_judge(ctx, model_qs, judge_model, led, i + 1)
            passes_out.append(_verify(ctx, model_qs, ans))
        if len(passes_out) == 2 and _needs_tiebreak(model_qs, passes_out[0], passes_out[1], points):
            ans, _c = _ask_judge(ctx, model_qs, judge_model, led, 3)
            passes_out.append(_verify(ctx, model_qs, ans))
    full_passes = [dict(local, **p) for p in passes_out] or [local]
    values = combine(questions, full_passes)
    total = score(questions, values)
    hard_failed = [q["id"] for q in questions if q.get("hard") and values[q["id"]] == 0.0]
    passed = total >= pass_score and not hard_failed
    n = next_run_number(root, stage_id)
    rows = []
    for q in questions:
        per = [p[q["id"]] for p in full_passes]
        rows.append({"id": q["id"], "text": q["text"], "weight": q.get("weight", 1), "hard": bool(q.get("hard")),
                     "source": "check" if q.get("check") else "judge", "value": values[q["id"]],
                     "answers": [a["answer"] for a in per], "evidence": [a["evidence"] for a in per],
                     "notes": [a["note"] for a in per if a.get("note")]})
    record = {
        "stage": stage_id, "run": n, "time": util.now(), "rubric": os.path.relpath(rubric_path(root, stage_id), root)
        if rubric_path(root, stage_id).startswith(root) else "skill:rubrics/%s.json" % stage_id,
        "layer_files": [ctx.rel(p) for p in ctx.layer_files], "layer_hash": layer_hash(ctx),
        "model": judge_model or ("media-judge" if model_qs else "local"), "passes": len(passes_out),
        "pass_scores": [score(questions, {k: ANSWERS[v["answer"]] for k, v in p.items()}) for p in full_passes],
        "score": total, "pass_score": pass_score, "hard_failed": hard_failed, "passed": passed,
        "cost_inr": round(led.summary()["spent_inr"] - spent_before, 2), "questions": rows,
    }
    util.write_json(os.path.join(root, "gates", "%s.%d.json" % (stage_id, n)), record)
    _record_in_project(root, stage_id, record)
    return record


def _record_in_project(root, stage_id, rec):
    def f(st):
        s = st.setdefault("stages", {}).setdefault(stage_id, {})
        s["status"] = "passed" if rec["passed"] else "failed"
        s["gate_runs"] = s.get("gate_runs", 0) + 1
        s["last_gate"] = rec["run"]
        s.setdefault("history", []).append({"gate": rec["run"], "score": rec["score"], "passed": rec["passed"],
                                            "time": rec["time"]})
        st.setdefault("scores", {})[stage_id] = rec["score"]
    project.update_state(root, f)
    project.refresh(root)


def failed_questions(record):
    """Rows of a gate record that did not fully pass (value < 1), hard ones first."""
    rows = [q for q in record["questions"] if q["value"] < 1.0]
    return sorted(rows, key=lambda q: (not q["hard"], q["value"]))


def format_result(record, max_rounds=3, rounds_used=0):
    """Short readable text for `bb gate`."""
    verdict = "PASS" if record["passed"] else "FAIL"
    lines = ["gate %s #%d: %.1f / %g  %s  (passes %s; judge %s; INR %.2f)"
             % (record["stage"], record["run"], record["score"], record["pass_score"], verdict,
                ", ".join("%.1f" % s for s in record["pass_scores"]), record["model"], record["cost_inr"])]
    if record["hard_failed"]:
        lines.append("  hard fail: %s" % ", ".join(record["hard_failed"]))
    for q in failed_questions(record)[:8]:
        ev = q["evidence"][-1] if q["evidence"] else ""
        lines.append("  %s %s %s: %s  -- %s" % ("!" if q["hard"] else "-", q["id"], "/".join(q["answers"]),
                                               q["text"][:80], ev[:140].replace("\n", " ")))
    if not record["passed"]:
        if rounds_used < max_rounds:
            lines.append("next: python3 scripts/bb.py restructure %s  (round %d of %d)"
                         % (record["stage"], rounds_used + 1, max_rounds))
        else:
            lines.append("restructure rounds used up (%d): show the user the score and the failing questions, "
                         "and ask: accept, edit by hand, or allow one more round." % max_rounds)
    return "\n".join(lines)
