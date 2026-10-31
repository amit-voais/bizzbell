"""Stage 8A, per shot: image-to-video from the shot's keyframe (the keyframe is the first frame).

Each take is generated 4-10 s long and only the early window is used (models add actions later in a take):
window = [clip_start, clip_start + the shot's slot]. The model's own audio is always discarded. Local checks run
first (duration, black frames with blackdetect, frozen picture with freezedetect inside the window), then the paid
per-take judge. Takes per shot: bizzbell.json budget.max_takes.

Writes clips/prompts.json, clips/raw/<shot>_t<n>.mp4, clips/cut/<shot>.mp4 (the window, master size, no audio)
and clips/registry.json (with each shot's pick: raw take, start, duration).

When /v1/videos is not live (HTTP 404, or `bb doctor` found it missing) Version A is skipped with a clear note in
project.json (stage video_a) and nothing crashes: Version B (HyperFrames) is still made."""
import math
import os

from .. import hidrogen, project
from ..errors import UsageError
from . import ff, judging, paid, screenplay, store, takes

D = "clips"
SKIP_NOTE = ("Version A skipped: /v1/videos is not live on this Hidrogen gateway (HTTP 404). Nothing was charged. "
             "Version B (HyperFrames) is still made from the same screenplay.")

TAIL = ("Animate this exact image as the first frame: same framing, people, place, light and colours. Photoreal "
        "live action. Natural behaviour: blinks, breathing, small hesitations; no posing. Faces, hair, glasses and "
        "clothes stay exactly the same. Hands keep five fingers and their grip. Nobody enters or leaves the frame; "
        "no one else appears; no cuts. No on-screen text, captions, logos, readable screens or watermarks.")
TALK = ("The person speaks this line in a natural, casual way: \"{say}\". The lips move in rhythm with the speech, "
        "starting within the first half second.")


def build_prompt(shot):
    p = (shot["motion"] or "A small natural movement; the camera stays almost still.").strip()
    if shot["say"]:
        p += " " + TALK.format(say=shot["say"])
    return p + " " + TAIL


def build_prompts(sp):
    return {s["id"]: build_prompt(s) for s in sp.live_shots()}


def videos_missing(root):
    return (project.load_settings(root).get("endpoints") or {}).get("videos") == "missing"


def skip_version_a(root, note=SKIP_NOTE):
    project.mark_stage(root, "video_a", "skipped", note=note)
    return {"skipped": True, "note": note}


def plan_seconds(ms, slot_len):
    """Seconds to generate: clip_seconds (default 6), at least the window plus a margin, within 4-10."""
    want = max(float(ms["clip_seconds"]), ms["clip_start"] + slot_len + 1.0)
    return int(min(10, max(4, math.ceil(want))))


def make(root, shots=(), dry_run=False, rebuild_prompts=False, redo=False, fix="", extra=0, judge=True, log=print):
    """Make a clip for every live shot that has a keyframe. Returns {shot: item}, the plan, or {"skipped": ...}."""
    if not dry_run:
        project.require_done(root, "video_a")
    sp = screenplay.load(root)
    prompts = store.sync_prompts(root, D, build_prompts(sp), rebuild=rebuild_prompts)
    live = sp.live_shots()
    if shots:
        live = [s for s in live if s["id"] in shots]
        if not live:
            raise UsageError("none of %s is a live shot" % ", ".join(shots))
    if videos_missing(root) and not dry_run:
        log(SKIP_NOTE)
        return skip_version_a(root)
    ms = store.media_settings(root)
    model = project.model_for(root, "video")
    plan = paid.Plan(root)
    reg_kf = store.load_registry(root, "keyframes")
    for shot in live:
        sid = shot["id"]
        kf_item = reg_kf["items"].get(sid, {})
        kf = kf_item.get("file") or os.path.join("keyframes", "%s.png" % sid)
        if not os.path.exists(os.path.join(root, kf)):
            log("  %s: no keyframe yet (bb keyframes make %s); skipped" % (sid, sid))
            continue
        prompt = prompts.get(sid)
        if not prompt:
            raise UsageError("clips/prompts.json has no prompt for %s (run with --rebuild-prompts)" % sid)
        ph = store.phash([prompt, store.file_hash(os.path.join(root, kf))])
        it = store.load_registry(root, D)["items"].get(sid, {})
        if not store.needs_work(root, it, ph, redo):
            log("  %s: %s (%s), up to date" % (sid, it.get("status"), it.get("file")))
            continue
        a, b = sp.slot(sid)
        slot_len = round(b - a, 3)
        seconds = plan_seconds(ms, slot_len)
        text = prompt + (("\nIMPORTANT: " + fix) if fix else "")
        if dry_run:
            plan.add("video", model, "/v1/videos", paid.video_body(text, kf, sp.aspect, ms["resolution"], seconds,
                                                                   model),
                     "%s -> clips/raw/%s_t1.mp4 (%ds generated, %.2fs used from %.2fs)"
                     % (sid, sid, seconds, slot_len, ms["clip_start"]), units=seconds)
            if judge and judging.load(root, D):
                plan.add_judge(sid, ["clips/raw/%s_t1.mp4" % sid, kf])
            continue
        log("%s -> clips/cut/%s.mp4  (%ds generated, window %.2f-%.2f s)"
            % (sid, sid, seconds, ms["clip_start"], ms["clip_start"] + slot_len))
        try:
            _make_one(root, sp, shot, prompt, ph, kf, model, ms, seconds, slot_len, fix, extra, judge, log)
        except hidrogen.NotAvailable:
            log(SKIP_NOTE)
            return skip_version_a(root)
    if dry_run:
        if videos_missing(root):
            log("note: bb doctor found /v1/videos missing; a real run would skip Version A")
        plan.show(log)
        return {"plan": plan.calls}
    return store.load_registry(root, D)["items"]


def _make_one(root, sp, shot, prompt, ph, kf, model, ms, seconds, slot_len, fix, extra, judge, log):
    sid = shot["id"]
    window = {"start": float(ms["clip_start"])}

    def generate(n, fx):
        text = prompt + (("\nIMPORTANT: " + fx) if fx else "")
        key = store.idem(root, "video", sid, ph, n, fx)
        mp4, _job = paid.call(root, "video", lambda: hidrogen.video(
            text, first_frame=os.path.join(root, kf), aspect=sp.aspect, resolution=ms["resolution"],
            seconds=seconds, model=model, idem=key),
            model=model, purpose="clip %s take %d" % (sid, n), units=seconds, ref=key,
            quote_params={"seconds": seconds, "resolution": ms["resolution"], "aspect_ratio": sp.aspect})
        out = os.path.join(D, "raw", "%s_t%d.mp4" % (sid, n))
        store.write_bytes(os.path.join(root, out), mp4)
        return out

    def check_local(rel):
        ok, notes, start = clip_ok(os.path.join(root, rel), float(ms["clip_start"]), slot_len)
        window["start"] = start
        return ok, notes

    def judge_fn(rel):
        notes = ("Judge ONE generated take. File 1 is the take; file 2 is its keyframe (the first frame). Only the "
                 "window %.2f-%.2f s of the take is used; judge that window. Its sound is discarded (the voice is "
                 "added later), so ignore the audio.\n%s" % (window["start"], window["start"] + slot_len,
                                                             sp.rows_text(sid)))
        return judging.judge_item(root, D, [os.path.join(root, rel), os.path.join(root, kf)], notes, sid)

    def install(rel):
        cut = cut_window(root, rel, sid, window["start"], slot_len, sp.aspect)
        pick = {"raw": rel, "start": window["start"], "dur": slot_len, "cut": cut}
        store.update_registry(root, D, lambda reg: store.item(reg, sid).__setitem__("pick", pick))
        return cut

    return takes.run_item(root, D, sid, generate, check_local, judge_fn if judge else None, install, prompt_hash=ph,
                          extra=extra, fix=fix, log=log)


def clip_ok(path, start, slot_len):
    """(ok, notes, window start): duration, black frames and a frozen picture inside the window."""
    try:
        p = ff.probe(path)
    except Exception as e:
        return False, "not a readable video (%s)" % hidrogen.redact(e)[:120], start
    if not p["has_video"]:
        return False, "no video stream", start
    if p["duration"] < start + slot_len - 0.05:
        if p["duration"] >= slot_len - 0.05:
            start = max(0.0, round(p["duration"] - slot_len, 3))
        else:
            return False, "the take is %.2fs; the shot needs %.2fs" % (p["duration"], slot_len), start
    black = ff.black_spans(path, start, slot_len, min_dur=min(0.2, slot_len / 2))
    if black:
        return False, "black frames at %s" % ", ".join("%.2f-%s" % (a, b) for a, b in black), start
    frz = ff.freeze_spans(path, start, slot_len, min_dur=max(0.5, min(1.0, slot_len * 0.6)))
    if frz:
        return False, "the picture freezes at %s" % ", ".join("%.2f-%s" % (a, b) for a, b in frz), start
    return True, "%.2fs, window %.2f-%.2f s clean (no black, no freeze)" % (p["duration"], start,
                                                                          start + slot_len), start


def cut_window(root, raw_rel, sid, start, dur, aspect):
    """clips/cut/<sid>.mp4: the window at the master size and fps, no audio (the last frame held if short)."""
    ms = store.media_settings(root)
    w, h = ff.master_size(aspect, project.load_settings(root))
    out = os.path.join(D, "cut", "%s.mp4" % sid)
    os.makedirs(os.path.join(root, D, "cut"), exist_ok=True)
    vf = "%s,fps=%s,format=yuv420p,tpad=stop_mode=clone:stop_duration=2" % (ff.cover_filter(w, h), ms["fps"])
    ff.run(["-ss", "%.3f" % start, "-i", os.path.join(root, raw_rel), "-t", "%.3f" % (dur + 0.5), "-an", "-vf", vf,
            "-t", "%.3f" % dur] + ff.video_encode_args(ms["fps"]) + [os.path.join(root, out)])
    return out


def pick(root, sid, take_n, start=None):
    """Use take <take_n> of a shot (the user's choice), from `start` seconds; re-cuts clips/cut/<sid>.mp4."""
    sp = screenplay.load(root)
    sp.shot(sid)
    reg = store.load_registry(root, D)
    it = reg["items"].get(sid) or {}
    t = [x for x in it.get("takes", []) if x.get("n") == int(take_n) and x.get("file")]
    if not t or not os.path.exists(os.path.join(root, t[0]["file"])):
        raise UsageError("%s has no take %s on disk" % (sid, take_n))
    a, b = sp.slot(sid)
    ms = store.media_settings(root)
    st = float(ms["clip_start"] if start is None else start)
    cut = cut_window(root, t[0]["file"], sid, st, round(b - a, 3), sp.aspect)

    def f(reg):
        x = store.item(reg, sid)
        x.update({"status": "approved", "file": cut, "take": int(take_n), "note": "picked by the user",
                  "pick": {"raw": t[0]["file"], "start": st, "dur": round(b - a, 3), "cut": cut}})
    store.update_registry(root, D, f)
    return cut


def status(root):
    return store.load_registry(root, D)["items"]
