"""Version B's deterministic gate checks (spec section 9), read from out/B/qa.json (made by `bb version_b check`).

  hf_text_fits          every text element inside the frame and the safe zone, in every size made
  hf_frames_repeatable  sampled frames render the same twice, the second time in shuffled order
A record counts only while it was made from the composition now on disk; otherwise the answer is no with the
command to run. No model call, no spend."""
from ..gate import check
from ..hf import formats, qa


def _ratios(ctx, data, ratios):
    if ratios:
        return [formats.name(r) for r in ratios]
    made = [r for r, rec in (data.get("ratios") or {}).items() if rec.get("video")]
    return [r for r in formats.ORDER if r in set(formats.REQUIRED) | set(made)]


def _stale(ctx, data, r):
    if r not in (data.get("ratios") or {}):
        return "%s: not checked (run: python3 scripts/bb.py version_b check)" % r
    if not qa.built_from_latest(ctx.root, r):
        return "%s: built from an older screenplay or brand (run: python3 scripts/bb.py version_b)" % r
    if not qa.fresh(ctx.root, r, data):
        return "%s: the check is older than the composition (run: python3 scripts/bb.py version_b check)" % r
    return ""


@check("hf_text_fits")
def hf_text_fits(ctx, ratios=None):
    """HyperFrames' layout check and the DOM safe-zone check found no cut-off or misplaced text."""
    data = qa.load(ctx.root)
    if not data.get("ratios"):
        return "no", "out/B/qa.json is missing: run python3 scripts/bb.py version_b check"
    bad, good = [], []
    for r in _ratios(ctx, data, ratios):
        why = _stale(ctx, data, r)
        if why:
            bad.append(why)
            continue
        rec = data["ratios"][r]
        if rec.get("text_ok"):
            good.append("%s (%d boxes)" % (r, (rec.get("bounds") or {}).get("checked", 0)))
            continue
        issues = [("%s %s at %ss" % (i.get("code"), i.get("el"), i.get("t")))
                  for i in (rec.get("bounds") or {}).get("issues", [])[:3]]
        issues += [("%s %s" % (i.get("code"), i.get("selector")))
                   for i in (rec.get("hf_check") or {}).get("text", [])[:3]]
        issues += [("%s %s" % (i.get("code"), i.get("selector")))
                   for i in (rec.get("hf_check") or {}).get("errors", [])[:2]]
        if (rec.get("hf_check") or {}).get("browser_skipped"):
            issues.append("hyperframes check could not open its browser")
        bad.append("%s: %s" % (r, "; ".join(issues) or "failed"))
    if bad:
        return "no", " | ".join(bad)[:900]
    return "yes", "text inside the frame and the safe zone: " + ", ".join(good)


@check("hf_frames_repeatable")
def hf_frames_repeatable(ctx, ratios=None):
    """Every sampled frame was identical (or within the pixel threshold) when rendered again in shuffled order."""
    data = qa.load(ctx.root)
    if not data.get("ratios"):
        return "no", "out/B/qa.json is missing: run python3 scripts/bb.py version_b check"
    bad, good = [], []
    for r in _ratios(ctx, data, ratios):
        why = _stale(ctx, data, r)
        if why:
            bad.append(why)
            continue
        rep = data["ratios"][r].get("repeat")
        if not rep:
            bad.append("%s: repeatability not checked (run bb version_b check without --no-repeat)" % r)
        elif rep.get("ok"):
            good.append("%s (%d frames)" % (r, len(rep.get("times", []))))
        else:
            bad.append("%s: frames differ at %s s" % (r, ", ".join("%g" % t for t in rep.get("differing", []))))
    if bad:
        return "no", " | ".join(bad)[:900]
    return "yes", "repeatable: " + ", ".join(good)
