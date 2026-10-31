"""Regression tests for the review findings: gates that passed with missing work, stage roll-up, the ledger under
kills and long text replies, stage order, file URLs, the loudness meter, stale sizes, voices, the estimate, and
the safety of downloads and child processes."""
import contextlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from helpers import BB, FAKE_KEY, REPO, SCRIPTS, TMP_ROOT
from test_media_base import SCREENPLAY, MediaCase

from bizzbell import cli, estimate, final, gate, hidrogen, ledger, mock_server, project, util
from bizzbell.checks import media as media_checks, text_layers
from bizzbell.errors import BudgetExceeded, OutOfOrder
from bizzbell.hf import audit, runner
from bizzbell.media import characters, ff, keyframes, layers, screenplay, store, voice


def _copy(d):
    return json.loads(json.dumps(d))


def _ctx(root, stage):
    return gate.GateContext(root, stage, gate.load_rubric(root, stage))


def _png(root, rel):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(b"\x89PNG fake " + rel.encode())
    return p


class CompletenessTests(MediaCase):
    """C-C1: a missing file, a too-long shot or a flagged item fails its gate outright."""

    def test_missing_keyframe_is_no(self):
        root = self.make_media_project(rubrics=False)
        _png(root, "keyframes/S01.png")
        ans, ev = gate.load_checks()["shot_files_exist"](_ctx(root, "keyframes"), folder="keyframes", ext=".png")
        self.assertEqual(ans, "no")
        self.assertIn("S02", ev)

    def test_one_long_shot_is_no(self):
        root = self.make_media_project(rubrics=False)
        sp = _copy(SCREENPLAY)
        sp["duration"] = 14
        sp["shots"][0]["end"] = 10
        sp["shots"][1]["start"], sp["shots"][1]["end"] = 10, 12
        sp["shots"][2]["start"], sp["shots"][2]["end"] = 12, 14
        self.write(root, "screenplay.json", sp)
        self.assertEqual(gate.load_checks()["shot_lengths"](_ctx(root, "screenplay"))[0], "no")

    def test_flagged_item_is_no(self):
        root = self.make_media_project(rubrics=False)
        reg = {"items": {"S01": {"status": "accepted"}, "S02": {"status": "flagged"}}}
        self.write(root, "keyframes/registry.json", reg)
        ans, ev = gate.load_checks()["none_flagged"](_ctx(root, "keyframes"), dir="keyframes")
        self.assertEqual(ans, "no")
        self.assertIn("S02", ev)

    def test_missing_sheet_is_no(self):
        root = self.make_media_project(rubrics=False)
        _png(root, characters.file_for("plate:GYM"))
        self.assertEqual(gate.load_checks()["sheets_cover_cast"](_ctx(root, "characters"))[0], "no")

    def test_completeness_questions_are_hard(self):
        want = {"keyframes": ("KF1", "KF14"), "clips": ("CL1", "CL12"), "characters": ("CH4",),
                "screenplay": ("SP3",), "voice": ("VO11",)}
        for stage, ids in want.items():
            qs = {q["id"]: q for q in util.read_json(os.path.join(REPO, "rubrics", stage + ".json"))["questions"]}
            for i in ids:
                self.assertTrue(qs[i].get("hard"), "%s %s must be hard" % (stage, i))

    def test_gate_fails_with_a_missing_keyframe(self):
        root = self.make_media_project(rubrics=False)
        _png(root, "keyframes/S01.png")
        self.write(root, "keyframes/prompts.json", {"S01": "x", "S02": "y"})
        rec = gate.run(root, "keyframes")
        self.assertFalse(rec["passed"])
        self.assertIn("KF1", rec["hard_failed"])


class RollupTests(MediaCase):
    """C-C2 and U-F3: the stage follows its sub-layers both ways; a changed layer leaves passed; bb mark <layer>."""

    def test_failed_sublayer_takes_stage_out_of_passed(self):
        root = self.make_media_project()
        for part in ("voice", "music", "mix"):
            project.mark_stage(root, part, "passed")
        self.assertEqual(layers.rollup(root, "mix"), "audio")
        self.assertEqual(project.stage_status(root, "audio"), "passed")
        project.mark_stage(root, "voice", "failed")
        layers.rollup(root, "voice")
        self.assertEqual(project.stage_status(root, "audio"), "failed")
        self.assertEqual(project.next_stage(root), "audio")

    def test_changed_layer_is_not_passed(self):
        root = self.make_media_project()
        _png(root, "keyframes/S01.png")
        _png(root, "keyframes/S02.png")
        project.mark_stage(root, "keyframes", "passed", layer=gate.snapshot(root, "keyframes"))
        self.assertEqual(project.stage_status(root, "keyframes"), "passed")
        os.remove(os.path.join(root, "keyframes/S02.png"))           # what bb keyframes reject does
        self.assertEqual(project.stage_status(root, "keyframes"), "changed")
        self.assertFalse(project.done("keyframes", "changed"))

    def test_new_files_do_not_make_a_layer_changed(self):
        root = self.make_media_project()
        _png(root, "keyframes/S01.png")
        project.mark_stage(root, "keyframes", "passed", layer=gate.snapshot(root, "keyframes"))
        _png(root, "keyframes/S02.png")
        self.assertEqual(project.stage_status(root, "keyframes"), "passed")

    def test_bb_mark_accepts_layer_names(self):
        root = self.make_media_project()
        for part in ("voice", "music"):
            project.mark_stage(root, part, "passed")
        project.mark_stage(root, "mix", "failed")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["mark", "mix", "passed", "-p", root, "--note", "accepted by the user"])
        self.assertEqual(code, 0)
        self.assertIn("stage audio: passed", out.getvalue())
        self.assertEqual(project.stage_status(root, "audio"), "passed")


class LedgerKillTests(MediaCase):
    """C-C3: a killed paid call does not leave a reservation that blocks the cap forever, nor count twice."""

    def _dead_pid(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        return p.pid

    def test_orphaned_pending_entry_becomes_uncertain_then_released_on_replay(self):
        root = self.make_project("led", budget=100)
        L = ledger.Ledger(root)
        eid = L.reserve("video", 40, ref="bb-key-1")
        d = util.read_json(L.path)
        d["entries"][eid - 1]["pid"] = self._dead_pid()
        util.write_json(L.path, d)
        s = L.summary()
        self.assertEqual(s["reserved_inr"], 0.0)
        self.assertEqual(s["spent_inr"], 40.0)                    # may have been charged: counted once, safely
        self.assertIsNone(L.check(60))
        L.reserve("video", 40, ref="bb-key-1")                     # the same take again, same Idempotency-Key
        s = L.summary()
        self.assertEqual(s["spent_inr"], 0.0)
        self.assertEqual(s["reserved_inr"], 40.0)
        self.assertEqual(L.entries()[0]["status"], "released")

    def test_sigterm_settles_the_reservation(self):
        root = self.make_project("term", budget=100)
        code = ("import sys, time, signal; sys.path.insert(0, %r)\n"
                "from bizzbell import cli, ledger\n"
                "signal.signal(signal.SIGTERM, cli._on_term)\n"
                "ledger.Ledger(%r).call('video', lambda: time.sleep(30), estimate_inr=40)\n" % (SCRIPTS, root))
        p = subprocess.Popen([sys.executable, "-c", code], stderr=subprocess.DEVNULL)
        L = ledger.Ledger(root)
        for _ in range(100):
            if L.entries():
                break
            time.sleep(0.05)
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=20)
        e = L.entries()[0]
        self.assertEqual(e["status"], "uncertain")
        self.assertEqual(L.summary()["reserved_inr"], 0.0)


class OrderTests(MediaCase):
    """C-C4: a paid stage does not spend while a layer it builds on has failed or was never gated."""

    def test_characters_refused_after_a_failed_screenplay(self):
        root = self.make_media_project()
        project.mark_stage(root, "screenplay", "failed")
        n0 = len(self.posts("/v1/images"))
        with self.assertRaises(OutOfOrder) as cm:
            characters.make(root, log=lambda *_: None)
        self.assertIn("screenplay (failed)", str(cm.exception))
        self.assertEqual(len(self.posts("/v1/images")), n0)
        self.assertEqual(ledger.Ledger(root).summary()["spent_inr"], 0.0)
        characters.make(root, dry_run=True, log=lambda *_: None)    # a dry run is still allowed

    def test_keyframes_need_characters(self):
        root = self.make_media_project()
        project.mark_stage(root, "characters", "made")
        with self.assertRaises(OutOfOrder):
            keyframes.make(root, log=lambda *_: None)


class CheapChecksTests(unittest.TestCase):
    """C-C5, C-C7, C-C8, U-F9, U-F6, U-F4, S-F3, S-F4: small units."""

    def test_file_url_encodes_hash_and_question_mark(self):
        url = audit.file_url("/tmp/promo #1/a?b/x.html")
        self.assertTrue(url.startswith("file:///"))
        self.assertIn("%231", url)
        self.assertIn("%3F", url)
        self.assertNotIn("#", url)

    def test_evidence_needs_every_quote(self):
        self.assertFalse(gate.evidence_found('"Diwali box" and "a fabricated claim never written"',
                                             "our Diwali box sale"))
        self.assertTrue(gate.evidence_found('"Diwali box" and "box sale"', "our Diwali box sale"))

    def test_negation_na_is_not_a_filler(self):
        self.assertEqual([m.group(1) for m in text_layers.TAG_NA.finditer("Umm, fees bhar ke na jaun toh?")], [])
        self.assertEqual([m.group(1) for m in text_layers.TAG_NA.finditer("Accha lagta hai na?")], ["na"])

    def test_previous_keyframe_only_from_the_same_place(self):
        data = _copy(SCREENPLAY)
        data["bibles"]["locations"]["HOME"] = {"name": "Home", "text": "HOME: a small bedroom at dawn."}
        data["shots"][1]["location"] = "HOME"
        sp = screenplay.Screenplay(data, aspect="9:16", lang="hinglish")
        reg = {"items": {"S01": {"status": store.GOOD[0], "file": __file__}}}
        self.assertIsNone(keyframes.previous_approved("/", sp, "S02", reg))
        data["shots"][1]["location"] = "GYM"
        sp = screenplay.Screenplay(data, aspect="9:16", lang="hinglish")
        self.assertEqual(keyframes.previous_approved("/", sp, "S02", reg), __file__)

    def test_default_audition_has_three_voices_of_the_narrators_kind(self):
        got = voice.default_candidates("rohan")
        self.assertEqual(len(got), 3)
        self.assertEqual(got[0], "rohan")
        self.assertTrue(all(voice.stock_gender(v) == "male" for v in got))
        self.assertEqual(voice.default_candidates("priya", "male")[1:], ["arjun", "dev"])

    def test_npx_environment_has_no_hidrogen_key(self):
        old = dict(os.environ)
        try:
            os.environ["HIDROGEN_API_KEY"] = FAKE_KEY
            os.environ["HIDROGEN_API_URL"] = "http://127.0.0.1:1"
            e = runner.env()
            self.assertFalse([k for k in e if k.startswith("HIDROGEN_")])
            self.assertEqual(e.get("HYPERFRAMES_NO_TELEMETRY"), "1")
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_download_refuses_file_and_plain_http(self):
        for url in ("file:///etc/hosts", "http://example.com/a.png", "ftp://example.com/a"):
            with self.assertRaises(hidrogen.HidrogenError):
                hidrogen.download(url)


class BrowserPathTests(unittest.TestCase):
    """U-F1: a system Google Chrome from `browser path` is replaced by HyperFrames' chrome-headless-shell."""

    def test_full_chrome_triggers_a_headless_shell_download(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        tmp = tempfile.mkdtemp(dir=TMP_ROOT)
        self.addCleanup(shutil.rmtree, tmp, True)
        full = os.path.join(tmp, "Google Chrome")
        shell = os.path.join(tmp, "chrome-headless-shell")
        for p in (full, shell):
            open(p, "w").close()
        calls = []
        state = {"downloaded": False}

        class R(object):
            def __init__(self, out):
                self.stdout, self.stderr, self.returncode = out, "", 0

        def fake_run(args, root=None, timeout=0, check=True):
            calls.append(list(args))
            if args[:2] == ["browser", "ensure"]:
                state["downloaded"] = "--force" in args
                return R("")
            return R((shell if state["downloaded"] else full) + "\n")
        old_run, old_env = runner.run, os.environ.pop("HYPERFRAMES_BROWSER_PATH", None)
        runner._CACHE.pop("browser", None)
        runner.run = fake_run
        try:
            self.assertEqual(runner.browser_path(), shell)
        finally:
            runner.run = old_run
            runner._CACHE.pop("browser", None)
            if old_env is not None:
                os.environ["HYPERFRAMES_BROWSER_PATH"] = old_env
        self.assertIn(["browser", "ensure", "--force"], calls)


class StaleSizesTests(MediaCase):
    """C-C6: sizes older than the master (A) or the latest build (B) are made again by bb final."""

    def test_stale_sizes(self):
        root = self.make_media_project()
        slug = project.load_state(root)["slug"]
        for v, tag in (("A", "1x1"), ("A", "9x16"), ("B", "1x1"), ("B", "9x16")):
            self.write(root, "out/%s/%s_%s_%s.mp4" % (v, slug, v, tag), "x")
        self.write(root, "hf/build.json", {"plan": "p"})
        old = time.time() - 100
        os.utime(os.path.join(root, "out/A/%s_A_1x1.mp4" % slug), (old, old))
        os.utime(os.path.join(root, "out/B/%s_B_1x1.mp4" % slug), (old, old))
        os.utime(os.path.join(root, "out/B/%s_B_9x16.mp4" % slug), (old, old))
        self.assertEqual(final.stale_sizes(root, "A"), ["1:1"])
        self.assertEqual(sorted(final.stale_sizes(root, "B")), ["1:1", "9:16"])


class AspectTests(MediaCase):
    """C-C7: media_aspect checks the aspect the generators used (project.json), not a stale screenplay one."""

    def test_project_aspect_wins(self):
        root = self.make_media_project()
        project.update_state(root, lambda st: st.__setitem__("aspect", "16:9"))
        ctx = _ctx(root, "keyframes")
        self.assertEqual(media_checks._target_aspect(ctx, os.path.join(root, "keyframes/S01.png")), "16:9")


@unittest.skipUnless(media_checks.tool("ffmpeg"), "ffmpeg is not installed")
class LoudnessMeterTests(MediaCase):
    """U-F2: the mix gate reads loudness with the same meter bb mix uses."""

    def test_gate_meter_is_the_mix_meter(self):
        root = self.make_media_project()
        out = os.path.join(root, "audio", "tone.wav")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        ff.run(["-f", "lavfi", "-i", "sine=f=220:d=4", "-af", "volume='if(between(t,1,2),0,1)':eval=frame",
                "-ar", "48000", "-ac", "2", out])
        m = ff.loudness(out)
        self.assertEqual(media_checks.loudness(out), (m["I"], m["TP"]))


class EstimateTests(MediaCase):
    """U-F5: bb budget estimate prices every stage before the budget, for free."""

    def test_estimate_from_seconds_and_from_the_screenplay(self):
        root = self.make_project("est", budget=0)
        est = estimate.estimate(root, seconds=20)
        self.assertEqual([r["stage"] for r in est["rows"]],
                         ["research", "story", "humanize", "screenplay", "characters", "keyframes", "audio",
                          "video_a", "video_b", "final"])
        self.assertGreater(est["worst"], est["likely"])
        self.assertGreater(est["likely"], 0)
        self.assertEqual(est["source"], "quote")
        self.assertEqual(ledger.Ledger(root).summary()["spent_inr"], 0.0)
        self.write(root, "screenplay.json", SCREENPLAY)
        est = estimate.estimate(root)
        self.assertEqual(est["counts"]["live"], 2)
        self.assertEqual(est["counts"]["lines"], 3)
        self.assertIn("characters", estimate.format_estimate(est))


class ChatCapTests(MediaCase):
    """S-F1: a long text reply cannot take the spend past the cap: chat calls are quoted (or reserved at their
    worst case) before they are sent."""

    def test_expensive_judge_is_refused_before_it_is_sent(self):
        old = mock_server.PAISE["chat"]
        mock_server.PAISE["chat"] = 6000                     # INR 60 per reply
        try:
            root = self.make_project("cap", budget=10)
            for f in ("brief.md", "research.md"):
                with open(os.path.join(REPO, "examples", "bakery-diwali", f), encoding="utf-8") as src:
                    self.write(root, f, src.read())
            n0 = len(self.posts("/v1/chat"))
            with self.assertRaises(BudgetExceeded):
                gate.run(root, "research")
            self.assertEqual(len(self.posts("/v1/chat")), n0)
            self.assertLessEqual(ledger.Ledger(root).summary()["spent_inr"], 10.0)
        finally:
            mock_server.PAISE["chat"] = old

    def test_unquoted_chat_reserves_its_worst_case(self):
        root = self.make_project("cap2", budget=100)
        inr, src = ledger.Ledger(root).estimate("chat", None, 1, {"max_tokens": 8192, "chars": 2000},
                                                ask_quote=False)
        self.assertEqual(src, "rate")
        self.assertGreaterEqual(inr, 20.0)


class KeyPipeTests(unittest.TestCase):
    """U-F10: a piped key is read without getpass's echo warning."""

    def test_piped_key_has_no_echo_warning(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        home = tempfile.mkdtemp(dir=TMP_ROOT)
        self.addCleanup(shutil.rmtree, home, True)
        env = dict(os.environ, HOME=home)
        env.pop("HIDROGEN_API_KEY", None)
        r = subprocess.run([sys.executable, BB, "key"], input=FAKE_KEY + "\n", capture_output=True, text=True,
                           env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("GetPassWarning", r.stderr)
        self.assertNotIn("echoed", r.stderr)
        self.assertNotIn(FAKE_KEY, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
