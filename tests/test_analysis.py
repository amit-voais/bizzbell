"""Stage 10, bb analyse: the three tools on synthetic fixtures, Hindi and Hinglish, bad files, and that the stage
order, the budget and bb status stay untouched."""
import json
import os
import subprocess
import sys
import unittest

from helpers import BB, MockCase, REPO

from bizzbell.analysis import edit, outliers, retention, text
from bizzbell.errors import BBError, UsageError

FIX = os.path.join(REPO, "tests", "fixtures", "analysis")
SRT = os.path.join(FIX, "hinglish.srt")
SHORT = os.path.join(FIX, "retention_short_seconds.csv")
PERCENT = os.path.join(FIX, "retention_percent.csv")
COLLECTED = os.path.join(FIX, "outliers.json")


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def bb(env, *args):
    r = subprocess.run([sys.executable, BB] + list(args), capture_output=True, text=True, env=env, timeout=60,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout, r.stderr


class Tokeniser(unittest.TestCase):
    def test_devanagari_keeps_vowel_signs(self):
        self.assertEqual(text.words("नमस्ते दोस्तों, की।"), ["नमस्ते", "दोस्तों", "की"])

    def test_spelling_variants_compare_equal(self):
        self.assertEqual(text.words("हाँ"), text.words("हां"))
        self.assertEqual(text.words("क्‍ष"), text.words("क्ष"))
        self.assertEqual(text.words("ज़"), text.words("ज़"))

    def test_other_scripts(self):
        self.assertEqual(text.words("déjame Çok привет don't"), ["déjame", "çok", "привет", "don't"])
        self.assertEqual(len(text.words("今天天气")), 4)

    def test_filler_cues_in_both_scripts(self):
        for line in ("umm", "Ummm, matlab", "yaani", "haan haan", "na", "arre", "उम्म", "मतलब", "यानी", "हाँ", "ना",
                     "अरे", "so yeah", "you know"):
            self.assertTrue(text.only_filler(text.words(line)), line)
        for line in ("matlab yeh box", "हम बेकरी", "are you here", ""):
            self.assertFalse(text.only_filler(text.words(line)), line)


class RetentionTool(unittest.TestCase):
    def test_short_in_seconds_is_not_read_as_percent(self):
        rep = retention.analyse(SHORT)
        self.assertEqual(rep["axis"], "seconds")
        self.assertEqual(rep["cliffs"][0]["at_seconds"], 9.0)
        self.assertEqual(rep["cliffs"][0]["lost_points"], 21.0)
        self.assertEqual(rep["opening"]["window"], "the first 14.2 s")        # a quarter of the 57 s, not 30 s
        self.assertEqual(rep["opening"]["lost_points"], 30.0)
        self.assertIn("not why", " ".join(rep["notes"]))

    def test_no_heading_uses_duration_or_flag(self):
        tmp = _Tmp(self)
        path = tmp.write("plain.csv", "".join("%d,%d\n" % (i * 5, 100 - i * 3) for i in range(12)))
        self.assertEqual(retention.analyse(path)["axis"], "seconds")
        self.assertTrue(any("guess" in n for n in retention.analyse(path)["notes"]))
        self.assertEqual(retention.analyse(path, duration=55)["axis_basis"], "the last point matches --duration")
        self.assertEqual(retention.analyse(path, axis="percent")["axis"], "percent")

    def test_percent_axis_with_transcript_says_what_was_said(self):
        rep = retention.analyse(PERCENT, transcript=SRT)
        self.assertEqual(rep["axis"], "percent")
        self.assertIn("transcript", rep["duration_basis"])
        self.assertTrue(rep["cliffs"][0]["said"])
        self.assertIn("Heuristic", retention.render(rep))

    def test_percent_axis_without_a_length_gives_no_seconds(self):
        rep = retention.analyse(PERCENT)
        self.assertIsNone(rep["cliffs"][0]["at_seconds"])
        self.assertIn("first 10%", rep["opening"]["window"])

    def test_export_shapes(self):
        tmp = _Tmp(self)
        ratio = tmp.write("ratio.csv", "pos,ratio\n" + "".join("%.2f,%.2f\n" % (i / 10, 1 - i / 20) for i in range(11)))
        rep = retention.analyse(ratio)
        self.assertEqual((rep["axis"], rep["start_percent"], rep["end_percent"]), ("percent", 100.0, 50.0))
        semi = tmp.write("semi.csv", "Time (seconds);Retention\n" + "".join(
            "%d;%d,5\n" % (i * 5, 90 - i) for i in range(10)))
        rep = retention.analyse(semi)
        self.assertEqual((rep["axis"], rep["start_percent"]), ("seconds", 90.5))
        clock = tmp.write("clock.csv", "pos,ret\n" + "".join("0:%02d,%d\n" % (i * 5, 100 - i) for i in range(10)))
        self.assertEqual(retention.analyse(clock)["axis"], "seconds")


class EditTool(unittest.TestCase):
    def test_hinglish_srt(self):
        rep = edit.analyse(SRT)
        kinds = [c["kind"] for c in rep["cuts"]]
        self.assertEqual(kinds, ["retake", "dead"])
        self.assertEqual((rep["cuts"][0]["start"], rep["cuts"][0]["end"]), (0.0, 2.0))
        self.assertEqual([c["text"] for c in rep["review"]["filler_cues"]], ["उम्म, मतलब", "arre yaar"])
        self.assertEqual(rep["review"]["filler_words"][0]["words"], ["matlab", "haan"])
        self.assertEqual(rep["review"]["counts"]["matlab"], 1)
        self.assertEqual(rep["review"]["counts"]["मतलब"], 1)

    def test_fillers_are_a_review_cue_not_a_cut_or_a_mistake(self):
        rep = edit.analyse(SRT)
        self.assertNotIn("filler", [c["kind"] for c in rep["cuts"]])
        self.assertEqual(rep["suggested_cut_seconds"], round(2.0 + (2.0 - 0.45), 3))
        report = edit.render(rep)
        self.assertIn("to review", report)
        self.assertIn("(heuristic)", report)
        self.assertNotIn("mistake", report.lower())
        self.assertNotIn("error", report.lower())

    def test_overlapping_cuts_are_not_counted_twice(self):
        tmp = _Tmp(self)
        path = tmp.write("o.json", json.dumps({"segments": [
            {"start": 0, "end": 4, "text": "one two three four"}, {"start": 1, "end": 2, "text": "one two three five"},
            {"start": 5, "end": 6, "text": "something else entirely here"}]}))
        rep = edit.analyse(path)
        self.assertLessEqual(rep["suggested_cut_seconds"], rep["duration_seconds"])

    def test_turkish_spanish_and_chinese_retakes(self):
        tmp = _Tmp(self)
        for name, a, b in (("tr", "İyi günler arkadaşlar", "İyi günler arkadaşlar bugün"),
                           ("es", "déjame que te", "déjame que te cuente"), ("zh", "今天天气", "今天天气很好")):
            path = tmp.write(name + ".srt", "1\n00:00:00,000 --> 00:00:01,000\n%s\n\n2\n00:00:01,100 --> "
                                            "00:00:02,000\n%s\n" % (a, b))
            self.assertEqual([c["kind"] for c in edit.analyse(path)["cuts"]], ["retake"], name)

    def _two_lines(self, tmp, name, a, b):
        return tmp.write(name + ".srt", "1\n00:00:00,000 --> 00:00:02,000\n%s\n\n2\n00:00:02,100 --> "
                                        "00:00:04,000\n%s\n" % (a, b))

    def test_short_line_full_of_fillers_said_twice_is_a_retake(self):
        tmp = _Tmp(self)
        line = "अरे यार, मतलब ये देखो"
        cuts = edit.analyse(self._two_lines(tmp, "hi", line, line))["cuts"]
        self.assertEqual([c["kind"] for c in cuts], ["retake"])

    def test_same_fillers_then_different_words_is_not_a_retake(self):
        tmp = _Tmp(self)
        path = self._two_lines(tmp, "hi2", "अरे यार, मतलब ये देखो", "अरे यार, मतलब वो सुनो")
        self.assertEqual(edit.analyse(path)["cuts"], [])

    def test_two_word_line_said_twice_stays_a_choice(self):
        tmp = _Tmp(self)
        self.assertEqual(edit.analyse(self._two_lines(tmp, "two", "ये देखो", "ये देखो"))["cuts"], [])

    def test_retakes_in_scripts_written_without_spaces(self):
        tmp = _Tmp(self)
        for name, a, b in (("th", "สวัสดีครับวันนี้เราจะมา", "สวัสดีครับวันนี้เราจะมาดูร้านใหม่"),
                           ("lo", "ສະບາຍດີມື້ນີ້ພວກເຮົາ", "ສະບາຍດີມື້ນີ້ພວກເຮົາຈະມາເບິ່ງ"),
                           ("km", "សួស្តីថ្ងៃនេះយើងនឹងមក", "សួស្តីថ្ងៃនេះយើងនឹងមកមើលហាង"),
                           ("my", "မင်္ဂလာပါဒီနေ့ကျွန်တော်တို့", "မင်္ဂလာပါဒီနေ့ကျွန်တော်တို့ဆိုင်ကိုကြည့်မယ်"),
                           ("th_same", "สวัสดีครับ", "สวัสดีครับ")):
            cuts = edit.analyse(self._two_lines(tmp, name, a, b))["cuts"]
            self.assertEqual([c["kind"] for c in cuts], ["retake"], name)

    def test_thai_lines_sharing_only_a_greeting_are_not_a_retake(self):
        tmp = _Tmp(self)
        path = self._two_lines(tmp, "th2", "สวัสดีครับวันนี้อากาศดี", "สวัสดีครับพรุ่งนี้เราไปตลาด")
        self.assertEqual(edit.analyse(path)["cuts"], [])

    def test_spanish_and_turkish_fillers_need_no_flag(self):
        tmp = _Tmp(self)
        rep = edit.analyse(tmp.write("es.srt", "1\n00:00:00,000 --> 00:00:01,000\nEste\n\n2\n00:00:01,100 --> "
                                               "00:00:03,000\nes un buen precio, o sea, barato\n"))
        self.assertEqual(rep["review"]["counts"], {"este": 1, "o sea": 1})
        rep = edit.analyse(tmp.write("tr.srt", "1\n00:00:00,000 --> 00:00:01,000\nİşte\n\n2\n00:00:01,100 --> "
                                               "00:00:03,000\nbu fiyat yani çok iyi\n"))
        self.assertEqual(rep["review"]["counts"], {"işte": 1, "yani": 1})

    def test_este_inside_a_spanish_sentence_is_a_normal_word(self):
        tmp = _Tmp(self)
        rep = edit.analyse(tmp.write("es2.srt", "1\n00:00:00,000 --> 00:00:02,000\neste producto es bueno\n"))
        self.assertEqual(rep["review"]["counts"], {})

    def test_extra_filler_in_any_language(self):
        tmp = _Tmp(self)
        path = tmp.write("x.srt", "1\n00:00:00,000 --> 00:00:01,000\nO zaman şey\n")
        self.assertEqual(edit.analyse(path)["review"]["filler_words"], [])
        self.assertEqual(edit.analyse(path, extra_fillers=["şey"])["review"]["filler_words"][0]["words"], ["şey"])

    def test_subtitle_details(self):
        tmp = _Tmp(self)
        path = tmp.write("v.vtt", "WEBVTT\n\nNOTE not speech\n\n00:00.000 --> 00:01.000 align:start\n<c>2024</c> was "
                                  "<b>good</b> &amp; fun\n\n00:01.000 --> 00:02.000\n1999\n\nbad --> 00:03.000\nlost\n")
        cues, skipped = text.load_cues(path)
        self.assertEqual([c[2] for c in cues], ["2024 was good & fun", "1999"])
        self.assertEqual(skipped, 1)


class OutliersTool(unittest.TestCase):
    def test_ranked_against_own_channel(self):
        rep = outliers.analyse(COLLECTED)
        top = rep["outliers"][0]
        self.assertEqual(top["title"], "दिवाली का डिब्बा")
        self.assertEqual((top["channel_median"], top["multiple"]), (1100.0, 10.91))
        gym = [r for r in rep["outliers"] if r["channel"] == "Local Gym"][0]
        self.assertEqual((gym["multiple"], gym["views_rounded_in_source"]), (3.0, True))
        self.assertEqual(rep["thin_channels"], [{"channel": "Tiny Channel", "videos": 1}])
        self.assertEqual((rep["skipped_rows"], rep["repeated_rows"]), (3, 1))
        self.assertIn("not why", outliers.render(rep))

    def test_views_formats(self):
        for raw, want in ((1234, 1234), ("1,234", 1234), ("12.000", 12000), ("1.2M", 1200000), ("45k views", 45000),
                          ("3 lakh", 300000), ("2 करोड़", 20000000), (0, 0)):
            self.assertEqual(outliers.parse_views(raw)[0], want, raw)
        for raw in (None, "many", -5, True, "", [], float("inf")):
            self.assertIsNone(outliers.parse_views(raw), raw)

    def test_all_zero_channel_is_reported(self):
        tmp = _Tmp(self)
        path = tmp.write("z.json", json.dumps([{"channel": "A", "views": 0, "title": str(i)} for i in range(4)]))
        self.assertEqual(outliers.analyse(path)["channels_with_zero_median"], ["A"])

    def test_the_tools_fetch_nothing(self):
        for mod in (retention, edit, outliers, text):
            src = read_bytes(mod.__file__).decode("utf-8")
            for word in ("urllib", "http.client", "socket", "hidrogen", "ledger"):
                self.assertNotIn(word, src)


class _Tmp:
    def __init__(self, case):
        import shutil
        import tempfile
        self.dir = tempfile.mkdtemp()
        case.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, data):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path


class BadFiles(unittest.TestCase):
    TOOLS = (retention.analyse, edit.analyse, outliers.analyse)

    def assert_friendly(self, path):
        for tool in self.TOOLS:
            with self.assertRaises(BBError):
                tool(path)

    def test_bad_inputs_are_friendly(self):
        tmp = _Tmp(self)
        for name, data in (("empty", b""), ("blank", b" \n\n"), ("bom_only", b"\xef\xbb\xbf"), ("words", b"hello there\n"),
                           ("binary", b"\xff\xd8\x00\x01\x80\x81"), ("nul", b"a,b\x00,c\n"),
                           ("zip", b"PK\x03\x04rest"), ("braces", b'{"segments":[{"start":"x"'),
                           ("deep", b"[" * 100000)):
            self.assert_friendly(tmp.write(name + ".txt", data))

    def test_missing_file_and_folder(self):
        tmp = _Tmp(self)
        for tool in self.TOOLS:
            with self.assertRaises(UsageError):
                tool(os.path.join(tmp.dir, "नहीं है.csv"))
            with self.assertRaises(UsageError):
                tool(tmp.dir)

    def test_broken_rows_inside_valid_files(self):
        tmp = _Tmp(self)
        for bad in ('[1, 2, 3]', '{"videos": "x"}', '[{"channel": "A", "views": 1e999}]', '"text"'):
            with self.assertRaises(BBError):
                outliers.analyse(tmp.write("o.json", bad))
        for bad in ('{"segments": [{"start": "x", "end": 1, "text": "a"}, 5]}', '{"a": 1}', '[]', '[1]'):
            with self.assertRaises(BBError):
                edit.analyse(tmp.write("e.json", bad))
        with self.assertRaises(BBError):
            edit.analyse(tmp.write("t.srt", "1\n12.5 --> 13.5\nhello\n"))
        with self.assertRaises(BBError):
            retention.analyse(tmp.write("r.csv", "a,b\nnan,inf\n1,2\n"))

    def test_boms_and_encodings_read_the_same(self):
        tmp = _Tmp(self)
        with open(SRT, encoding="utf-8") as f:
            body = f.read()
        plain = edit.analyse(SRT)["cuts"]
        self.assertEqual(edit.analyse(tmp.write("b.srt", b"\xef\xbb\xbf" + body.encode("utf-8")))["cuts"], plain)
        self.assertEqual(edit.analyse(tmp.write("u.srt", body.encode("utf-16")))["cuts"], plain)
        self.assertEqual(edit.analyse(tmp.write("c.srt", body.replace("\n", "\r\n")))["cuts"], plain)
        self.assertEqual(len(retention.analyse(tmp.write("b.csv", b"\xef\xbb\xbf" + read_bytes(SHORT)))["cliffs"]),
                         len(retention.analyse(SHORT)["cliffs"]))
        self.assertTrue(outliers.analyse(tmp.write("b.json", b"\xef\xbb\xbf" + read_bytes(COLLECTED)))["outliers"])
        self.assertTrue(edit.analyse(tmp.write("w.json", b"\xef\xbb\xbf" + json.dumps(
            {"segments": [{"start": 0, "end": 1, "text": "नमस्ते"}]}).encode()))["cuts"] == [])


class Command(MockCase):
    with_key = False

    def run_all(self, root):
        base = ["-p", root]
        for args in (["retention", SHORT, "--transcript", SRT], ["edit", SRT], ["outliers", COLLECTED]):
            code, out, err = bb(self.env(), "analyse", *(args + base))
            self.assertEqual(code, 0, err)
            self.assertIn("saved:", out)

    def test_no_change_to_stages_status_or_budget(self):
        root = self.make_project(budget=0, doctor=False)
        env = self.env()
        env["HIDROGEN_API_URL"] = "http://127.0.0.1:9"       # nothing may be called
        before = bb(env, "status", "-p", root, "--json")[1]
        with open(os.path.join(root, "project.json"), "rb") as f:
            state = f.read()
        self.run_all(root)
        for tool in ("retention", "edit", "outliers"):
            for ext in (".json", ".md"):
                self.assertTrue(os.path.isfile(os.path.join(root, "analysis", tool + ext)), tool + ext)
        self.assertEqual(bb(env, "status", "-p", root, "--json")[1], before)
        with open(os.path.join(root, "project.json"), "rb") as f:
            self.assertEqual(f.read(), state)
        with open(os.path.join(root, "analysis", "edit.json"), encoding="utf-8") as f:
            self.assertIn("उम्म", f.read())

    def test_spaces_and_non_ascii_paths(self):
        folder = os.path.join(self.tmp, "मेरी फ़िल्म folder")
        os.makedirs(folder)
        srt = os.path.join(folder, "वॉइस ओवर.srt")
        with open(srt, "wb") as f:
            f.write(read_bytes(SRT))
        root = self.make_project(os.path.join("मेरी फ़िल्म folder", "प्रोजेक्ट one"), budget=0, doctor=False)
        code, out, err = bb(self.env(), "analyse", "edit", srt, "-p", root)
        self.assertEqual(code, 0, err)
        self.assertIn("वॉइस ओवर.srt", out)

    def test_friendly_errors_with_exit_codes(self):
        tmp = _Tmp(self)
        empty = tmp.write("खाली file.csv", b"")
        for args in (["retention", empty], ["edit", empty], ["outliers", empty]):
            code, out, err = bb(self.env(), "analyse", *args)
            self.assertEqual(code, 1)
            self.assertIn("bizzbell:", err)
            self.assertIn("empty", err)
            self.assertNotIn("Traceback", out + err)
        code, _, err = bb(self.env(), "analyse", "edit", os.path.join(tmp.dir, "gone.srt"))
        self.assertEqual(code, 2)
        self.assertIn("cannot find", err)
        code, _, err = bb(self.env(), "analyse", "edit", SRT, "--floor=-1")
        self.assertEqual(code, 2)
        code, _, err = bb(self.env(), "analyse", "retention", SHORT, "--duration", "0")
        self.assertEqual(code, 2)

    def test_without_a_project_it_prints_and_saves_nothing(self):
        code, out, err = bb(self.env(), "analyse", "outliers", COLLECTED, "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["tool"], "outliers")
        self.assertIn("nothing was saved", err)

    def test_ascii_terminal_does_not_crash(self):
        env = self.env()
        env["PYTHONIOENCODING"] = "ascii"
        code, out, err = bb(env, "analyse", "edit", SRT)
        self.assertEqual(code, 0, err)
        self.assertIn("\\u", out)

    def test_lone_surrogate_in_json_does_not_crash_the_save(self):
        tmp = _Tmp(self)
        root = self.make_project(budget=0, doctor=False)
        path = tmp.write("s.json", "[%s]" % ",".join(
            '{"channel": "A", "title": "t%d\\ud800", "views": %d}' % (v, v) for v in (1, 2, 3, 40)))
        code, out, err = bb(self.env(), "analyse", "outliers", path, "-p", root)
        self.assertEqual(code, 0, err)


if __name__ == "__main__":
    unittest.main()
