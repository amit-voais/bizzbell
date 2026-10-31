"""The take loop every media item goes through (sheets, keyframes, clips, VO lines, the music bed):

  generate take n -> local checks (ffmpeg, free) -> per-take judge (paid, optional) -> accept, or reject and retry
  with a correction built from what failed, until max_takes (bizzbell.json budget.max_takes) is used up.

A blocked call (safety filter, charged 0) stops the item: the agent rephrases the prompt as visible behaviour and
runs it once more. When no take passes, the best-scoring take that passed its local checks is put in place and
the item is marked "flagged", so the layer gate shows it and the agent asks the user."""
import os
import shutil

from .. import hidrogen, util
from . import judging, store


def run_item(root, d, iid, generate, check_local, judge, install, prompt_hash="", extra=0, fix="", log=print,
             source="hidrogen"):
    """Run takes for one item until one is accepted or the takes are used up. Returns the item record.

    generate(n, fix) -> relative path of the new take; check_local(rel) -> (ok, notes);
    judge(rel) -> judging result or None; install(rel) -> relative path of the installed file."""
    reg = store.load_registry(root, d)
    it = store.item(reg, iid)
    used = store.takes_used(it, prompt_hash or None)
    allowed = store.max_takes(root) + int(extra or 0)
    n_next = len(it.get("takes", [])) + 1
    best = None
    if used >= allowed:
        log("  %s: all %d takes used (status %s). Ask the user before another take (--extra-take)."
            % (iid, allowed, it.get("status")))
        return it
    while used < allowed:
        n = n_next
        n_next += 1
        try:
            take = generate(n, fix)
        except hidrogen.Blocked as e:
            _save_take(root, d, iid, {"n": n, "file": None, "status": "blocked", "note": hidrogen.redact(e)[:300],
                                      "ph": prompt_hash},
                       status="blocked", note="blocked by the safety filter (charged 0): rephrase %s/prompts.json "
                       "[%s] as plain visible behaviour and run it once more" % (d, iid))
            log("  %s take %d: BLOCKED by the safety filter (charged 0). Rephrase the prompt in %s/prompts.json as "
                "visible behaviour, then run it once more." % (iid, n, d))
            return store.load_registry(root, d)["items"][iid]
        used += 1
        ok, notes = check_local(take)
        rec = {"n": n, "file": take, "local": notes, "time": util.now(), "ph": prompt_hash}
        if not ok:
            rec["status"] = "rejected"
            rec["file"] = store.move_to(root, take, os.path.join(d, "_rejected")) or take
            _save_take(root, d, iid, rec)
            log("  %s take %d: rejected by the local checks: %s" % (iid, n, notes))
            fix = "Fix these: %s" % notes
            continue
        res = judge(take) if judge else None
        if res is not None:
            rec["score"] = res["score"]
            rec["failed"] = [f["id"] for f in res["failed"]]
            if res.get("voice_free") is not None:
                rec["voice_free"] = res["voice_free"]
            if res.get("voice_free") is False:
                res["passed"] = False
                rec["note"] = "the music judge heard a voice in at least one pass"
        if res is None or res["passed"]:
            final = install(take)
            rec["status"] = "accepted"
            rec["installed"] = final
            _save_take(root, d, iid, rec, status="accepted", file=final, take=n, prompt_hash=prompt_hash,
                       score=rec.get("score"), source=source, voice_free=rec.get("voice_free"),
                       note="" if res else "kept on its local checks (no per-take judge)")
            log("  %s take %d: accepted%s -> %s" % (iid, n, (" (judge %.1f)" % res["score"]) if res else "", final))
            return store.load_registry(root, d)["items"][iid]
        rec["status"] = "rejected"
        rec["file"] = store.move_to(root, take, os.path.join(d, "_rejected")) or take
        _save_take(root, d, iid, rec)
        log("  %s take %d: rejected by the judge (%.1f, needs %g): %s"
            % (iid, n, res["score"], res["pass_score"], ", ".join(rec["failed"]) or "voice heard"))
        if res.get("voice_free") is not False and (best is None or res["score"] > best[1]):
            best = (rec["file"], res["score"], n)
        fix = judging.fix_from(res) or fix
    if best:
        src = os.path.join(root, best[0])
        tmp_rel = os.path.join(d, "_takes", "flagged_" + os.path.basename(best[0]))
        os.makedirs(os.path.dirname(os.path.join(root, tmp_rel)), exist_ok=True)
        shutil.copy2(src, os.path.join(root, tmp_rel))
        final = install(tmp_rel)
        _save_take(root, d, iid, None, status="flagged", file=final, take=best[2], prompt_hash=prompt_hash,
                   score=best[1], source=source,
                   note="no take reached the pass score in %d takes; the best (%.1f) is in place. Ask the user: "
                        "accept, edit by hand, or allow another take (--extra-take)." % (allowed, best[1]))
        log("  %s: no take passed in %d; best take %d (%.1f) is in place and FLAGGED" % (iid, allowed, best[2],
                                                                                        best[1]))
    else:
        _save_take(root, d, iid, None, status="rejected",
                   note="no usable take in %d: each failed its local checks or (music) a judge heard a voice; "
                        "see %s/_rejected/" % (allowed, d))
        log("  %s: no usable take in %d; nothing is in place" % (iid, allowed))
    return store.load_registry(root, d)["items"][iid]


def _save_take(root, d, iid, rec, **fields):
    def f(reg):
        it = store.item(reg, iid)
        if rec is not None:
            it.setdefault("takes", []).append(rec)
        it.update({k: v for k, v in fields.items() if v is not None or k == "score"})
        it["updated"] = util.now()
    store.update_registry(root, d, f)
