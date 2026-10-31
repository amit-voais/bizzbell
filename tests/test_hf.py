"""Version B, offline: formats, screenplay reading, the composition builder, the gate checks, frame comparison.

No Node, no network, no spend. The real HyperFrames render is in test_hf_render.py."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import BB, REPO, TMP_ROOT

from bizzbell import cli, gate, mock_server, project, util
from bizzbell.errors import ConfigError, UsageError
from bizzbell.hf import compose, formats, icons, qa, repeat, runner, screenplay

HAS_FFMPEG = bool(shutil.which("ffmpeg") or os.path.exists("/opt/homebrew/bin/ffmpeg"))
EMOJI = re.compile("[%s-%s%s-%s]" % (chr(0x1F300), chr(0x1FAFF), chr(0x2600), chr(0x27BF)))

SCREENPLAY = {
    "title": "Morning loaf", "duration": 3, "fps": 30,
    "shots": [
        {"id": "S01", "start": 0, "end": 1.5, "kind": "live", "source": "keyframe", "camera": "slow push-in",
         "lines": ["L01"]},
        {"id": "G02", "start": 1.5, "end": 3, "kind": "graphic",
         "graphic": {"type": "endcard", "title": "Corner Bakery", "subtitle": "Open at 7", "cta": "Order today"},
         "lines": ["L02"]},
    ],
    "rows": [
        {"t": 0, "shot": "S01", "vo": "ताज़ा ब्रेड", "caption": "Fresh bread, every morning"},
        {"t": 1, "shot": "S01", "vo": "ताज़ा ब्रेड", "caption": "Fresh bread, every morning"},
        {"t": 2, "shot": "G02", "vo": "आज ही", "caption": "Order today"},
    ],
    "lines": [{"id": "L01", "shot": "S01", "at": 0.1, "end": 1.4, "text": "Fresh bread, every morning"},
              {"id": "L02", "shot": "G02", "at": 1.6, "end": 2.8, "text": "Order today"}],
}


def make_project(base, name="hfp", sp=None, keyframe=True, audio=True):
    """A Version B-ready project: screenplay.json, a 9:16 keyframe PNG and a short voice WAV."""
    root = project.init(os.path.join(base, name), "A 3 s reel for a corner bakery", lang="hinglish")
    util.write_json(os.path.join(root, "screenplay.json"), sp or SCREENPLAY)
    if keyframe:
        with open(os.path.join(root, "keyframes", "S01.png"), "wb") as f:
            f.write(mock_server.png(90, 160, (182, 120, 60)))
    if audio:
        with open(os.path.join(root, "audio", "vo.wav"), "wb") as f:
            f.write(mock_server.wav(3.0, 330.0))
    return root


class TempDirCase(unittest.TestCase):
    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        self.tmp = tempfile.mkdtemp(dir=TMP_ROOT)
        self._env = dict(os.environ)
        os.environ["HOME"] = os.path.join(self.tmp, "home")        # keep user settings out of the build
        os.makedirs(os.environ["HOME"])

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)


class FormatTests(unittest.TestCase):
    def test_names_and_lists(self):
        self.assertEqual(formats.name("9:16"), "9x16")
        self.assertEqual(formats.name("16X9"), "16x9")
        self.assertEqual(formats.parse_list(""), ["9x16", "1x1", "16x9", "4x5"])
        self.assertEqual(formats.parse_list("16:9,9:16"), ["9x16", "16x9"])
        with self.assertRaises(UsageError):
            formats.name("2:3")

    def test_safe_boxes_inside_frames(self):
        for r, f in formats.FORMATS.items():
            l, t, rr, b = formats.safe_box(r)
            self.assertTrue(0 < l < rr < f["w"] and 0 < t < b < f["h"], r)
        self.assertEqual(formats.safe_box("9:16")[3], 1536)       # bottom 20 % kept clear of Reels UI

    def test_icons_are_svg(self):
        s = icons.svg("gift")
        self.assertTrue(s.startswith("<svg") and "currentColor" in s)
        self.assertEqual(icons.svg("offer"), icons.svg("gift"))
        self.assertEqual(icons.svg("nope"), "")


class ScreenplayTests(TempDirCase):
    def test_shots_captions_and_audio(self):
        root = make_project(self.tmp)
        plan = screenplay.load(root)
        self.assertEqual(plan["duration"], 3.0)
        self.assertEqual([s["kind"] for s in plan["shots"]], ["image", "graphic"])
        self.assertTrue(plan["shots"][0]["image"].endswith("keyframes/S01.png"))
        self.assertEqual(plan["shots"][0]["camera"], "push")
        self.assertEqual(plan["shots"][1]["graphic"]["type"], "endcard")
        self.assertFalse(plan["shots"][1]["captions"])          # no captions over the end card by default
        self.assertEqual(plan["caption_source"], "screenplay rows (caption)")
        self.assertEqual(" ".join(w["text"] for w in plan["words"]), "Fresh bread, every morning")
        self.assertTrue(plan["audio"]["vo"].endswith("audio/vo.wav"))
        self.assertEqual(plan["warnings"], [])

    def test_caption_sources_in_order(self):
        root = make_project(self.tmp)
        util.write_json(os.path.join(root, "audio", "vo_timing.json"),
                        {"lines": [{"id": "L01", "start": 0.3, "end": 1.2, "text": "Fresh bread"}]})
        plan = screenplay.load(root)
        self.assertEqual(plan["caption_source"], "audio/vo_timing.json")
        self.assertAlmostEqual(plan["words"][0]["start"], 0.3)
        util.write_json(os.path.join(root, "audio", "words.json"),
                        [{"word": "ताज़ा", "start": 0.3, "end": 0.6}])           # Devanagari: not on screen
        self.assertEqual(screenplay.load(root)["caption_source"], "audio/vo_timing.json")
        util.write_json(os.path.join(root, "audio", "words.json"),
                        {"words": [{"word": "Fresh", "start": 0.3, "end": 0.6}]})
        self.assertEqual(screenplay.load(root)["caption_source"], "audio/words.json")

    def test_lines_then_vo_fallbacks(self):
        sp = json.loads(json.dumps(SCREENPLAY))
        for r in sp["rows"]:
            r.pop("caption")
        root = make_project(self.tmp, sp=sp)
        plan = screenplay.load(root)
        self.assertEqual(plan["caption_source"], "screenplay lines")
        sp.pop("lines")
        util.write_json(os.path.join(root, "screenplay.json"), sp)
        self.assertEqual(screenplay.load(root)["caption_source"], "screenplay rows (vo)")

    def test_rows_only_and_missing_keyframe(self):
        sp = {"duration": 4, "rows": [{"t": 0, "shot": "A"}, {"t": 1, "shot": "A"}, {"t": 2, "shot": "B",
                                                                                      "camera": "locked off"},
                                      {"t": 3, "shot": "B"}]}
        root = make_project(self.tmp, sp=sp, keyframe=False)
        plan = screenplay.load(root)
        self.assertEqual([(s["id"], s["start"], s["end"]) for s in plan["shots"]], [("A", 0, 2), ("B", 2, 4)])
        self.assertEqual(plan["shots"][1]["camera"], "still")
        self.assertEqual(len(plan["warnings"]), 2)
        self.assertEqual(plan["caption_source"], "none")

    def test_overlays_and_errors(self):
        sp = dict(SCREENPLAY, overlays=[{"shot": "S01", "text": "Since 1998"}, {"start": 9, "end": 10, "text": "x"}])
        root = make_project(self.tmp, sp=sp)
        self.assertEqual([o["text"] for o in screenplay.load(root)["overlays"]], ["Since 1998"])
        os.remove(os.path.join(root, "screenplay.json"))
        with self.assertRaises(UsageError):
            screenplay.load(root)

    def test_chunks(self):
        words = screenplay.spread_words(0, 2, "one two three four five") + \
            screenplay.spread_words(2, 3, "six", line=1)
        chunks = screenplay.chunk(words, max_words=3, max_chars=40)
        self.assertEqual([[w["text"] for w in c["words"]] for c in chunks],
                         [["one", "two", "three"], ["four", "five"], ["six"]])
        for a, b in zip(chunks, chunks[1:]):
            self.assertLessEqual(a["end"], b["start"] + 1e-9)
        stop = screenplay.chunk(screenplay.spread_words(0, 2, "Wait, look here"), 3, 40)
        self.assertEqual([len(c["words"]) for c in stop], [1, 2])


class ComposeTests(TempDirCase):
    def _page(self, root, ratio):
        return util.read_text(os.path.join(root, "hf", ratio, "index.html"))

    def test_build_every_ratio(self):
        root = make_project(self.tmp)
        b = compose.build(root)
        self.assertEqual(sorted(b["ratios"]), ["16x9", "1x1", "4x5", "9x16"])
        for r, f in formats.FORMATS.items():
            page = self._page(root, r)
            self.assertIn('data-width="%d" data-height="%d"' % (f["w"], f["h"]), page)
            self.assertIn('data-composition-id="bizzbell-b"', page)
            self.assertIn('data-duration="3.0"', page)
            self.assertNotIn("{{", page)
            self.assertIsNone(EMOJI.search(page), r)
            self.assertIn('<audio id="bb-vo" src="assets/vo.wav"', page)
            self.assertTrue(os.path.isfile(os.path.join(root, "hf", r, "assets", "S01.png")))
            self.assertIn("Corner Bakery", page)
            self.assertIn("Order today", page)
            self.assertIn("<svg", page)                              # CTA arrow is an SVG icon
            plan = json.loads(re.search(r'id="bb-plan">(.*?)</script>', page, re.S).group(1).replace("<\\/", "</"))
            sels = [a["sel"] for a in plan["anims"]]
            self.assertEqual(len(sels), len(set(sels)), "one animation per element, so fills never fight")
            for a in plan["anims"]:
                offs = [k["offset"] for k in a["kf"] if "offset" in k]
                self.assertEqual(offs, sorted(offs))
                self.assertTrue(re.match(r"^#[A-Za-z0-9_-]+$", a["sel"]))
                self.assertIn('id="%s"' % a["sel"][1:], page)
            for m in re.finditer(r'<[^>]*data-bb-text[^>]*>', page):
                self.assertIn("id=", m.group(0))
        self.assertNotIn("Noto+Sans+Devanagari", self._page(root, "9x16"))     # no Devanagari on screen here
        self.assertEqual(util.read_json(os.path.join(root, "hf", "build.json"))["shot_times"],
                         [[0, 1.5], [1.5, 3]])

    def test_laid_out_again_per_ratio(self):
        root = make_project(self.tmp)
        compose.build(root)
        self.assertIn('class="bb-still bb-contain"', self._page(root, "16x9"))   # 9:16 still shown whole, blur behind
        self.assertNotIn('class="bb-still bb-contain"', self._page(root, "1x1"))  # filled: an image has no text
        v9 = re.search(r"--sb: (\d+)px", self._page(root, "9x16")).group(1)
        v16 = re.search(r"--sb: (\d+)px", self._page(root, "16x9")).group(1)
        self.assertEqual((int(v9), int(v16)), (formats.safe_box("9x16")[3], formats.safe_box("16x9")[3]))

    def test_devanagari_font_and_captions_sidecar(self):
        sp = json.loads(json.dumps(SCREENPLAY))
        sp["shots"][1]["graphic"]["subtitle"] = "हर सुबह"
        root = make_project(self.tmp, sp=sp)
        compose.build(root, "9:16")
        page = self._page(root, "9x16")
        self.assertIn("family=Noto+Sans+Devanagari", page)
        self.assertIn('"Kohinoor Devanagari"', page)
        ass = util.read_text(os.path.join(root, "out", "B", "captions.ass"))
        self.assertIn("Dialogue: 0,0:00:00.00", ass)
        self.assertIn("Fresh bread,", ass)

    def test_hash_follows_content(self):
        root = make_project(self.tmp)
        h1 = compose.build(root, "9:16")["ratios"]["9x16"]["hash"]
        self.assertEqual(compose.build(root, "9:16")["ratios"]["9x16"]["hash"], h1)
        sp = json.loads(json.dumps(SCREENPLAY))
        sp["shots"][1]["graphic"]["cta"] = "Visit today"
        util.write_json(os.path.join(root, "screenplay.json"), sp)
        self.assertNotEqual(compose.build(root, "9:16")["ratios"]["9x16"]["hash"], h1)

    def test_brand_colours_stay_readable(self):
        b = compose.brand({"brand": {"colors": {"ink": "#777777", "paper": "#888888", "accent": "#FFFF00"}}})
        self.assertGreaterEqual(compose.contrast(b["c"]["ink"], b["c"]["paper"]), 7)
        self.assertGreaterEqual(compose.contrast(b["c"]["cap_hl"], b["c"]["ink"]), 4.5)
        self.assertGreaterEqual(compose.contrast(b["c"]["accent_ink"], b["c"]["paper"]), 3.0)

    def test_fit_shrinks_long_text(self):
        self.assertEqual(compose.fit("Hi", 96, 900, 400), 96)
        self.assertLess(compose.fit("Supercalifragilisticexpialidocious", 96, 600, 400), 40)

    def test_image_size(self):
        p = os.path.join(self.tmp, "x.png")
        with open(p, "wb") as f:
            f.write(mock_server.png(33, 44))
        self.assertEqual(compose.image_size(p), (33, 44))
        self.assertIsNone(compose.image_size(os.path.join(self.tmp, "none.png")))


class RunnerTests(TempDirCase):
    def test_pin_from_settings(self):
        root = make_project(self.tmp)
        self.assertEqual(runner.pin(root), project.HYPERFRAMES_VERSION)
        project.update_settings(root, lambda s: s.update({"hyperframes": {"version": "latest"}}))
        with self.assertRaises(ConfigError):
            runner.pin(root)
        ok, why = runner.available(root)
        self.assertFalse(ok)
        self.assertIn("exact version", why)

    def test_quiet_env(self):
        e = runner.env()
        self.assertEqual(e["HYPERFRAMES_NO_TELEMETRY"], "1")
        self.assertEqual(e["DO_NOT_TRACK"], "1")


class GateCheckTests(TempDirCase):
    """hf_text_fits / hf_frames_repeatable read out/B/qa.json and trust it only for the current composition."""

    def _ctx(self, root):
        return gate.GateContext(root, "video_b", gate.load_rubric(root, "video_b"))

    def _qa(self, root, text_ok=True, repeat_ok=True, ratios=("9x16", "1x1", "16x9")):
        compose.build(root, list(ratios))
        recs = {}
        for r in ratios:
            recs[r] = {"hash": qa.current_hash(root, r), "text_ok": text_ok,
                       "hf_check": {"ok": text_ok, "text": [], "errors": []},
                       "bounds": {"ok": text_ok, "checked": 6, "issues": [] if text_ok else [
                           {"code": "outside_safe_zone", "el": "#cap-000-box", "t": 1.2}]},
                       "repeat": {"ok": repeat_ok, "times": [0.75, 2.25], "differing": [] if repeat_ok else [0.75]},
                       "repeat_ok": repeat_ok, "video": None}
        util.write_json(qa.qa_path(root), {"pin": "0.8.150", "ratios": recs})

    def test_registered_and_in_rubric(self):
        names = gate.registered_checks()
        self.assertIn("hf_text_fits", names)
        self.assertIn("hf_frames_repeatable", names)
        r = gate.load_rubric(None, "video_b")
        self.assertTrue({"hf_text_fits", "hf_frames_repeatable"} <= {q.get("check") for q in r["questions"]})

    def test_missing_qa(self):
        root = make_project(self.tmp)
        checks = gate.registered_checks()
        self.assertEqual(checks["hf_text_fits"](self._ctx(root))[0], "no")
        self.assertEqual(checks["hf_frames_repeatable"](self._ctx(root))[0], "no")

    def test_pass_fail_and_stale(self):
        root = make_project(self.tmp)
        checks = gate.registered_checks()
        self._qa(root)
        self.assertEqual(checks["hf_text_fits"](self._ctx(root))[0], "yes")
        self.assertEqual(checks["hf_frames_repeatable"](self._ctx(root))[0], "yes")
        self._qa(root, text_ok=False, repeat_ok=False)
        ans, ev = checks["hf_text_fits"](self._ctx(root))
        self.assertEqual(ans, "no")
        self.assertIn("outside_safe_zone", ev)
        ans, ev = checks["hf_frames_repeatable"](self._ctx(root))
        self.assertEqual(ans, "no")
        self.assertIn("0.75", ev)
        self._qa(root)
        with open(os.path.join(root, "hf", "1x1", "index.html"), "a") as f:
            f.write("<!-- edited -->")
        ans, ev = checks["hf_text_fits"](self._ctx(root))
        self.assertEqual(ans, "no")
        self.assertIn("older than the composition", ev)

    def test_partial_rebuild_makes_other_sizes_stale(self):
        root = make_project(self.tmp)
        self._qa(root)
        sp = json.loads(json.dumps(SCREENPLAY))
        sp["shots"][1]["graphic"]["cta"] = "Visit today"
        util.write_json(os.path.join(root, "screenplay.json"), sp)
        compose.build(root, "9:16")                       # 1:1 and 16:9 still hold the old screenplay
        self.assertFalse(qa.built_from_latest(root, "1x1"))
        self.assertTrue(qa.built_from_latest(root, "9x16"))
        ans, ev = gate.registered_checks()["hf_text_fits"](self._ctx(root))
        self.assertEqual(ans, "no")
        self.assertIn("older screenplay", ev)

    def test_missing_required_ratio(self):
        root = make_project(self.tmp)
        self._qa(root, ratios=("9x16",))
        self.assertEqual(gate.registered_checks()["hf_text_fits"](self._ctx(root))[0], "no")


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg is not installed")
class RepeatCompareTests(TempDirCase):
    def _png(self, name, rgb, w=90, h=160):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(mock_server.png(w, h, rgb))
        return p

    def test_compare(self):
        a = self._png("a.png", (10, 20, 30))
        self.assertTrue(repeat.compare(a, self._png("b.png", (10, 20, 30)))["identical"])
        near = repeat.compare(a, self._png("c.png", (12, 21, 31)))      # bytes differ, pixels do not
        self.assertTrue(near["same"])
        self.assertFalse(near["identical"])
        far = repeat.compare(a, self._png("d.png", (200, 20, 30)))
        self.assertFalse(far["same"])
        self.assertGreater(far["changed_fraction"], 0.5)

    def test_sample_times_and_shuffle(self):
        ts = repeat.sample_times(3.0, [{"start": 0, "end": 1.5}, {"start": 1.5, "end": 3}], n=5)
        self.assertEqual(ts, sorted(ts))
        self.assertIn(0.75, ts)
        self.assertIn(2.25, ts)
        self.assertTrue(all(0 < t < 3 for t in ts))
        sh = repeat.shuffled(ts)
        self.assertEqual(sorted(sh), ts)
        self.assertNotEqual(sh, ts)


class CommandTests(TempDirCase):
    def test_discovered(self):
        self.assertIn("version_b", [m.NAME for m in cli.discover()])

    def test_build_from_the_cli(self):
        root = make_project(self.tmp)
        r = subprocess.run([sys.executable, BB, "version_b", "build", "-p", root, "--ratios", "9:16,1:1"],
                           capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("built Version B", r.stdout)
        self.assertTrue(os.path.isfile(os.path.join(root, "hf", "1x1", "index.html")))
        self.assertFalse(os.path.exists(os.path.join(root, "hf", "16x9")))

    def test_no_screenplay_is_a_usage_error(self):
        root = project.init(os.path.join(self.tmp, "empty"), "a brief")
        r = subprocess.run([sys.executable, BB, "version_b", "build", "-p", root], capture_output=True, text=True,
                           env=dict(os.environ))
        self.assertEqual(r.returncode, 2)
        self.assertIn("screenplay.json is missing", r.stderr)


class TemplateTests(unittest.TestCase):
    def test_template_files(self):
        for name in ("composition.html", "style.css", "motion.js", "README.md"):
            text = util.read_text(os.path.join(REPO, "hyperframes", name))
            self.assertTrue(text, name)
            self.assertIsNone(EMOJI.search(text), name)
        js = util.read_text(os.path.join(REPO, "hyperframes", "motion.js"))
        for banned in ("Date.now", "Math.random", "performance.now", "requestAnimationFrame", "fetch("):
            self.assertNotIn(banned, js.split("*/", 1)[1])


if __name__ == "__main__":
    unittest.main()
