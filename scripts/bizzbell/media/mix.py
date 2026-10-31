"""Stage 7, mix (ffmpeg only, no API call): VO on top, the bed ducked under it, then loudness.

1. Each stem is levelled first (VO about -18 LUFS, bed about -30 LUFS; bizzbell.json media.vo_lufs / bed_lufs).
2. The bed is ducked under the voice with sidechaincompress (the VO is the sidechain).
3. Two-pass loudnorm to -14 LUFS integrated with a -1.5 dBTP ceiling (so it stays <= -1 dBTP after AAC).
4. Verified after with ebur128 (true peak); the numbers go to audio/mix_report.json.

Output: audio/mix.wav (48 kHz stereo). Either stem may be missing (VO only, or music only)."""
import os

from .. import util
from ..errors import UsageError
from . import ff, screenplay, store

DUCK = "sidechaincompress=threshold=0.02:ratio=6:attack=15:release=300:makeup=1"


def build(root, log=print):
    """Make audio/mix.wav and audio/mix_report.json. Returns the report."""
    sp = screenplay.load(root)
    ms = store.media_settings(root)
    vo = os.path.join(root, "audio", "vo.wav")
    bed = os.path.join(root, "audio", "music_bed.wav")
    have_vo, have_bed = os.path.exists(vo), os.path.exists(bed)
    if not have_vo and not have_bed:
        raise UsageError("nothing to mix: make audio/vo.wav (bb voice place) and/or audio/music_bed.wav (bb music "
                         "make) first")
    d = sp.duration
    tmp = os.path.join(root, "audio", "_mix")
    os.makedirs(tmp, exist_ok=True)
    pre = os.path.join(tmp, "premix.wav")
    lvl = "loudnorm=I=%g:TP=-3:LRA=11"
    args, fc = [], []
    if have_vo:
        args += ["-i", vo]
    if have_bed:
        args += ["-i", bed]
    if have_vo and have_bed:
        fc = ["[0:a]aformat=sample_rates=48000:channel_layouts=stereo,%s,aresample=48000,asplit=2[vo][sc]"
              % (lvl % ms["vo_lufs"]),
              "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,%s,aresample=48000[bed]" % (lvl % ms["bed_lufs"]),
              "[bed][sc]%s[duck]" % DUCK,
              "[vo][duck]%s,apad,atrim=0:%.3f[out]" % (ff.amix(2, "longest"), d)]
    else:
        target = ms["vo_lufs"] if have_vo else ms["bed_lufs"] + 8
        fc = ["[0:a]aformat=sample_rates=48000:channel_layouts=stereo,%s,aresample=48000,apad,atrim=0:%.3f[out]"
              % (lvl % target, d)]
    ff.run(args + ["-filter_complex", ";".join(fc), "-map", "[out]", "-t", "%.3f" % d, "-ar", "48000", "-ac", "2",
                   "-c:a", "pcm_s16le", pre])
    out = os.path.join(root, "audio", "mix.wav")
    res = ff.loudnorm(pre, out, target_i=float(ms["target_lufs"]), target_tp=float(ms["true_peak"]))
    got = res["result"]
    ok = got["I"] is not None and abs(got["I"] - float(ms["target_lufs"])) <= 1.0 and got["TP"] is not None and \
        got["TP"] <= -1.0
    report = {"file": "audio/mix.wav", "duration": round(ff.duration(out), 3), "film_duration": d,
              "target": {"I": float(ms["target_lufs"]), "TP_max": -1.0, "TP_ceiling": float(ms["true_peak"])},
              "measured_before": res["measured"], "result": got, "passes": res["passes"], "ok": ok,
              "stems": {"vo": "audio/vo.wav" if have_vo else None,
                        "music": "audio/music_bed.wav" if have_bed else None},
              "ducking": DUCK if have_vo and have_bed else None, "time": util.now()}
    util.write_json(os.path.join(root, "audio", "mix_report.json"), report)
    log("mix: %.2f LUFS integrated, true peak %.2f dBTP, LRA %s  -> audio/mix.wav  %s"
        % (got["I"] if got["I"] is not None else float("nan"), got["TP"] if got["TP"] is not None else float("nan"),
           got.get("LRA"), "OK" if ok else "OUT OF RANGE (target -14 LUFS, <= -1 dBTP)"))
    return report
