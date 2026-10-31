"""Stage 7, voice: audition voices -> judged -> takes per VO line -> placed on the timeline.

The voice is always synthetic TTS (never a clone; the video model's own speech is discarded).
For Hindi and Hinglish the text sent to the voice is the line's "tts" field in Devanagari (it reads Devanagari
best), while captions keep the Roman spelling ("text").

Files: audio/voice/prompts.json ({line: {"tts", "style"}}), audio/voice/audition/<voice>.wav,
audio/voice/takes/<line>_t<n>.wav, audio/voice/lines/<line>.wav (the chosen take), audio/voice/registry.json,
audio/vo.wav (the VO on the film timeline, 48 kHz mono) and audio/vo_timing.json."""
import os

from .. import hidrogen, project, util
from ..errors import UsageError
from . import ff, judging, paid, screenplay, store, takes

D = os.path.join("audio", "voice")

# Hidrogen's stock studio voices (voice-studio), by how they sound. `bb voice list` prints them.
STOCK = {
    "female": ("priya", "meera", "kavya", "tara", "isha", "anya", "diya", "nisha", "riya", "sana", "asha", "zoya",
               "gauri"),
    "male": ("arjun", "dev", "raj", "veer", "kabir", "rohan", "aman", "vikram", "karan", "aditya", "yash", "neel",
             "sahil", "manav", "ishaan", "arnav"),
}
AUDITION_SIZE = 3


def stock_gender(name):
    """"female", "male" or None for a voice name."""
    for g, names in STOCK.items():
        if (name or "").lower() in names:
            return g
    return None


def default_candidates(name, gender=None, n=AUDITION_SIZE):
    """`name` plus the next stock voices of the same kind (screenplay voice.gender, else the kind of `name`)."""
    g = (gender or "").lower()
    g = g if g in STOCK else (stock_gender(name) or "female")
    out = [name] if name else []
    out += [v for v in STOCK[g] if v not in out]
    return out[:n]


def voice_name(root):
    reg = store.load_registry(root, D)
    return reg.get("voice") or project.load_settings(root).get("voice", {}).get("name") or "priya"


def style_for(sp):
    return str(sp.voice().get("style") or "").strip()


def build_prompts(sp):
    base = style_for(sp)
    out = {}
    for l in sp.lines:
        st = " ".join(x for x in (base, l["hint"]) if x).strip()
        out[l["id"]] = {"tts": l["tts"] or l["text"], "style": st}
    return out


def warnings(sp, prompts=None):
    """Plain-language warnings about the VO text (Devanagari for Hindi TTS, Roman captions)."""
    out = []
    for l in sp.lines:
        tts = ((prompts or {}).get(l["id"]) or {}).get("tts", l["tts"])
        if screenplay.hindi(sp.lang) and not screenplay.has_devanagari(tts):
            out.append("%s: the voice text is not in Devanagari; Hindi TTS reads Devanagari best (add \"tts\" in "
                       "Devanagari to the line in screenplay.json, or edit audio/voice/prompts.json)" % l["id"])
        if screenplay.has_devanagari(l["text"]):
            out.append("%s: the caption is in Devanagari; captions are Roman (set \"text\" in Roman)" % l["id"])
    return out


def audio_ok(path, min_s=0.2):
    """(ok, notes): readable, long enough, not silent."""
    try:
        p = ff.probe(path)
    except Exception as e:
        return False, "not readable audio (%s)" % hidrogen.redact(e)[:120]
    if not p["has_audio"]:
        return False, "no audio stream"
    if p["duration"] < min_s:
        return False, "only %.2fs long" % p["duration"]
    peak = ff.max_volume(path)
    if peak < -45:
        return False, "silent (peak %.1f dBFS)" % peak
    return True, "%.2fs, peak %.1f dBFS" % (p["duration"], peak)


def _tts_call(root, text, voice, model, style, purpose, idem_parts):
    key = store.idem(root, *idem_parts, model=model, body=paid.tts_body(text, voice, model, style))
    audio, _meta = paid.call(root, "voice", lambda: hidrogen.tts(text, voice=voice, model=model, style=style,
                                                                 fmt="wav", idem=key),
                             model=model, purpose=purpose, quote_params={"chars": len(text), "voice": voice}, ref=key)
    return audio


# ---------------------------------------------------------------- audition
def audition(root, voices=(), text=None, dry_run=False, judge=True, redo=False, log=print):
    """TTS the audition text in each voice, judge each, choose the best. Returns {"ranking", "chosen"} or the plan."""
    if not dry_run:
        project.require_done(root, "audio")
    sp = screenplay.load(root)
    v = sp.voice()
    settings = project.load_settings(root)
    voices = list(voices) or list(v.get("candidates") or settings.get("voice", {}).get("candidates") or []) or \
        default_candidates(v.get("name") or settings.get("voice", {}).get("name") or "priya", v.get("gender"))
    text = text or v.get("audition_text") or " ".join(l["tts"] for l in sp.lines[:2])
    if not text:
        raise UsageError("no audition text: add voice.audition_text or VO lines to screenplay.json")
    model = project.model_for(root, "voice")
    style = style_for(sp)
    passes = int(settings.get("gate", {}).get("passes", 2))
    plan = paid.Plan(root)
    reg = store.load_registry(root, D)
    for name in voices:
        key = "audition:" + name
        out = os.path.join(D, "audition", "%s.wav" % store.safe(name))
        it = reg["items"].get(key, {})
        if not redo and it.get("file") and os.path.exists(os.path.join(root, it["file"])) and "score" in it:
            log("  %s: auditioned (%s)" % (name, it.get("score")))
            continue
        if dry_run:
            plan.add("voice", model, "/v1/audio/speech", paid.tts_body(text, name, model, style), "audition " + name)
            if judge and judging.load(root, "voice"):
                plan.add_judge("audition " + name, [out], passes)
            continue
        audio = _tts_call(root, text, name, model, style, "audition %s" % name, ("tts-audition", name, text, style))
        store.write_bytes(os.path.join(root, out), audio)
        ok, notes = audio_ok(os.path.join(root, out))
        res = None
        if ok and judge:
            res = judging.judge_item(root, "voice", [os.path.join(root, out)],
                                     "Voice audition for %s. Expected words: \"%s\". Wanted voice: %s"
                                     % (name, text, style or "natural, warm, conversational"),
                                     "audition " + name, passes=passes)
        score = 0.0 if not ok else (res["score"] if res else 100.0)

        def f(r, name=name, out=out, ok=ok, notes=notes, res=res, score=score):
            it2 = store.item(r, "audition:" + name)
            it2.update({"status": "accepted" if ok else "rejected", "file": out, "local": notes, "score": score,
                        "failed": [x["id"] for x in res["failed"]] if res else [], "time": util.now()})
        store.update_registry(root, D, f)
        log("  %s: %s, score %.1f" % (name, notes, score))
    if dry_run:
        plan.show(log)
        return {"plan": plan.calls}
    reg = store.load_registry(root, D)
    ranking = sorted([(k.split(":", 1)[1], it.get("score", 0)) for k, it in reg["items"].items()
                      if k.startswith("audition:") and k.split(":", 1)[1] in voices],
                     key=lambda x: (-x[1], voices.index(x[0])))
    chosen = ranking[0][0] if ranking and ranking[0][1] > 0 else None
    if chosen:
        store.update_registry(root, D, lambda r: r.__setitem__("voice", chosen))
        project.update_settings(root, lambda s: s.setdefault("voice", {}).__setitem__("name", chosen))
    return {"ranking": ranking, "chosen": chosen}


# ---------------------------------------------------------------- takes per line
def make_takes(root, lines=(), dry_run=False, rebuild_prompts=False, redo=False, fix="", extra=0, judge=True,
               log=print):
    """A judged take per VO line (retakes up to max_takes). Returns {line: item} or the plan."""
    if not dry_run:
        project.require_done(root, "audio")
    sp = screenplay.load(root)
    if not sp.lines:
        raise UsageError("the screenplay has no VO lines (rows with \"vo\", or \"lines\")")
    prompts = store.sync_prompts(root, D, build_prompts(sp), rebuild=rebuild_prompts)
    for w in warnings(sp, prompts):
        log("  warning: " + w)
    todo = [l for l in sp.lines if not lines or l["id"] in lines]
    model = project.model_for(root, "voice")
    voice = voice_name(root)
    plan = paid.Plan(root)
    for l in todo:
        lid = l["id"]
        pr = prompts.get(lid) or {}
        if isinstance(pr, str):
            pr = {"tts": pr, "style": ""}
        tts, style = str(pr.get("tts") or l["tts"]), str(pr.get("style") or "")
        ph = store.phash([tts, style, voice])
        it = store.load_registry(root, D)["items"].get(lid, {})
        if not store.needs_work(root, it, ph, redo):
            log("  %s: %s (%s), up to date" % (lid, it.get("status"), it.get("file")))
            continue
        if dry_run:
            plan.add("voice", model, "/v1/audio/speech", paid.tts_body(tts, voice, model, style),
                     "%s -> audio/voice/lines/%s.wav" % (lid, lid))
            if judge and judging.load(root, "voice"):
                plan.add_judge(lid, ["audio/voice/takes/%s_t1.wav" % lid])
            continue
        log("%s: \"%s\" (voice %s)" % (lid, l["text"], voice))
        _take_line(root, sp, l, tts, style, ph, voice, model, fix, extra, judge, log)
    if dry_run:
        plan.show(log)
        return {"plan": plan.calls}
    return {k: v for k, v in store.load_registry(root, D)["items"].items() if not k.startswith("audition:")}


def _take_line(root, sp, l, tts, style, ph, voice, model, fix, extra, judge, log):
    lid = l["id"]

    def generate(n, fx):
        st = style + ((" " + fx) if fx and not fx.startswith("Fix these") else "")
        audio = _tts_call(root, tts, voice, model, st.strip(), "VO %s take %d" % (lid, n),
                          ("tts", lid, ph, n, fx))
        out = os.path.join(D, "takes", "%s_t%d.wav" % (lid, n))
        store.write_bytes(os.path.join(root, out), audio)
        return out

    def check_local(rel):
        return audio_ok(os.path.join(root, rel))

    def judge_fn(rel):
        notes = ("Judge ONE voice-over take of line %s. Expected words (caption spelling): \"%s\". Text sent to the "
                 "voice: \"%s\". Wanted delivery: %s" % (lid, l["text"], tts, style or "natural and warm"))
        return judging.judge_item(root, "voice", [os.path.join(root, rel)], notes, lid)

    def install(rel):
        final = os.path.join(D, "lines", "%s.wav" % lid)
        os.makedirs(os.path.join(root, D, "lines"), exist_ok=True)
        ff.run(["-i", os.path.join(root, rel), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
                os.path.join(root, final)])
        return final

    return takes.run_item(root, D, lid, generate, check_local, judge_fn if judge else None, install, prompt_hash=ph,
                          extra=extra, fix=fix, log=log)


# ---------------------------------------------------------------- timeline
def place(root, log=print):
    """Trim each chosen take, place it on the film timeline -> audio/vo.wav + audio/vo_timing.json."""
    sp = screenplay.load(root)
    ms = store.media_settings(root)
    reg = store.load_registry(root, D)
    placed, inputs, warn = [], [], []
    prev_end = 0.0
    for l in sp.lines:
        it = reg["items"].get(l["id"], {})
        src = it.get("file")
        if not src or not os.path.exists(os.path.join(root, src)):
            raise UsageError("%s has no chosen take yet: python3 scripts/bb.py voice takes" % l["id"])
        trimmed = os.path.join(D, "placed", "%s.wav" % l["id"])
        os.makedirs(os.path.join(root, D, "placed"), exist_ok=True)
        trim = ("silenceremove=start_periods=1:start_duration=0:start_threshold=-45dB,areverse,"
                "silenceremove=start_periods=1:start_duration=0:start_threshold=-45dB,areverse,"
                "adelay=30:all=1,apad=pad_dur=0.12")
        ff.run(["-i", os.path.join(root, src), "-af", trim, "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
                os.path.join(root, trimmed)])
        dur = ff.duration(os.path.join(root, trimmed))
        if l.get("at") is not None:
            start = float(l["at"])
        elif l.get("shot"):
            try:
                start = sp.shot(l["shot"])["start"] + float(ms["voice_onset"])
            except UsageError:
                start = prev_end + float(ms["line_gap"])
        else:
            start = prev_end + float(ms["line_gap"])
        if placed and start < prev_end + 0.05:
            moved = round(prev_end + float(ms["line_gap"]), 3)
            warn.append("%s was due at %.2fs, but %s ends at %.2fs: moved to %.2fs"
                        % (l["id"], start, placed[-1]["id"], prev_end, moved))
            start = moved
        start = round(max(0.0, start), 3)
        end = round(start + dur, 3)
        slot_end = sp.line_slot_end(l)
        over = round(end - slot_end, 3) if slot_end is not None and end > slot_end + 0.1 else 0.0
        if over:
            warn.append("%s runs %.2fs past its end (%.2fs): shorten the line, move the cut, or start it earlier"
                        % (l["id"], over, slot_end))
        if end > sp.duration:
            warn.append("%s ends at %.2fs, after the film ends (%.2fs)" % (l["id"], end, sp.duration))
        placed.append({"id": l["id"], "shot": l.get("shot"), "text": l["text"], "tts": l["tts"], "take": it.get("take"),
                       "file": trimmed, "start": start, "end": end, "slot_end": slot_end, "overrun": over})
        inputs.append((trimmed, start))
        prev_end = end
    out = os.path.join("audio", "vo.wav")
    args = ["-f", "lavfi", "-t", "%.3f" % sp.duration, "-i", "anullsrc=r=48000:cl=mono"]
    chains, labels = [], ["[0:a]"]
    for i, (f, start) in enumerate(inputs):
        args += ["-i", os.path.join(root, f)]
        ms_delay = int(round(start * 1000))
        chains.append("[%d:a]aformat=sample_rates=48000:channel_layouts=mono,adelay=%d:all=1[v%d]" % (i + 1, ms_delay,
                                                                                                       i))
        labels.append("[v%d]" % i)
    fc = ";".join(chains + ["%s%s[out]" % ("".join(labels), ff.amix(len(labels), "first"))])
    ff.run(args + ["-filter_complex", fc, "-map", "[out]", "-t", "%.3f" % sp.duration, "-ar", "48000", "-ac", "1",
                   "-c:a", "pcm_s16le", os.path.join(root, out)])
    timing = {"duration": sp.duration, "voice": voice_name(root), "lines": placed, "warnings": warn,
              "time": util.now()}
    util.write_json(os.path.join(root, "audio", "vo_timing.json"), timing)
    for p in placed:
        log("  %s %6.2f-%6.2f  %s" % (p["id"], p["start"], p["end"], p["text"]))
    for w in warn:
        log("  ! " + w)
    return timing


def status(root):
    return store.load_registry(root, D)
