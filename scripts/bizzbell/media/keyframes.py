"""Stage 6: one keyframe per live shot, with Hidrogen image.

References (always; never a text-only frame): the sheets of the shot's characters, the plate of its location, the
previous approved keyframe, and any refs the shot names. The bibles are pasted verbatim from screenplay.json.
Writes keyframes/prompts.json, keyframes/<shot>.png, keyframes/registry.json; rejects go to keyframes/_rejected/.
Shots are made in timeline order, so each one can lean on the keyframe before it."""
import os

from .. import hidrogen, project
from ..errors import UsageError
from . import characters, ff, judging, paid, screenplay, store, takes

D = "keyframes"

STYLE = ("Photoreal still frame from a {orient} {aspect} handheld phone video: natural documentary realism, real "
         "skin texture, unposed body language, hands with exactly five fingers and a real grip, natural colours, "
         "slight sensor grain, shallow depth of field. One small action at most. Nobody is cut off by the frame "
         "edge in a way that suggests leaving. No text, letters, numbers, captions, logos, brand marks, emblems, "
         "badges, uniform insignia or watermarks anywhere; plain unbranded objects; phone screens face away from "
         "the lens; no number plates.")
REFNOTE = ("Use the reference images only for identity, face, hair, wardrobe, props and setting. Do not copy their "
           "studio backgrounds, poses or framing; never make a collage or a split image. One single photograph.")


def orient(aspect):
    return "vertical" if aspect in ("9:16", "4:5") else "horizontal" if aspect == "16:9" else "square"


def bibles_for(sp, shot):
    """The verbatim bible texts for a shot (characters, location, props), in that order."""
    out = []
    for cid in shot["characters"]:
        b = sp.bibles["characters"].get(cid)
        if b and b["text"]:
            out.append(b["text"])
    if shot["location"] and shot["location"] in sp.bibles["locations"]:
        t = sp.bibles["locations"][shot["location"]]["text"]
        if t:
            out.append(t)
    for pid in shot["props"]:
        b = sp.bibles["props"].get(pid)
        if b and b["text"]:
            out.append(b["text"])
    return out


def build_prompt(sp, shot):
    parts = ["SHOT %s (%.1f-%.1f s). %s" % (shot["id"], shot["start"], shot["end"], shot["keyframe"])]
    if shot["camera"]:
        parts.append("Camera: %s" % shot["camera"])
    bib = bibles_for(sp, shot)
    if bib:
        parts += ["", "Character, location and prop bibles (verbatim; keep every detail):"] + bib
    if sp.continuity:
        parts += ["", "Continuity: " + " ".join(sp.continuity)]
    parts += ["", STYLE.format(orient=orient(sp.aspect), aspect=sp.aspect)]
    return "\n".join(parts)


def build_prompts(sp):
    return {s["id"]: build_prompt(sp, s) for s in sp.live_shots()}


def refs_for(root, sp, shot, reg_chars, reg_kf):
    """[(path, label)] references for a shot. Missing sheets/plates are reported, not invented."""
    out, missing = [], []
    for cid in shot["characters"]:
        it = reg_chars["items"].get("sheet:" + cid, {})
        f = it.get("file") or characters.file_for("sheet:" + cid)
        if os.path.exists(os.path.join(root, f)):
            out.append((f, "%s's character sheet: face, hair, build and wardrobe" % cid))
        else:
            missing.append("sheet:" + cid)
    if shot["location"]:
        f = characters.file_for("plate:" + shot["location"])
        if os.path.exists(os.path.join(root, f)):
            out.append((f, "the location %s: place and light" % shot["location"]))
        else:
            missing.append("plate:" + shot["location"])
    prev = previous_approved(root, sp, shot["id"], reg_kf)
    if prev:
        out.append((prev, "the previous shot's approved keyframe: same people, clothes and light"))
    for r in shot["refs"]:
        p, label = (r[0], r[1]) if isinstance(r, (list, tuple)) and len(r) > 1 else (str(r), "a reference")
        if not os.path.exists(os.path.join(root, p)):
            raise UsageError("%s: reference %s is not in the project" % (shot["id"], p))
        out.append((p, label))
    return out, missing


def previous_approved(root, sp, sid, reg_kf):
    live = [s["id"] for s in sp.live_shots()]
    i = live.index(sid)
    for prev in reversed(live[:i]):
        it = reg_kf["items"].get(prev, {})
        f = it.get("file")
        if it.get("status") in store.GOOD and f and os.path.exists(os.path.join(root, f)):
            return f
    return None


def full_prompt(prompt, refs, fix=""):
    parts = ["Make one photoreal still frame for a short film.", "", "Reference images:"]
    parts += ["Image %d: %s." % (i + 1, label) for i, (_p, label) in enumerate(refs)]
    parts += [REFNOTE, "", prompt]
    if fix:
        parts += ["", "IMPORTANT CORRECTIONS: " + fix]
    return "\n".join(parts)


def _real_people(sp, shot):
    return [c for c in shot["characters"] if c in sp.bibles["characters"] and
            (sp.bibles["characters"][c]["real_person"] or sp.bibles["characters"][c]["photos"])]


def make(root, shots=(), dry_run=False, rebuild_prompts=False, redo=False, fix="", extra=0, judge=True, log=print):
    """Make the keyframes that are missing, rejected or whose prompt changed. Returns {shot: item} (or the plan)."""
    sp = screenplay.load(root)
    prompts = store.sync_prompts(root, D, build_prompts(sp), rebuild=rebuild_prompts)
    live = sp.live_shots()
    if shots:
        known = [s["id"] for s in live]
        bad = [s for s in shots if s not in known]
        if bad:
            raise UsageError("not live shots: %s (live shots: %s)" % (", ".join(bad), ", ".join(known)))
        live = [s for s in live if s["id"] in shots]
    ms = store.media_settings(root)
    model = project.model_for(root, "image")
    plan = paid.Plan(root)
    for shot in live:
        sid = shot["id"]
        prompt = prompts.get(sid)
        if not prompt:
            raise UsageError("keyframes/prompts.json has no prompt for %s (run with --rebuild-prompts)" % sid)
        ph = store.phash(prompt)
        reg_kf = store.load_registry(root, D)
        it = reg_kf["items"].get(sid, {})
        if not store.needs_work(root, it, ph, redo):
            log("  %s: %s (%s), up to date" % (sid, it.get("status"), it.get("file")))
            continue
        if _real_people(sp, shot):
            why = store.consent_problem(root, [sp.bibles["characters"][c]["name"] for c in _real_people(sp, shot)])
            if why:
                raise UsageError("%s shows a real person: %s" % (sid, why))
        refs, missing = refs_for(root, sp, shot, store.load_registry(root, characters.D), reg_kf)
        if missing:
            log("  %s: no %s yet (make them with: bb characters make)" % (sid, ", ".join(missing)))
        if not refs:
            raise UsageError("%s has no reference image (sheet, plate or previous keyframe). Make the character "
                             "sheets and location plates first: python3 scripts/bb.py characters make" % sid)
        item_fix = " ".join(x for x in (fix, it.get("fix", "")) if x)
        if dry_run:
            body = paid.image_body(full_prompt(prompt, refs, item_fix), [p for p, _l in refs], sp.aspect,
                                   ms["image_size"], model)
            plan.add("image", model, "/v1/images/generations", body, "%s -> keyframes/%s.png" % (sid, sid))
            if judge and judging.load(root, D):
                plan.add_judge(sid, ["keyframes/%s.png" % sid] + [p for p, _l in refs])
            continue
        log("%s -> keyframes/%s.png  (refs: %s)" % (sid, sid, ", ".join(p for p, _l in refs)))
        _make_one(root, sp, shot, prompt, ph, refs, model, ms, item_fix, extra, judge, log)
    if dry_run:
        plan.show(log)
        return {"plan": plan.calls}
    return store.load_registry(root, D)["items"]


def _make_one(root, sp, shot, prompt, ph, refs, model, ms, fix, extra, judge, log):
    sid = shot["id"]
    abs_refs = [os.path.join(root, p) for p, _l in refs]

    def generate(n, fx):
        text = full_prompt(prompt, refs, fx)
        png, _resp = paid.call(root, "image", lambda: hidrogen.image(
            text, abs_refs, aspect=sp.aspect, size=ms["image_size"], model=model,
            idem=store.idem(root, "keyframe", sid, ph, n, fx)), model=model, purpose="keyframe %s take %d" % (sid, n),
            quote_params={"count": 1, "size": ms["image_size"], "aspect_ratio": sp.aspect})
        out = os.path.join(D, "_takes", "%s_t%d.png" % (sid, n))
        store.write_bytes(os.path.join(root, out), png)
        ff.crop_image_to_aspect(os.path.join(root, out), sp.aspect)
        return out

    def check_local(rel):
        return characters.image_ok(os.path.join(root, rel), sp.aspect)

    def judge_fn(rel):
        notes = ("Judge ONE keyframe. File 1 is the new keyframe; the other files are its references (character "
                 "sheet, location plate, previous keyframe) for identity and continuity only.\n%s"
                 % sp.rows_text(sid))
        return judging.judge_item(root, D, [os.path.join(root, rel)] + abs_refs, notes, sid)

    def install(rel):
        final = os.path.join(D, "%s.png" % sid)
        if os.path.exists(os.path.join(root, final)):
            store.move_to(root, final, os.path.join(D, "_rejected"), "%s_old.png" % sid)
        os.replace(os.path.join(root, rel), os.path.join(root, final))
        return final

    it = takes.run_item(root, D, sid, generate, check_local, judge_fn if judge else None, install, prompt_hash=ph,
                        extra=extra, fix=fix, log=log)
    if it.get("fix"):
        store.update_registry(root, D, lambda reg: store.item(reg, sid).pop("fix", None))
    return it


def reject(root, sid, note=""):
    """Move keyframes/<sid>.png to keyframes/_rejected/; the note becomes a correction for the next take."""
    sp = screenplay.load(root)
    sp.shot(sid)
    moved = store.move_to(root, os.path.join(D, "%s.png" % sid), os.path.join(D, "_rejected"))

    def f(reg):
        it = store.item(reg, sid)
        it.update({"status": "rejected", "file": None, "note": note or "rejected by hand", "fix": note})
    store.update_registry(root, D, f)
    return moved


def approve(root, sid, note=""):
    """Record that the user approved the keyframe in place (it then counts as the previous approved keyframe)."""
    f_rel = os.path.join(D, "%s.png" % sid)
    if not os.path.exists(os.path.join(root, f_rel)):
        raise UsageError("no keyframes/%s.png to approve" % sid)

    def f(reg):
        it = store.item(reg, sid)
        it.update({"status": "approved", "file": f_rel, "note": note or "approved by the user"})
    store.update_registry(root, D, f)
    return f_rel


def status(root):
    return store.load_registry(root, D)["items"]
