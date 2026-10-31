"""The per-take judge: the stage's own rubric questions, asked about ONE item (a sheet, a keyframe, a take).

judge_item() loads rubrics/<rubric_id>.json (project override first), keeps the questions a model answers
(questions with a local "check" are for the whole-layer gate; questions marked "scope": "layer" too), attaches the
item's files, and asks /v1/media/judge through the ledger. It returns None when there is no rubric, no
item-level question, or the media judge is not live (the take is then kept on its local checks alone).

Result: {"score", "passed", "hard_failed", "failed": [{"id", "text", "evidence"}], "answers": [per pass],
         "voice_free": True|False|None}"""
import copy
import os

from .. import gate, hidrogen, ledger as ledger_mod, project
from ..errors import UsageError


def item_questions(rubric):
    return [q for q in rubric.get("questions", []) if not q.get("check") and q.get("scope", "item") != "layer"]


def load(root, rubric_id):
    try:
        return gate.load_rubric(root, rubric_id)
    except UsageError:
        return None


def voice_free_ids(questions):
    """Ids of the questions that ask whether music is free of vocals ("voice_free": true, or by wording)."""
    flagged = [q["id"] for q in questions if q.get("voice_free")]
    if flagged:
        return flagged
    words = ("vocal", "voice-free", "voice free", "no voice", "singing", "sung", "lyrics")
    return [q["id"] for q in questions if any(w in q["text"].lower() for w in words)]


def judge_item(root, rubric_id, files, notes, purpose, passes=1):
    """Judge one item. files: absolute paths (the item first, then its references). See the module docstring."""
    rubric = load(root, rubric_id)
    if rubric is None:
        return None
    qs = item_questions(rubric)
    if not qs:
        return None
    r = copy.deepcopy(rubric)
    r["layer"] = {"kind": "media", "files": [os.path.relpath(f, root) for f in files], "max_files": len(files)}
    r["judge_notes"] = ("%s\n%s" % (rubric.get("judge_notes", ""), notes)).strip()
    r["questions"] = qs
    ctx = gate.GateContext(root, rubric_id, r)
    ctx.stage = "%s %s" % (rubric_id, purpose)
    led = ledger_mod.Ledger(root)
    answers = []
    try:
        for i in range(max(1, passes)):
            ans, _c = gate._ask_judge(ctx, qs, None, led, i + 1)
            answers.append(ans)
    except hidrogen.NotAvailable:
        return None
    values = gate.combine(qs, answers)
    sc = gate.score(qs, values)
    gcfg = project.load_settings(root).get("gate", {})
    ps = float(rubric.get("pass_score", gcfg.get("pass_score", 95)))
    hard = [q["id"] for q in qs if q.get("hard") and values[q["id"]] == 0.0]
    failed = [{"id": q["id"], "text": q["text"], "evidence": answers[-1][q["id"]]["evidence"]}
              for q in qs if values[q["id"]] < 1.0]
    vf_ids = voice_free_ids(qs) if rubric_id == "music" else []
    voice_free = None
    if vf_ids:
        voice_free = all(a[q]["answer"] == "yes" for a in answers for q in vf_ids)
    return {"score": sc, "passed": sc >= ps and not hard, "pass_score": ps, "hard_failed": hard, "failed": failed,
            "answers": answers, "voice_free": voice_free}


def fix_from(result, limit=4):
    """Correction text for the next take, from a failed judge result (no extra model call)."""
    if not result or not result.get("failed"):
        return ""
    bits = []
    for f in result["failed"][:limit]:
        bits.append("%s (judge: %s)" % (f["text"].rstrip("?"), f["evidence"][:160]))
    return "Fix these: " + "; ".join(bits)
