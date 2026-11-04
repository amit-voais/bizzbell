"""The agent-facing text: rubrics validate and use registered checks, stage guides name real rubrics, SKILL.md
frontmatter is valid, every `bb` command the docs name exists, the example passes its local checks, and the
screenplay / text / media checks answer correctly."""
import argparse
import copy
import glob
import json
import os
import re
import shutil
import unittest

from helpers import REPO, MockCase

from bizzbell import cli, gate, ledger, project
from bizzbell.checks import media as media_checks, text_layers
from bizzbell.mock_server import mp4, wav

RUBRICS = os.path.join(REPO, "rubrics")
STAGES = os.path.join(REPO, "stages")
EXAMPLE = os.path.join(REPO, "examples", "bakery-diwali")
DOCS = [os.path.join(REPO, f) for f in ("SKILL.md", "README.md", "AGENTS.md")] + \
    sorted(glob.glob(os.path.join(STAGES, "*.md"))) + [os.path.join(EXAMPLE, "README.md")]
TEXT_LAYERS = ("research", "story", "humanize", "screenplay")
# Commands the spec names (stage 9 and the offline demo) that another part of the build adds. They may be missing
# only while commands/<name>.py does not exist; once it does, they are checked like every other command.
PENDING = set()     # commands named in the docs but not written yet (none left)


def copy_example(dst):
    """Copy examples/bakery-diwali (files and sub-folders) into dst."""
    for f in glob.glob(os.path.join(EXAMPLE, "*")):
        if os.path.isdir(f):
            shutil.copytree(f, os.path.join(dst, os.path.basename(f)), dirs_exist_ok=True)
        else:
            shutil.copy(f, dst)


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def rubric_files():
    return sorted(glob.glob(os.path.join(RUBRICS, "*.json")))


def frontmatter(text):
    """{key: value} of a simple YAML frontmatter block (one line per key), or None."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    out = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([a-z_-]+):\s*(.*)$", line)
        if not m:
            return None
        out[m.group(1)] = m.group(2).strip()
    return out


def doc_commands(text):
    """[(command, next_word_or_None)] for every `bb <cmd>` / `bb.py <cmd>` inside code spans or fenced blocks."""
    code = re.findall(r"```.*?```", text, re.S) + re.findall(r"`[^`\n]+`", re.sub(r"```.*?```", "", text, flags=re.S))
    out = []
    for chunk in code:
        for m in re.finditer(r"(?:\bbb\.py|(?<![\w/.])bb)\s+([a-z][a-z_]*)(?:[ \t]+([A-Za-z0-9_:.<\-]+))?", chunk):
            out.append((m.group(1), m.group(2)))
    return out


class RubricFiles(unittest.TestCase):
    def test_every_rubric_validates_against_the_core_schema(self):
        files = rubric_files()
        self.assertGreater(len(files), 10)
        for p in files:
            r = json.loads(read(p))
            gate.validate_rubric(r, where=p)
            name = os.path.basename(p)[:-5]
            if not name.startswith("_"):
                self.assertEqual(r["stage"], name, p)
                self.assertTrue(8 <= len(r["questions"]) <= 15, "%s has %d questions" % (p, len(r["questions"])))
                self.assertEqual(r.get("pass_score", 95), 95, p)
                self.assertTrue(any(q.get("hard") for q in r["questions"]), "%s has no hard question" % p)

    def test_expected_layers_have_rubrics(self):
        want = {"research", "story", "humanize", "screenplay", "characters", "keyframes", "clips", "voice", "music",
                "mix", "version_a", "video_b", "final"}
        have = {os.path.basename(p)[:-5] for p in rubric_files()}
        self.assertEqual(want - have, set())

    def test_every_rubric_is_reachable_from_the_cli(self):
        stage_arg = [a for a in sub_parser("gate")._actions if a.dest == "stage"][0]
        for p in rubric_files():
            name = os.path.basename(p)[:-5]
            if not name.startswith("_"):
                self.assertIn(name, stage_arg.choices or [name], "bb gate cannot reach %s" % name)

    def test_every_check_a_rubric_names_is_registered(self):
        checks = gate.registered_checks()
        for p in rubric_files():
            for q in json.loads(read(p))["questions"]:
                if q.get("check"):
                    self.assertIn(q["check"], checks, "%s %s names an unknown check" % (os.path.basename(p), q["id"]))

    def test_hard_rules_are_hard(self):
        def hard(name, words):
            qs = json.loads(read(os.path.join(RUBRICS, name + ".json")))["questions"]
            hits = [q for q in qs if all(w in q["text"].lower() for w in words)]
            self.assertTrue(hits and all(q.get("hard") for q in hits), "%s: %s should be hard" % (name, words))
        hard("screenplay", ["every second"])
        hard("screenplay", ["voice-over", "word for word"])
        hard("screenplay", ["logo"])
        hard("screenplay", ["research"])
        hard("keyframes", ["logo"])
        hard("characters", ["consent"])
        hard("music", ["vocals"])
        hard("voice", ["exactly"])
        hard("story", ["claim", "research"])


def sub_parser(name):
    ap = cli.build_parser()
    sub = [a for a in ap._actions if isinstance(a, argparse._SubParsersAction)][0]
    return sub.choices[name]


class StageGuides(unittest.TestCase):
    def test_every_stage_guide_names_an_existing_rubric(self):
        guides = sorted(glob.glob(os.path.join(STAGES, "*.md")))
        self.assertEqual(len(guides), 12)
        named = set()
        for g in guides:
            refs = re.findall(r"rubrics/([A-Za-z0-9_]+)\.json", read(g))
            if not os.path.basename(g).startswith(("00-", "10-")):      # no gate: the budget yes; analysis is local
                self.assertTrue(refs, "%s names no rubric" % g)
            for r in refs:
                self.assertTrue(os.path.exists(os.path.join(RUBRICS, r + ".json")), "%s names rubrics/%s.json" % (g, r))
            named.update(refs)
        missing = {os.path.basename(p)[:-5] for p in rubric_files() if not os.path.basename(p).startswith("_")} - named
        self.assertEqual(missing, set(), "rubrics no stage guide names")

    def test_skill_links_every_stage_guide(self):
        skill = read(os.path.join(REPO, "SKILL.md"))
        for g in glob.glob(os.path.join(STAGES, "*.md")):
            self.assertIn("stages/" + os.path.basename(g), skill)


class SkillFile(unittest.TestCase):
    def test_frontmatter(self):
        text = read(os.path.join(REPO, "SKILL.md"))
        fm = frontmatter(text)
        self.assertIsNotNone(fm, "SKILL.md needs a --- frontmatter block")
        self.assertEqual(fm.get("name"), "bizzbell")
        self.assertRegex(fm["name"], r"^[a-z0-9-]{1,64}$")
        desc = fm.get("description", "")
        self.assertTrue(0 < len(desc) <= 1024, "description must be 1-1024 characters")
        for word in ("video ad", "reel", "story film", "explainer"):
            self.assertIn(word, desc.lower())
        self.assertNotIn("<", desc)

    def test_skill_is_tight_and_has_the_permission_points(self):
        text = read(os.path.join(REPO, "SKILL.md"))
        self.assertLess(len(text.splitlines()), 250)
        for phrase in ("budget set", "logs in themselves", "CONSENT.md", "Never publish", "--extra",
                       "At most 3 restructure rounds", "95"):
            self.assertIn(phrase, text)

    def test_every_bb_command_in_the_docs_exists(self):
        names = {m.NAME: m for m in cli.discover()}
        for core in ("init", "status", "budget", "gate", "restructure", "doctor", "key", "mark", "mock"):
            self.assertIn(core, names)
        bad = []
        for p in DOCS:
            for cmd, nxt in doc_commands(read(p)):
                if cmd in PENDING and cmd not in names and not os.path.exists(
                        os.path.join(REPO, "scripts", "bizzbell", "commands", cmd + ".py")):
                    continue
                if cmd not in names:
                    bad.append("%s: bb %s" % (os.path.relpath(p, REPO), cmd))
                    continue
                pos = [a for a in sub_parser(cmd)._actions if not a.option_strings and a.dest != "help"]
                if pos and pos[0].choices and nxt and re.match(r"^[a-z][a-z0-9_]*$", nxt):
                    if nxt not in pos[0].choices:
                        bad.append("%s: bb %s %s (choices: %s)" % (os.path.relpath(p, REPO), cmd, nxt,
                                                                   ", ".join(sorted(pos[0].choices))))
        self.assertEqual(bad, [])


class Templates(unittest.TestCase):
    def test_screenplay_template_and_example_share_one_schema(self):
        tpl = json.loads(read(os.path.join(REPO, "templates", "screenplay.json")))
        ex = json.loads(read(os.path.join(EXAMPLE, "screenplay.json")))
        self.assertEqual(set(tpl) - {"_about"}, set(ex))
        self.assertEqual(set(tpl["bibles"]), {"characters", "locations", "props"})
        self.assertEqual(set(tpl["rows"][0]), set(ex["rows"][0]))
        self.assertEqual(set(tpl["lines"][0]), set(ex["lines"][0]))

    def test_template_files_exist(self):
        for f in ("brief.md", "research.md", "story.md", "story_humanized.md", "screenplay.md", "screenplay.json",
                  "bible.md", "CONSENT.md", "report.md"):
            self.assertTrue(os.path.exists(os.path.join(REPO, "templates", f)), f)


class ExampleProject(MockCase):
    def project(self):
        root = self.make_project("bakery")
        copy_example(root)
        return root

    def test_brief_template_is_used_by_init(self):
        root = self.make_project("tpl", budget=0, doctor=False)
        text = read(os.path.join(root, "brief.md"))
        self.assertIn("neighbourhood bakery", text)
        self.assertIn("Language: hinglish", text)
        self.assertIn("Must not say", text)

    def test_every_local_check_passes_on_the_example(self):
        root = self.project()
        for stage in TEXT_LAYERS:
            r = gate.load_rubric(root, stage)
            ctx = gate.GateContext(root, stage, r)
            for q in r["questions"]:
                if q.get("check"):
                    a = gate._run_check(ctx, q)
                    self.assertEqual(a["answer"], "yes", "%s %s: %s" % (stage, q["id"], a["evidence"]))

    def test_text_gates_pass_end_to_end_on_the_mock(self):
        root = self.project()
        for stage in TEXT_LAYERS:
            rec = gate.run(root, stage)
            self.assertTrue(rec["passed"], "%s: %s" % (stage, gate.format_result(rec)))
        self.assertEqual(project.next_stage(root), "characters")
        self.assertGreater(ledger.Ledger(root).summary()["spent_inr"], 0)


class ScreenplayChecks(MockCase):
    def setUp(self):
        super(ScreenplayChecks, self).setUp()
        self.root = self.make_project("sp", budget=0, doctor=False)
        copy_example(self.root)
        self.doc = json.loads(read(os.path.join(EXAMPLE, "screenplay.json")))

    def answer(self, check, doc=None, stage="screenplay", **args):
        if doc is not None:
            self.write(self.root, "screenplay.json", doc)
        r = gate.load_rubric(self.root, stage)
        ctx = gate.GateContext(self.root, stage, r)
        return gate._run_check(ctx, {"id": "X", "check": check, "args": args})

    def test_missing_second(self):
        d = copy.deepcopy(self.doc)
        d["rows"] = [r for r in d["rows"] if r["t"] != 7]
        a = self.answer("rows_cover_every_second", d)
        self.assertEqual(a["answer"], "no")
        self.assertIn("[7]", a["evidence"])

    def test_vo_changed_word(self):
        d = copy.deepcopy(self.doc)
        d["lines"][1]["text"] = d["lines"][1]["text"].replace("dabba", "box")
        a = self.answer("vo_word_for_word", d)
        self.assertEqual(a["answer"], "no")
        self.assertIn("dabba", a["evidence"])

    def test_long_shot(self):
        d = copy.deepcopy(self.doc)
        d["shots"][0]["end"] = 4.5
        self.assertNotEqual(self.answer("shot_lengths", d)["answer"], "yes")

    def test_prompt_asking_for_a_logo(self):
        d = copy.deepcopy(self.doc)
        d["shots"][3]["keyframe_prompt"] += " The bakery logo is printed on the box."
        a = self.answer("prompts_no_text", d)
        self.assertEqual(a["answer"], "no")
        self.assertIn("S04", a["evidence"])

    def test_negated_mentions_are_fine(self):
        d = copy.deepcopy(self.doc)
        d["shots"][0]["keyframe_prompt"] += " No text or logo anywhere, without any lettering."
        self.assertEqual(self.answer("prompts_no_text", d)["answer"], "yes")

    def test_unsourced_number_and_sample(self):
        d = copy.deepcopy(self.doc)
        d["shots"][7]["graphic"]["subtitle"] = "Loved by 5000 families"
        self.assertEqual(self.answer("numbers_sourced", d)["answer"], "no")
        d["shots"][7]["graphic"]["sample"] = True
        self.assertEqual(self.answer("numbers_sourced", d)["answer"], "yes")

    def test_long_caption(self):
        d = copy.deepcopy(self.doc)
        d["rows"][3]["caption"] = "x" * 60
        self.assertEqual(self.answer("captions_short", d)["answer"], "no")

    def test_bibles_must_match_the_md(self):
        d = copy.deepcopy(self.doc)
        d["bibles"]["characters"]["RANI"]["text"] += " Extra detail."
        self.assertEqual(self.answer("bibles_verbatim", d)["answer"], "no")

    def test_real_person_needs_consent(self):
        d = copy.deepcopy(self.doc)
        d["bibles"]["characters"]["RANI"]["real_person"] = True
        self.assertEqual(self.answer("consent_for_real_faces", d)["answer"], "no")
        self.write(self.root, "CONSENT.md", "Who: Rani\nFilm: Diwali reel\nChannels: Instagram\nHow long: 12 months\n"
                                            "Date agreed: 2026-10-20\n")
        self.assertEqual(self.answer("consent_for_real_faces")["answer"], "yes")

    def test_unknown_bible_in_a_shot(self):
        d = copy.deepcopy(self.doc)
        d["shots"][0]["characters"] = ["NOBODY"]
        self.assertEqual(self.answer("live_shots_complete", d)["answer"], "no")


class TextLayerChecks(MockCase):
    def setUp(self):
        super(TextLayerChecks, self).setUp()
        self.root = self.make_project("tl", budget=0, doctor=False)
        copy_example(self.root)

    def answer(self, check, stage, **args):
        r = gate.load_rubric(self.root, stage)
        return gate._run_check(gate.GateContext(self.root, stage, r), {"id": "X", "check": check, "args": args})

    def test_source_without_date(self):
        text = read(os.path.join(self.root, "research.md")).replace("read 2026-10-21", "read recently")
        self.write(self.root, "research.md", text)
        self.assertEqual(self.answer("sources_dated", "research")["answer"], "partly")

    def test_uncited_claim(self):
        text = read(os.path.join(self.root, "research.md")).replace("- C4: Orders are delivered in the city within "
                                                                    "2 days. [brief]", "- C4: Fastest in town.")
        self.write(self.root, "research.md", text)
        self.assertEqual(self.answer("claims_cited", "research")["answer"], "no")

    def test_wrapped_claim_keeps_its_citation(self):
        # a claim wrapped onto an indented continuation line used to lose its [S1] and fail hard question RS2
        text = read(os.path.join(self.root, "research.md")).replace(
            "- C4: Orders are delivered in the city within 2 days. [brief]",
            "- C4: Orders are delivered in the city\n  within 2 days. [brief]")
        self.write(self.root, "research.md", text)
        self.assertEqual(self.answer("claims_cited", "research")["answer"], "yes")

    def test_items_read_continuation_lines(self):
        lines = ["- C1: first part", "  second part [S1]", "    third part", "- C2: alone [S2]",
                 "  - nested item [S3]", "", "  after a blank line", "1. numbered", "\tcontinued [brief]"]
        self.assertEqual(text_layers._items(lines), ["C1: first part second part [S1] third part",
                                                    "C2: alone [S2]", "nested item [S3]",
                                                    "numbered continued [brief]"])

    def test_fillers(self):
        vo = "# H\n\n## Tone\n\nx\n\n## Voice-over\n\n- L01: %s\n"
        self.write(self.root, "story_humanized.md", vo % "Our cookies are fresh and made by hand every day.")
        self.assertEqual(self.answer("fillers_natural", "humanize")["answer"], "no")
        self.write(self.root, "story_humanized.md", vo % "Arre yaar umm matlab haan na yaar arre umm cookies.")
        self.assertEqual(self.answer("fillers_natural", "humanize")["answer"], "partly")
        hindi = ("अरे यार, दिवाली में बस पाँच दिन बचे हैं और गिफ़्ट का एक भी डब्बा रेडी नहीं है, "
                 "फिर बेकरी का बॉक्स मिला, ये तो घर जैसा है ना!")
        self.write(self.root, "story_humanized.md", vo % hindi)
        project.update_state(self.root, lambda st: st.update(lang="hi"))
        self.assertEqual(self.answer("fillers_natural", "humanize")["answer"], "yes")
        project.update_state(self.root, lambda st: st.update(lang="en"))
        self.write(self.root, "story_humanized.md", vo % "Our cookies are fresh.")
        self.assertEqual(self.answer("fillers_natural", "humanize")["answer"], "yes")

    def test_stage_direction_in_vo(self):
        self.write(self.root, "story_humanized.md", "## Voice-over\n\n- L01: (sighs) Diwali is close.\n")
        self.assertEqual(self.answer("no_stage_directions_in_vo", "humanize")["answer"], "no")


@unittest.skipUnless(media_checks.tool("ffmpeg") and media_checks.tool("ffprobe"), "needs ffmpeg")
class MediaChecks(MockCase):
    def setUp(self):
        super(MediaChecks, self).setUp()
        self.root = self.make_project("media", budget=0, doctor=False)
        self.write(self.root, "screenplay.json", {"duration": 2, "aspect": "9:16", "shots": []})

    def put(self, rel, data):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

    def answer(self, check, **args):
        r = {"stage": "x", "layer": {"kind": "media", "files": ["out/A/*.mp4"]},
             "questions": [{"id": "Q", "text": "?"}]}
        return gate._run_check(gate.GateContext(self.root, "x", r), {"id": "X", "check": check, "args": args})

    def test_video_checks(self):
        self.put("out/A/demo_A_9x16.mp4", mp4(seconds=2.0, width=144, height=256))
        self.assertEqual(self.answer("media_aspect")["answer"], "yes")
        self.assertEqual(self.answer("media_duration")["answer"], "yes")
        self.assertEqual(self.answer("has_audio_stream")["answer"], "yes")
        self.assertEqual(self.answer("no_black_frames")["answer"], "yes")
        self.put("out/A/demo_A_16x9.mp4", mp4(seconds=2.0, width=144, height=256))
        self.assertEqual(self.answer("media_aspect")["answer"], "no")

    def test_formats_and_share_copy(self):
        for f in ("9x16", "1x1", "16x9", "share"):
            self.put("out/B/demo_B_%s.mp4" % f, mp4(seconds=1.0))
        a = self.answer("formats_present")
        self.assertEqual(a["answer"], "yes", a["evidence"])
        self.assertIn("out/A", a["evidence"])
        os.remove(os.path.join(self.root, "out/B/demo_B_1x1.mp4"))
        self.assertEqual(self.answer("formats_present")["answer"], "no")

    def test_loudness_reading(self):
        self.put("audio/mix.wav", wav(seconds=2.0))
        a = self.answer("audio_loudness", files=["audio/mix.wav"])
        self.assertIn("LUFS", a["evidence"])
        self.assertEqual(self.answer("media_duration", files=["audio/mix.wav"])["answer"], "yes")


if __name__ == "__main__":
    unittest.main()
