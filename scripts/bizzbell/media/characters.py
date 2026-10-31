"""Stage 5: a turnaround sheet per character and a plate per location, with Hidrogen image + reference images.

Reads characters/bible.md (the agent writes it from the screenplay; sections are matched by heading) and the
screenplay's bibles (pasted verbatim). Writes characters/prompts.json ("sheet:<ID>", "plate:<ID>"),
characters/sheets/<ID>.png, characters/plates/<ID>.png, characters/registry.json; rejected takes go to
characters/_rejected/. A real person (bible "real_person": true or "photos") needs CONSENT.md first.

The optional ChatGPT path happens in the user's browser; import_image() registers the image the user approved."""
import os

from .. import hidrogen, project
from ..errors import UsageError
from . import ff, judging, paid, screenplay, store, takes

D = "characters"

SHEET = ("A character reference sheet of one person for a short film. Four views side by side on one plain "
         "light-grey studio background, even soft light: (1) head and shoulders, front; (2) head and shoulders, "
         "three-quarter left; (3) head and shoulders, profile right; (4) full body, front, standing, arms relaxed. "
         "The same person and the same clothes in all four views. Photoreal, natural skin texture, hands with five "
         "fingers. No text, labels, numbers, logos or emblems anywhere.")
REAL = ("The reference photos are real photos of this person, used with their written consent. Every view must "
        "match them exactly: face shape, eyes, nose, hairline, hair, facial hair, glasses. Use the photos for "
        "identity only, not their background, pose or anything they hold.")
PLATE = ("One empty photoreal still of a real place for a short film, with no people in it. A {aspect} frame at eye "
         "level, the whole space readable, natural light. No text, no signs with words, no logos, no emblems, no "
         "screens with content, no number plates.")
REFNOTE = ("Use the reference images only for identity, wardrobe and setting. Do not copy their backgrounds, poses "
           "or framing; never make a collage beyond the four views asked for.")


safe = store.safe


def file_for(key):
    kind, _, name = key.partition(":")
    return os.path.join(D, "sheets" if kind == "sheet" else "plates", safe(name) + ".png")


def build_prompts(root, sp):
    """{key: prompt} for every character and location in the screenplay's bibles."""
    sections = store.bible_sections(root)
    out = {}
    for cid, b in sp.bibles["characters"].items():
        detail = store.bible_for(sections, cid, b["name"])
        parts = [SHEET]
        if b["real_person"] or b["photos"]:
            parts.append(REAL)
        parts += ["", "Character bible (verbatim):", b["text"] or cid]
        if detail:
            parts += ["", "In depth (from the character bible):", detail]
        out["sheet:" + cid] = "\n".join(parts).strip()
    for lid, b in sp.bibles["locations"].items():
        detail = store.bible_for(sections, lid, b["name"])
        parts = [PLATE.format(aspect=sp.aspect), "", "Location bible (verbatim):", b["text"] or lid]
        if detail:
            parts += ["", "In depth:", detail]
        if sp.continuity:
            parts += ["", "Continuity: " + " ".join(sp.continuity)]
        out["plate:" + lid] = "\n".join(parts).strip()
    return out


def _entry(sp, key):
    kind, _, name = key.partition(":")
    group = sp.bibles["characters" if kind == "sheet" else "locations"]
    if name not in group:
        raise UsageError("%s is not in the screenplay's %s bibles (have: %s)"
                         % (name, "character" if kind == "sheet" else "location", ", ".join(group) or "none"))
    return group[name]


def refs_for(root, sp, key):
    b = _entry(sp, key)
    refs = list(b["photos"]) + list(b["refs"])
    for r in refs:
        if not os.path.exists(os.path.join(root, r)):
            raise UsageError("%s: reference %s is not in the project" % (key, r))
    return refs


def real_person(sp, key):
    b = _entry(sp, key)
    return key.startswith("sheet:") and (b["real_person"] or bool(b["photos"]))


def resolve(sp, names):
    """Keys for the given names (BAKER, sheet:BAKER, plate:SHOP); all keys when names is empty."""
    allk = ["sheet:" + c for c in sp.bibles["characters"]] + ["plate:" + l for l in sp.bibles["locations"]]
    if not names:
        return allk
    out = []
    for n in names:
        if n in allk:
            out.append(n)
        elif "sheet:" + n in allk:
            out.append("sheet:" + n)
        elif "plate:" + n in allk:
            out.append("plate:" + n)
        else:
            raise UsageError("unknown character or location %r (have: %s)" % (n, ", ".join(allk) or "none"))
    return out


def _labels(root, sp, key, refs):
    b = _entry(sp, key)
    out = []
    for i, r in enumerate(refs):
        what = "a consented photo of %s" % b["name"] if r in b["photos"] else "a reference for %s" % b["name"]
        out.append("Image %d: %s." % (i + 1, what))
    return out


def full_prompt(root, sp, key, prompt, refs, fix=""):
    parts = []
    if refs:
        parts += ["Reference images:"] + _labels(root, sp, key, refs) + [REFNOTE, ""]
    parts.append(prompt)
    if fix:
        parts += ["", "IMPORTANT CORRECTIONS: " + fix]
    return "\n".join(parts)


def make(root, names=(), dry_run=False, rebuild_prompts=False, redo=False, fix="", extra=0, judge=True, log=print):
    """Make the sheets and plates that are missing or whose prompt changed. Returns {key: item} (or the plan)."""
    if not dry_run:
        project.require_done(root, "characters")
    sp = screenplay.load(root)
    prompts = store.sync_prompts(root, D, build_prompts(root, sp), rebuild=rebuild_prompts)
    keys = resolve(sp, names)
    ms = store.media_settings(root)
    model = project.model_for(root, "image")
    reg = store.load_registry(root, D)
    plan = paid.Plan(root)
    todo = []
    for key in keys:
        prompt = prompts.get(key)
        if not prompt:
            raise UsageError("characters/prompts.json has no prompt for %s (run with --rebuild-prompts)" % key)
        ph = store.phash(prompt)
        it = reg["items"].get(key, {})
        if not store.needs_work(root, it, ph, redo):
            log("  %s: %s (%s), up to date" % (key, it.get("status"), it.get("file")))
            continue
        if real_person(sp, key):
            why = store.consent_problem(root, [_entry(sp, key)["name"]])
            if why:
                raise UsageError("%s is a real person: %s" % (key, why))
        todo.append((key, prompt, ph))
    for key, prompt, ph in todo:
        refs = refs_for(root, sp, key)
        aspect = "16:9" if key.startswith("sheet:") else sp.aspect
        if dry_run:
            body = paid.image_body(full_prompt(root, sp, key, prompt, refs, fix), refs, aspect, ms["image_size"],
                                   model)
            plan.add("image", model, "/v1/images/generations", body, "%s -> %s" % (key, file_for(key)))
            if judge and judging.load(root, "characters"):
                plan.add_judge(key, [file_for(key)] + refs)
            continue
        log("%s -> %s" % (key, file_for(key)))
        _make_one(root, sp, key, prompt, ph, refs, aspect, model, ms, fix, extra, judge, log)
    if dry_run:
        plan.show(log)
        return {"plan": plan.calls}
    return store.load_registry(root, D)["items"]


def _make_one(root, sp, key, prompt, ph, refs, aspect, model, ms, fix, extra, judge, log):
    abs_refs = [os.path.join(root, r) for r in refs]

    def generate(n, fx):
        text = full_prompt(root, sp, key, prompt, refs, fx)
        idem = store.idem(root, "image", key, ph, n, fx)
        png, _resp = paid.call(root, "image", lambda: hidrogen.image(
            text, abs_refs, aspect=aspect, size=ms["image_size"], model=model, idem=idem),
            model=model, purpose="%s take %d" % (key, n), ref=idem,
            quote_params={"count": 1, "size": ms["image_size"], "aspect_ratio": aspect})
        out = os.path.join(D, "_takes", "%s_t%d.png" % (safe(key.replace(":", "_")), n))
        store.write_bytes(os.path.join(root, out), png)
        ff.crop_image_to_aspect(os.path.join(root, out), aspect)
        return out

    def check_local(rel):
        return image_ok(os.path.join(root, rel), aspect)

    def judge_fn(rel):
        b = _entry(sp, key)
        notes = ("Judge ONE %s: file 1 is the new image of %s; the other files are its references (identity and "
                 "setting only). Bible: %s" % ("character sheet" if key.startswith("sheet:") else "location plate",
                                                b["name"], b["text"][:1500]))
        return judging.judge_item(root, "characters", [os.path.join(root, rel)] + abs_refs, notes, key)

    def install(rel):
        final = file_for(key)
        if os.path.exists(os.path.join(root, final)):
            store.move_to(root, final, os.path.join(D, "_rejected"), "%s_old.png" % safe(key.replace(":", "_")))
        os.makedirs(os.path.dirname(os.path.join(root, final)), exist_ok=True)
        os.replace(os.path.join(root, rel), os.path.join(root, final))
        return final

    return takes.run_item(root, D, key, generate, check_local, judge_fn if judge else None, install,
                          prompt_hash=ph, extra=extra, fix=fix, log=log)


def image_ok(path, aspect=None):
    """(ok, notes) local checks of a still: readable, not black, the right aspect."""
    try:
        p = ff.probe(path)
    except Exception as e:
        return False, "not a readable image (%s)" % hidrogen.redact(e)[:120]
    if not p["width"] or not p["height"]:
        return False, "not a readable image"
    if ff.mean_luma(path) < 8:
        return False, "the image is black"
    if aspect:
        aw, ah = [float(x) for x in aspect.split(":")]
        if abs(p["width"] / float(p["height"]) - aw / ah) > 0.02:
            return False, "aspect %dx%d is not %s" % (p["width"], p["height"], aspect)
    return True, "%dx%d, not black%s" % (p["width"], p["height"], ", %s" % aspect if aspect else "")


def import_image(root, path, character=None, location=None, source="chatgpt", note=""):
    """Register an image the user approved (for example made in ChatGPT in their browser) as a sheet or plate."""
    if bool(character) == bool(location):
        raise UsageError("say which one it is: --character <ID> or --location <ID>")
    if not os.path.isfile(path):
        raise UsageError("no such file: %s" % path)
    sp = screenplay.load(root)
    key = ("sheet:" + character) if character else ("plate:" + location)
    _entry(sp, key)
    if real_person(sp, key):
        why = store.consent_problem(root, [_entry(sp, key)["name"]])
        if why:
            raise UsageError("%s is a real person: %s" % (key, why))
    final = file_for(key)
    if os.path.exists(os.path.join(root, final)):
        store.move_to(root, final, os.path.join(D, "_rejected"), "%s_old.png" % safe(key.replace(":", "_")))
    os.makedirs(os.path.dirname(os.path.join(root, final)), exist_ok=True)
    ff.run(["-i", os.path.abspath(path), "-frames:v", "1", os.path.join(root, final)])
    ok, notes = image_ok(os.path.join(root, final))
    if not ok:
        store.move_to(root, final, os.path.join(D, "_rejected"))
        raise UsageError("the imported image failed its checks: %s" % notes)
    try:
        prompts = store.sync_prompts(root, D, build_prompts(root, sp))
        ph = store.phash(prompts.get(key, ""))
    except UsageError:
        ph = None

    def f(reg):
        it = store.item(reg, key)
        it.update({"status": "approved", "file": final, "source": source, "prompt_hash": ph,
                   "note": note or "imported after the user approved it", "imported_from": os.path.basename(path)})
    store.update_registry(root, D, f)
    return {"key": key, "file": final, "source": source, "checks": notes}


def status(root):
    return store.load_registry(root, D)["items"]
