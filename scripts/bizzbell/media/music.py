"""Stage 7, music: an instrumental bed with Hidrogen music, judged voice-free on EVERY judge pass.

A take whose judge hears a voice (singing, humming, spoken words) in any pass is rejected, whatever its score.
The chosen bed is edited to the film's length with ffmpeg (looped if short, faded in and out).

Files: audio/music/prompts.json ({"bed": prompt}), audio/music/takes/bed_t<n>.wav, audio/music/registry.json,
audio/music_bed.wav (48 kHz stereo, film length)."""
import math
import os

from .. import hidrogen, project
from ..errors import UsageError
from . import ff, judging, paid, screenplay, store, takes
from .voice import audio_ok

D = os.path.join("audio", "music")
TAIL = ("Instrumental only: no vocals, no singing, no humming, no choir, no spoken words, no vocal samples. It sits "
        "under a voice-over: steady, uncluttered mid-range, no sudden drops or risers.")
DEFAULT = "A warm, modern instrumental bed for a short ad, light steady pulse, hopeful and simple."


def build_prompts(sp):
    m = sp.music()
    base = str(m.get("prompt") or DEFAULT).strip()
    return {"bed": "%s %s" % (base, TAIL)}


def make(root, seconds=None, dry_run=False, rebuild_prompts=False, redo=False, fix="", extra=0, judge=True, log=print):
    """Generate the bed (retakes up to max_takes), then edit it to the film. Returns the item or the plan."""
    if not dry_run:
        project.require_done(root, "audio")
    sp = screenplay.load(root)
    prompts = store.sync_prompts(root, D, build_prompts(sp), rebuild=rebuild_prompts)
    prompt = prompts.get("bed")
    if not prompt:
        raise UsageError("audio/music/prompts.json has no \"bed\" prompt (run with --rebuild-prompts)")
    secs = int(seconds or min(180, math.ceil(sp.duration) + 2))
    model = project.model_for(root, "music")
    passes = int(project.load_settings(root).get("gate", {}).get("passes", 2))
    ph = store.phash([prompt, secs])
    it = store.load_registry(root, D)["items"].get("bed", {})
    if dry_run:
        plan = paid.Plan(root)
        if store.needs_work(root, it, ph, redo):
            plan.add("music", model, "/v1/music", paid.music_body(prompt + ((" " + fix) if fix else ""), secs,
                                                                  model), "bed -> audio/music_bed.wav", units=1)
            if judge and judging.load(root, "music"):
                plan.add_judge("bed", ["audio/music/takes/bed_t1.wav"], passes)
        plan.show(log)
        return {"plan": plan.calls}
    if not store.needs_work(root, it, ph, redo):
        log("  bed: %s (%s), up to date" % (it.get("status"), it.get("file")))
        if not os.path.exists(os.path.join(root, "audio", "music_bed.wav")):
            edit(root, it["file"])
        return it

    def generate(n, fx):
        text = prompt + ((" " + fx) if fx and not fx.startswith("Fix these") else "")
        key = store.idem(root, "music", ph, n, fx, model=model, body=paid.music_body(text, secs, model))
        outs, _job = paid.call(root, "music", lambda: hidrogen.music(
            text, seconds=secs, instrumental=True, model=model, idem=key),
            model=model, purpose="music bed take %d" % n, quote_params={"seconds": secs}, ref=key)
        data, mime = outs[0]
        ext = ".mp3" if "mpeg" in (mime or "") else ".m4a" if "mp4" in (mime or "") else ".wav"
        raw = os.path.join(D, "takes", "bed_t%d%s" % (n, ext))
        store.write_bytes(os.path.join(root, raw), data)
        if ext != ".wav":
            wav = os.path.join(D, "takes", "bed_t%d.wav" % n)
            ff.run(["-i", os.path.join(root, raw), "-ar", "48000", "-ac", "2", os.path.join(root, wav)])
            return wav
        return raw

    def check_local(rel):
        return audio_ok(os.path.join(root, rel), min_s=1.0)

    def judge_fn(rel):
        notes = ("Judge ONE music bed for a short ad (%.0f s). It must be instrumental with no voice of any kind "
                 "(singing, humming, choir, spoken words). Brief for the music: %s" % (sp.duration, prompt))
        return judging.judge_item(root, "music", [os.path.join(root, rel)], notes, "bed", passes=passes)

    def install(rel):
        edit(root, rel)
        return rel

    log("music bed: %ds, model %s" % (secs, model))
    return takes.run_item(root, D, "bed", generate, check_local, judge_fn if judge else None, install,
                          prompt_hash=ph, extra=extra, fix=fix, log=log)


def edit(root, src_rel, fade_in=0.05, fade_out=0.8):
    """audio/music_bed.wav: the bed looped/trimmed to the film length, faded in and out, 48 kHz stereo."""
    sp = screenplay.load(root)
    d = sp.duration
    out = os.path.join("audio", "music_bed.wav")
    fo = min(fade_out, d / 3.0)
    af = "aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:%.3f,afade=t=in:d=%.2f,afade=t=out:st=%.3f:d=%.2f" \
        % (d, fade_in, max(0.0, d - fo), fo)
    ff.run(["-stream_loop", "-1", "-i", os.path.join(root, src_rel), "-af", af, "-t", "%.3f" % d, "-ar", "48000",
            "-ac", "2", "-c:a", "pcm_s16le", os.path.join(root, out)])
    return out


def status(root):
    return store.load_registry(root, D)["items"]
