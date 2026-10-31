"""Gating the media layers with the core gate engine, and rolling sub-layers up into their stage.

Rubric ids: characters, keyframes (the stage ids themselves), and the sub-layers voice, music, mix (stage audio)
and clips, version_a (stage video_a). The stage follows its sub-layers in project.json: passed when every one has
passed (or was skipped), failed as soon as one fails, and out of passed again when one is no longer passed. `bb gate <layer>` and `bb restructure <layer>` accept these ids too; `bb gate audio`
/ `bb gate video_a` still work when those rubrics exist."""
from .. import gate, project, restructure
from ..errors import UsageError

PARENT = project.LAYER_PARENT
PARTS = project.STAGE_PARTS
LAYERS = ("characters", "keyframes", "clips", "voice", "music", "mix", "version_a")


def version_a_rubric(root):
    """The rubric id that gates the whole Version A film: version_a when that rubric exists, else video_a."""
    try:
        gate.rubric_path(root, "version_a")
        return "version_a"
    except UsageError:
        return "video_a"


def run_gate(root, layer, passes=None):
    """gate.run() for one media layer, then the roll-up. Returns (record, rolled_up_stage_or_None)."""
    rec = gate.run(root, layer, passes=passes)
    return rec, rollup(root, layer)


def rollup(root, layer):
    if layer in ("final_a", "final_b"):
        return _rollup_final(root)
    parent = PARENT.get(layer)
    if not parent:
        return None
    stages = project.load_state(root).get("stages", {})
    if stages.get(parent, {}).get("status") == "skipped":
        return None
    status = {p: stages.get(p, {}).get("status") for p in PARTS[parent]}
    if all(v in ("passed", "skipped") for v in status.values()):
        project.mark_stage(root, parent, "passed", note="%s gates passed" % ", ".join(PARTS[parent]))
        return parent
    failed = [p for p in PARTS[parent] if status[p] == "failed"]
    if failed:
        project.mark_stage(root, parent, "failed", note="%s gate failed" % ", ".join(failed))
    elif stages.get(parent, {}).get("status") == "passed":
        waiting = [p for p in PARTS[parent] if status[p] not in ("passed", "skipped")]
        project.mark_stage(root, parent, "made", note="gate %s again" % ", ".join(waiting))
    return None


def _rollup_final(root):
    """Stage final follows the latest final_a / final_b gates of the versions that were made (bb gate final_a
    after a restructure). Returns "final" when it passed."""
    from .. import final
    versions = [v for v in final.VERSIONS if final.made(root, v)]
    recs = {v: gate.latest(root, final.gate_id(v)) for v in versions}
    if not versions or any(r is None for r in recs.values()):
        return None
    note = ", ".join("%s %.1f" % (v, r["score"]) for v, r in sorted(recs.items()))
    if all(r["passed"] for r in recs.values()):
        project.mark_stage(root, "final", "passed", note=note)
        return "final"
    project.mark_stage(root, "final", "failed", note=note)
    return None


def run_restructure(root, layer, extra=False, note=""):
    return restructure.run(root, layer, extra=extra, note=note)


def format_gate(root, rec, rolled):
    used, allowed = restructure.rounds(root, rec["stage"])
    text = gate.format_result(rec, max_rounds=allowed, rounds_used=used)
    if rolled:
        text += "\nstage %s: passed (all its layers passed)" % rolled
    return text
