"""원고 분석과 고유명사 시험."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import text
from attools.write import manuscript, names
class ManuscriptTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_stats_excludes_heading(self):
        p = self.root / "1화.txt"
        p.write_text("# 제목\n\n가나다 라마바.\n", encoding="utf-8")
        s = manuscript.analyze(p)
        self.assertEqual(s.chars_no_space, 7)   # 가나다라마바.
        self.assertEqual(s.sentences, 1)

    def test_dialogue_ratio(self):
        s = manuscript.analyze(Path("x.txt"), '"안녕" 그가 말했다.')
        self.assertGreater(s.dialogue_ratio, 0)

    def test_inspect_runs(self):
        f = manuscript.inspect("그는 갔다. 그는 왔다. 그는 섰다.", run_threshold=3)
        self.assertEqual(f.start_runs, [("그는", 3, 1)])

    def test_inspect_cliche_and_long(self):
        f = manuscript.inspect("그는 미소를 지었다. " + "가" * 150 + ".", long_limit=100)
        self.assertIn(("미소를 지었다", 1), f.cliches)
        self.assertEqual(len(f.long_sentences), 1)

    def test_split_scenes_by_breaks_and_headings(self):
        text = ("# 1화\n\n" + "가" * 60 + "\n\n***\n\n" + "나" * 60 + "\n\n"
                "## 2화\n\n" + "다" * 60 + "\n")
        scenes = manuscript.split_scenes(text, min_chars=10)
        self.assertEqual(len(scenes), 3)
        self.assertEqual([s.title for s in scenes], ["1화", "", "2화"])
        self.assertEqual(scenes[0].number, 1)

    def test_split_scenes_drops_short_fragments(self):
        text = "짧음\n\n***\n\n" + "가" * 60
        scenes = manuscript.split_scenes(text, min_chars=30)
        self.assertEqual(len(scenes), 1)

    def test_split_scenes_on_blank_run(self):
        text = "가" * 40 + "\n\n\n\n" + "나" * 40
        self.assertEqual(len(manuscript.split_scenes(text, min_chars=10)), 2)

    def test_scene_metrics(self):
        scene = manuscript.Scene(1, "", 1, '리안이 웃었다.\n"안녕." 카일이 답했다.')
        self.assertEqual(scene.opening, "리안이 웃었다.")
        self.assertGreater(scene.dialogue_ratio, 0)
        # 공백만 뺀 글자 수라 따옴표도 센다
        self.assertEqual(scene.chars, len('리안이웃었다."안녕."카일이답했다.'))

    def test_tag_people_orders_by_frequency(self):
        scenes = [manuscript.Scene(1, "", 1, "리안 리안 카일")]
        manuscript.tag_people(scenes, ["카일", "리안", "세드릭"])
        self.assertEqual(scenes[0].people, ["리안", "카일"])

    def test_find_mentions_with_context(self):
        import re

        text = ("리안은 상자를 열었다. 안에는 붉은 열쇠가 있었다. 그는 넣었다.\n"
                "다른 이야기였다. 붉은 열쇠는 잊혔다.\n")
        found = manuscript.find_mentions(text, re.compile("붉은 열쇠"), path="1화.txt")
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0].hit, "안에는 붉은 열쇠가 있었다.")
        self.assertIn("리안은 상자를 열었다.", found[0].before)
        self.assertIn("그는 넣었다.", found[0].after)
        self.assertIn("**붉은 열쇠", found[0].context().replace("안에는 ", ""))

    def test_find_mentions_tags_scene_number(self):
        import re

        text = ("# 1화\n\n" + "가" * 60 + " 열쇠가 있었다.\n\n***\n\n"
                + "나" * 60 + " 열쇠를 꺼냈다.\n")
        scenes = manuscript.split_scenes(text, min_chars=10)
        found = manuscript.find_mentions(text, re.compile("열쇠"), scenes=scenes)
        self.assertEqual([m.scene for m in found], [1, 2])

    def test_find_mentions_none(self):
        import re

        self.assertEqual(manuscript.find_mentions("아무것도 없다.", re.compile("열쇠")), [])

    def test_strip_headings_keeps_scene_breaks(self):
        text = "# 1화\n\n본문\n\n***\n\n다음\n"
        stripped = manuscript.strip_headings(text)
        self.assertNotIn("1화", stripped)
        self.assertIn("***", stripped)          # 장면 구분선은 남아야 한다
        self.assertEqual(text.count("\n"), stripped.count("\n"))   # 행 번호 유지

        self.assertNotIn("***", manuscript.strip_markup(text))

    def test_find_context_skips_separator_lines(self):
        import re

        text = "***\n열쇠가 있었다.\n***\n"
        found = manuscript.find_mentions(text, re.compile("열쇠"))
        self.assertEqual(found[0].before, "")
        self.assertEqual(found[0].after, "")

    def test_time_marks_extract_kinds(self):
        text = "2026년 3월 5일 아침, 봄이었다. 사흘 뒤 오후 3시에 다시 왔다."
        kinds = {m.kind for m in manuscript.find_time_marks(text)}
        self.assertEqual(kinds, {"날짜", "시간대", "계절", "기간", "시각"})

    def test_time_marks_prefer_longest_overlap(self):
        marks = manuscript.find_time_marks("2026년 3월 5일에 만났다.")
        self.assertEqual([m.text for m in marks if m.kind == "날짜"], ["2026년 3월 5일"])

    def test_time_conflict_within_one_scene(self):
        text = ("# 1화\n\n" + "가" * 50 + " 아침이었다. " + "나" * 50 + " 한밤중이었다.\n"
                "\n***\n\n" + "다" * 50 + " 저녁이었다.\n")
        scenes = manuscript.split_scenes(text, min_chars=10)
        marks = manuscript.find_time_marks(manuscript.strip_headings(text), scenes=scenes)
        conflicts = manuscript.time_conflicts(marks)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].scene, 1)
        self.assertEqual(sorted(conflicts[0].values), ["밤", "아침"])

    def test_no_conflict_across_scenes(self):
        text = ("아침이었다. " + "가" * 60 + "\n\n***\n\n한밤중이었다. " + "나" * 60 + "\n")
        scenes = manuscript.split_scenes(text, min_chars=10)
        marks = manuscript.find_time_marks(text, scenes=scenes)
        self.assertEqual(manuscript.time_conflicts(marks), [])

    def test_style_metrics(self):
        text = '짧다. 이것은 조금 더 긴 문장이다. "대사." 그가 말했다.'
        st = manuscript.style_metrics(text, "1화")
        self.assertEqual(st.name, "1화")
        self.assertEqual(st.sentences, 4)
        self.assertGreater(st.avg_sentence, 0)
        self.assertGreater(st.dialogue_ratio, 0)
        self.assertGreater(st.vocabulary, 0)
        self.assertLessEqual(st.vocabulary, 1)

    def test_style_metrics_empty(self):
        st = manuscript.style_metrics("", "빈것")
        self.assertEqual(st.sentences, 0)
        self.assertEqual(st.avg_sentence, 0.0)

    def test_style_long_ratio(self):
        text = "짧다. " + "가" * 100 + "."
        st = manuscript.style_metrics(text, long_limit=50)
        self.assertAlmostEqual(st.long_ratio, 0.5)

    def test_style_outliers_needs_three(self):
        rows = [manuscript.style_metrics("가나다. 라마바.", f"{i}") for i in range(2)]
        self.assertEqual(manuscript.style_outliers(rows), {})

    def test_style_outliers_flags_the_odd_one(self):
        rows = []
        for i in range(5):
            body = ("그는 걸었다. " * 10 if i != 2
                    else "그는 오래도록 걸었고 그 길은 끝없이 이어졌으며 결국 아무 데도 "
                         "닿지 못했다. " * 10)
            rows.append(manuscript.style_metrics(body, f"{i}화"))
        found = manuscript.style_outliers(rows)
        self.assertIn("2화", found)
        self.assertTrue(any("평균 문장 길이" in r for r in found["2화"]))

    def test_normalize_body_one_line_one_paragraph(self):
        text = "# 1화\n\n첫 줄이다.\n둘째 줄이다.\n\n***\n\n다음 문단.\n"
        body = manuscript.normalize_body(text)
        self.assertNotIn("1화", body)                    # 제목은 뺀다
        self.assertEqual(body.split("\n\n"),
                         ["첫 줄이다.", "둘째 줄이다.", "***", "다음 문단."])

    def test_normalize_body_join_and_indent(self):
        text = "접힌 문단의\n뒷부분이다.\n"
        joined = manuscript.normalize_body(text, join_lines=True)
        self.assertEqual(joined, "접힌 문단의 뒷부분이다.")

        indented = manuscript.normalize_body(text, indent=True)
        self.assertTrue(indented.startswith("\u3000"))

    def test_normalize_body_scene_mark(self):
        body = manuscript.normalize_body("가.\n\n***\n\n나.\n", scene_mark="＊")
        self.assertIn("＊", body)
        self.assertNotIn("***", body)

    def test_chapter_title_prefers_heading(self):
        self.assertEqual(manuscript.chapter_title(Path("01.txt"), "# 1화 겨울\n\n본문"),
                         "1화 겨울")
        self.assertEqual(manuscript.chapter_title(Path("01화.txt"), "제목 없는 본문"),
                         "01화")

    def test_export_html_structure(self):
        html = manuscript.export_html([("1화", "가.\n\n***\n\n나.")],
                                      title="제목", author="필명", note="메모")
        self.assertIn("<h2 id=\"장1\">1화</h2>", html)
        self.assertIn("<p>가.</p>", html)
        self.assertIn('class="break"', html)
        self.assertIn("제목", html)
        self.assertNotIn("text-indent", html)

    def test_export_html_indent_uses_css(self):
        html = manuscript.export_html([("1화", "가.")], indent=True)
        self.assertIn("text-indent", html)

    def test_export_html_escapes(self):
        html = manuscript.export_html([("<script>", "a & b")])
        self.assertNotIn("<script>", html.split("<style>")[0] + html.split("</style>")[1])
        self.assertIn("a &amp; b", html)

    def test_export_text_formats(self):
        plain = manuscript.export_text([("1화", "본문")], title="제목")
        self.assertIn("[ 1화 ]", plain)

        markdown = manuscript.export_text([("1화", "본문")], title="제목", markdown=True)
        self.assertIn("# 제목", markdown)
        self.assertIn("## 1화", markdown)

    def test_snapshot_growth(self):
        (self.root / "1화.txt").write_text("가나다", encoding="utf-8")
        manuscript.snapshot(self.root, note="초고")
        (self.root / "1화.txt").write_text("가나다라마", encoding="utf-8")
        manuscript.snapshot(self.root, note="퇴고")
        snaps = manuscript.list_snapshots(self.root)
        self.assertEqual([s["total"] for s in snaps], [3, 5])
        self.assertEqual(snaps[0]["note"], "초고")


class PaceTest(unittest.TestCase):
    SNAPS = [
        {"time": "2026-08-25T20:00:00", "total": 1000},
        {"time": "2026-08-28T09:00:00", "total": 2000},
        {"time": "2026-08-28T20:00:00", "total": 2800},   # 같은 날 두 번
        {"time": "2026-09-01T20:00:00", "total": 4000},
    ]

    def test_daily_counts_folds_same_day_and_marks_baseline(self):
        days = manuscript.daily_counts(self.SNAPS)
        self.assertEqual([str(d.day) for d in days],
                         ["2026-08-25", "2026-08-28", "2026-09-01"])
        self.assertEqual([d.total for d in days], [1000, 2800, 4000])
        self.assertTrue(days[0].baseline)
        self.assertEqual(days[0].written, 0)
        self.assertEqual([d.written for d in days[1:]], [1800, 1200])

    def test_daily_counts_skips_broken_timestamp(self):
        days = manuscript.daily_counts([{"time": "언제인지 모름", "total": 5},
                                        *self.SNAPS])
        self.assertEqual(len(days), 3)

    def test_pace_averages_and_best_day(self):
        p = manuscript.pace(self.SNAPS)
        self.assertEqual(p.current, 4000)
        self.assertEqual(p.span, 7)
        self.assertEqual(p.written_days, 2)
        self.assertAlmostEqual(p.per_day, 3000 / 7)
        self.assertEqual(p.per_written_day, 1500)
        self.assertEqual(str(p.best.day), "2026-08-28")

    def test_pace_single_day_has_no_speed(self):
        p = manuscript.pace(self.SNAPS[:1])
        self.assertEqual(p.span, 0)
        self.assertEqual(p.per_day, 0.0)
        self.assertIsNone(p.best)
        self.assertIsNone(p.finish_day())

    def test_window_keeps_recent_days_and_rebases(self):
        p = manuscript.pace(self.SNAPS, window=4)
        self.assertEqual([str(d.day) for d in p.days],
                         ["2026-08-28", "2026-09-01"])
        self.assertTrue(p.days[0].baseline)
        self.assertEqual(p.days[0].written, 0)

    def test_goal_and_due_math(self):
        from datetime import date

        p = manuscript.pace(self.SNAPS, goal=10000, due=date(2026, 9, 11))
        today = date(2026, 9, 1)
        self.assertEqual(p.remaining, 6000)
        self.assertEqual(p.days_left(today), 10)
        self.assertEqual(p.need_per_day(today), 600)
        self.assertEqual(str(p.finish_day(today)), "2026-09-15")

    def test_past_due_gives_no_daily_need(self):
        from datetime import date

        p = manuscript.pace(self.SNAPS, goal=10000, due=date(2026, 8, 1))
        self.assertIsNone(p.need_per_day(date(2026, 9, 1)))

    def test_goal_already_met(self):
        from datetime import date

        p = manuscript.pace(self.SNAPS, goal=1000)
        self.assertEqual(p.remaining, 0)
        self.assertEqual(p.finish_day(date(2026, 9, 1)), date(2026, 9, 1))


class NamesTest(unittest.TestCase):
    SAMPLE = ("리안은 문을 열었다. 카일이 뒤따랐다.\n"
              "리안는 대답하지 않았다. 리언이 웃었다.\n"
              "카일을 바라보던 리안이 고개를 저었다.\n"
              "세드릭과 리안은 걸었다. 세드릭를 믿을 수 없었다.\n"
              "카알이 문득 돌아보았다. 세드릭은 검을 뽑았다.\n")

    def test_strip_particle_takes_longest(self):
        self.assertEqual(names.strip_particle("리안에게서"), ("리안", "에게서"))
        self.assertEqual(names.strip_particle("리안은"), ("리안", "은"))
        self.assertEqual(names.strip_particle("문득"), ("문득", ""))

    def test_extract_needs_repetition_and_variety(self):
        found = names.extract(self.SAMPLE, min_count=2, min_variety=2)
        # 횟수가 같으면 이름 순으로 고정된다
        self.assertEqual([n.text for n in found], ["리안", "세드릭", "카일"])
        self.assertEqual(found[0].count, 4)

    def test_extract_skips_stopwords(self):
        text = "그녀는 갔다. 그녀가 왔다. 그녀를 봤다. " * 3
        self.assertEqual(names.extract(text, min_count=2), [])

    def test_variants_flags_rare_lookalikes(self):
        found = names.extract(self.SAMPLE, min_count=2, min_variety=2)
        pairs = names.variants(found, names.all_stems(self.SAMPLE))
        self.assertIn(("리안", "리언"), [(a.text, b.text) for a, b, _ in pairs])
        self.assertIn(("카일", "카알"), [(a.text, b.text) for a, b, _ in pairs])
        # 확정된 이름끼리는 흔들림으로 보지 않는다
        self.assertNotIn("세드릭", [b.text for _, b, _ in pairs])

    def test_edit_distance_cutoff(self):
        self.assertEqual(names.edit_distance("리안", "리언"), 1)
        self.assertEqual(names.edit_distance("리안", "리안"), 0)
        self.assertGreater(names.edit_distance("리안", "세드릭", 1), 1)

    def test_josa_batchim_rules(self):
        errors = names.check_josa("카일가 왔다. 카일는 갔다.", ["카일"])
        self.assertEqual([(e.wrong, e.right) for e in errors], [("가", "이"), ("는", "은")])

        errors = names.check_josa("미아이 왔다. 미아으로 갔다.", ["미아"])
        self.assertEqual([(e.wrong, e.right) for e in errors], [("이", "가"), ("으로", "로")])

    def test_josa_riul_takes_ro(self):
        # 받침이 ㄹ 이면 '서울로'가 맞고 '서울으로'는 틀리다
        self.assertEqual(names.check_josa("서울로 갔다.", ["서울"]), [])
        errors = names.check_josa("서울으로 갔다.", ["서울"])
        self.assertEqual((errors[0].wrong, errors[0].right), ("으로", "로"))

    def test_josa_ignores_longer_words(self):
        # '리안나는'은 리안+는이 아니다
        self.assertEqual(names.check_josa("리안나는 다른 사람이다.", ["리안"]), [])

    def test_josa_correct_forms_pass(self):
        clean = "리안이 웃었다. 리안은 갔다. 리안을 봤다. 리안과 함께."
        self.assertEqual(names.check_josa(clean, ["리안"]), [])

    SPEECH = ('"늦었어." 카일이 말했다.\n'
              '리안이 고개를 저었다. "괜찮습니다."\n'
              '"그럴 수 없어." 카일이 다시 말했다.\n'
              '"모르겠어."\n')

    def test_extract_speech_finds_speaker_after_quote(self):
        found = names.extract_speech(self.SPEECH, ["리안", "카일"])
        self.assertEqual([s.speaker for s in found], ["카일", "리안", "카일", ""])

    def test_extract_speech_does_not_cross_lines(self):
        # 다음 줄의 이름을 화자로 집으면 안 된다
        text = '"대사."\n카일이 다음 줄에서 말했다.\n'
        self.assertEqual(names.extract_speech(text, ["카일"])[0].speaker, "")

    def test_extract_speech_detects_politeness(self):
        found = names.extract_speech(self.SPEECH, ["리안", "카일"])
        self.assertEqual([s.polite for s in found], [False, True, False, False])

    def test_extract_speech_line_numbers(self):
        found = names.extract_speech(self.SPEECH, ["리안", "카일"])
        self.assertEqual([s.line for s in found], [1, 2, 3, 4])

    def test_voice_profiles(self):
        profiles, unknown = names.voice_profiles(
            names.extract_speech(self.SPEECH, ["리안", "카일"]))
        self.assertEqual(unknown, 1)
        self.assertEqual(profiles[0].name, "카일")
        self.assertEqual(profiles[0].count, 2)
        self.assertEqual(profiles[0].polite_ratio, 0.0)

        polite = [p for p in profiles if p.name == "리안"][0]
        self.assertEqual(polite.polite_ratio, 1.0)
        self.assertEqual(polite.top_endings[0][0], "니다")

    def test_voice_profiles_empty(self):
        self.assertEqual(names.voice_profiles([]), ([], 0))

    DOCS = [("1화", "리안은 성문을 지났다. 성문 앞에 눈이 쌓였다."),
            ("2화", "카일은 탑에 올랐다. 탑은 높았다. 리안도 탑을 보았다."),
            ("3화", "세드릭이 성문을 열었다.")]

    def test_wordlist_counts_and_first_source(self):
        words = {w.text: w for w in names.build_wordlist(self.DOCS)}
        self.assertEqual(words["성문"].count, 3)
        self.assertEqual(words["성문"].first_source, "1화")
        self.assertEqual(words["성문"].spread, 2)
        self.assertEqual(words["세드릭"].first_source, "3화")

    def test_wordlist_merges_one_char_stems(self):
        # '탑에·탑은·탑을·탑에서'는 한 낱말이다
        words = {w.text: w for w in names.build_wordlist(self.DOCS)}
        self.assertEqual(words["탑"].count, 3)
        self.assertNotIn("탑에", words)
        self.assertNotIn("탑을", words)

    def test_wordlist_does_not_split_real_two_char_words(self):
        # '가을'을 '가'+'을'로 자르면 안 된다
        docs = [("a", "가을이 왔다. 가을은 짧다. 서울로 갔다.")]
        words = {w.text for w in names.build_wordlist(docs)}
        self.assertIn("가을", words)
        self.assertIn("서울", words)
        self.assertNotIn("가", words)

    def test_wordlist_skip_common_toggle(self):
        docs = [("a", "마을에 눈이 온다. 마을은 조용하다.")]
        self.assertNotIn("마을", {w.text for w in names.build_wordlist(docs)})
        self.assertIn("마을",
                      {w.text for w in names.build_wordlist(docs, skip_common=False)})

    def test_words_only_in(self):
        words = names.build_wordlist(self.DOCS)
        only = {w.text for w in names.words_only_in(words, "2화")}
        self.assertIn("카일", only)
        self.assertNotIn("성문", only)

    def test_first_appearances_follows_document_order(self):
        words = names.build_wordlist(self.DOCS)
        firsts = names.first_appearances(words, ["1화", "2화", "3화"])
        self.assertEqual(list(firsts), ["1화", "2화", "3화"])
        self.assertIn("성문", [w.text for w in firsts["1화"]])
        self.assertIn("세드릭", [w.text for w in firsts["3화"]])

    def test_dialogue_speakers(self):
        text = '"늦었어." 카일이 말했다.\n"응." 리안이 답했다.\n'
        counts = names.dialogue_speakers(text, ["카일", "리안"])
        self.assertEqual(counts["카일"], 1)
        self.assertEqual(counts["리안"], 1)


class EpubTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.dest = self.root / "책.epub"
        self.chapters = [("1화 만남", "첫 문단이다.\n\n＊\n\n둘째 문단."),
                         ("2화 이별", "마지막 문단.")]

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _zip(self):
        import zipfile

        manuscript.export_epub(self.chapters, self.dest, title="시험작",
                               author="홍길동", note="2편")
        return zipfile.ZipFile(self.dest)

    def test_mimetype_is_first_and_stored(self):
        import zipfile

        with self._zip() as z:
            first = z.infolist()[0]
            self.assertEqual(first.filename, "mimetype")
            self.assertEqual(first.compress_type, zipfile.ZIP_STORED)
            self.assertEqual(z.read("mimetype"), b"application/epub+zip")

    def test_every_xml_part_parses(self):
        import xml.etree.ElementTree as ET

        with self._zip() as z:
            for name in z.namelist():
                if name.endswith((".xhtml", ".opf", ".xml")):
                    ET.fromstring(z.read(name))     # 리더는 XML 파서로 읽는다

    def test_manifest_and_spine_cover_every_chapter(self):
        with self._zip() as z:
            opf = z.read("OEBPS/content.opf").decode("utf-8")
            for i in (1, 2):
                self.assertIn(f'href="ch{i:03d}.xhtml"', opf)
                self.assertIn(f'idref="ch{i:03d}"', opf)
            self.assertLess(opf.index('idref="ch001"'), opf.index('idref="ch002"'))
            self.assertIn("<dc:creator>홍길동</dc:creator>", opf)

    def test_nav_lists_chapter_titles_in_order(self):
        with self._zip() as z:
            nav = z.read("OEBPS/nav.xhtml").decode("utf-8")
            self.assertLess(nav.index("1화 만남"), nav.index("2화 이별"))

    def test_scene_break_and_escaping(self):
        page = manuscript.epub_chapter("제목 <&>", "본문 <태그> 처럼\n\n＊＊＊")
        self.assertIn("&lt;태그&gt;", page)
        self.assertIn('<p class="break">', page)
        self.assertNotIn("<태그>", page)

    def test_indent_uses_class_not_spaces(self):
        page = manuscript.epub_chapter("제목", "본문", indent=True)
        self.assertIn('class="indent"', page)
        self.assertNotIn("\u3000", page)


class CastTest(unittest.TestCase):
    CHAPTERS = [("1화", "리안이 왔다. 리안나는 다른 사람이다. 세드릭도 왔다."),
                ("2화", "리안은 갔다."),
                ("3화", "세드릭만 남았다. 세드릭이 말했다.")]

    def test_count_mentions_allows_particles(self):
        self.assertEqual(names.count_mentions("리안이 왔다. 리안은 갔다.", "리안"), 2)
        self.assertEqual(names.count_mentions("리안에게 주었다", "리안"), 1)

    def test_count_mentions_skips_longer_names(self):
        self.assertEqual(names.count_mentions("리안나는 리안이 아니다", "리안"), 1)

    def test_cast_counts_by_chapter_sorted_by_total(self):
        rows = names.cast_by_chapter(self.CHAPTERS, ["리안", "세드릭", "리안나"])
        self.assertEqual([r.name for r in rows], ["세드릭", "리안", "리안나"])
        self.assertEqual(rows[0].counts, [1, 0, 2])

    def test_first_and_last_chapter(self):
        row = names.cast_by_chapter(self.CHAPTERS, ["리안"])[0]
        self.assertEqual((row.first, row.last, row.total), (1, 2, 2))

    def test_gone_for_counts_chapters_since_last(self):
        row = names.cast_by_chapter(self.CHAPTERS, ["리안"])[0]
        self.assertEqual(row.gone_for(), 1)
        self.assertEqual(row.gone_for(10), 8)      # 아직 안 쓴 화까지 셀 때

    def test_missing_person_has_no_first_or_last(self):
        row = names.cast_by_chapter(self.CHAPTERS, ["없는사람"])[0]
        self.assertEqual((row.first, row.last, row.total, row.gone_for()), (0, 0, 0, 0))


class TidyTest(unittest.TestCase):
    RAW = "# 1화 만남\n\n첫 줄이다.  \n이어지는 줄.\n\n\n***\n\n다음 문단.\n"

    def test_headings_survive(self):
        # normalize_body 는 제목을 떼지만, 파일에 되쓰는 tidy 는 남겨야 한다
        self.assertIn("# 1화 만남", manuscript.tidy_text(self.RAW))
        self.assertNotIn("# 1화 만남", manuscript.normalize_body(self.RAW))

    def test_paragraphs_get_one_blank_line(self):
        out = manuscript.tidy_text(self.RAW)
        self.assertIn("첫 줄이다.\n\n이어지는 줄.", out)
        self.assertNotIn("\n\n\n", out)

    def test_scene_mark_is_unified(self):
        out = manuscript.tidy_text(self.RAW, scene_mark="＊")
        self.assertIn("＊", out)
        self.assertNotIn("***", out)

    def test_join_folds_wrapped_lines(self):
        out = manuscript.tidy_text(self.RAW, join_lines=True)
        self.assertIn("첫 줄이다. 이어지는 줄.", out)

    def test_indent_uses_full_width_space(self):
        out = manuscript.tidy_text(self.RAW, indent=True)
        self.assertIn("　첫 줄이다.", out)

    def test_tidy_is_idempotent(self):
        once = manuscript.tidy_text(self.RAW, scene_mark="＊")
        self.assertEqual(manuscript.tidy_text(once, scene_mark="＊"), once)

    def test_empty_text_stays_empty(self):
        self.assertEqual(manuscript.tidy_text("\n\n"), "")


class QuoteTest(unittest.TestCase):
    def test_unclosed_quote_is_found(self):
        issues = manuscript.check_quotes("“여는 대사만 있다.\n")
        self.assertEqual([i.kind for i in issues], ["닫히지 않은 따옴표"])
        self.assertEqual(issues[0].line, 1)

    def test_multiline_dialogue_is_not_an_error(self):
        # 문단 안에서 열고 닫으면 줄이 나뉘어도 괜찮다
        body = "“여러 줄에 걸친\n대사도 있다.” 지문이 이어진다.\n"
        self.assertEqual(manuscript.check_quotes(body), [])

    def test_closing_without_opening(self):
        issues = manuscript.check_quotes("닫는 것만 있다.”\n")
        self.assertEqual([i.kind for i in issues], ["닫는 따옴표가 먼저"])

    def test_odd_straight_quote_is_reported(self):
        issues = manuscript.check_quotes('"곧은 따옴표 하나.\n')
        self.assertEqual([i.kind for i in issues], ["곧은 따옴표 홀수"])

    def test_even_straight_quotes_pass(self):
        self.assertEqual(manuscript.check_quotes('"대사다." 지문.\n'), [])

    def test_nested_quotes_pair_up(self):
        self.assertEqual(manuscript.check_quotes("“그가 ‘안녕’ 이라 했다.”\n"), [])

    def test_line_numbers_point_at_the_paragraph(self):
        body = "첫 문단.\n\n둘째 문단.\n\n“안 닫힌 대사.\n"
        self.assertEqual(manuscript.check_quotes(body)[0].line, 5)

    def test_quote_styles_counts_each_mark(self):
        styles = manuscript.quote_styles('“가”와 "나"')
        self.assertEqual(styles["“"], 1)
        self.assertEqual(styles['"'], 2)


class ChapterSplitTest(unittest.TestCase):
    RAW = ("들어가는 말이다.\n\n제1화 만남\n\n첫 문단.\n\n2화 이별\n\n"
           "둘째 문단.\n3화 때 그랬다는 문장.\n\n### 후일담\n\n끝.\n")

    def test_splits_on_chapter_lines_and_headings(self):
        preface, chapters = manuscript.split_chapters(self.RAW)
        self.assertEqual(preface, "들어가는 말이다.")
        self.assertEqual([c.title for c in chapters], ["만남", "이별", "후일담"])
        self.assertEqual([c.label for c in chapters], ["1화", "2화", ""])

    def test_sentence_in_the_middle_is_not_a_chapter(self):
        # '3화 때 그랬다는 문장.' 은 본문이다. 앞 줄이 비어 있지 않고 문장으로 끝난다
        _, chapters = manuscript.split_chapters(self.RAW)
        self.assertIn("3화 때 그랬다는 문장.", chapters[1].body)

    def test_no_marks_means_no_split(self):
        preface, chapters = manuscript.split_chapters("제목 없는 글\n계속.\n")
        self.assertEqual(chapters, [])
        self.assertTrue(preface)

    def test_filename_keeps_order_and_hangul(self):
        _, chapters = manuscript.split_chapters(self.RAW)
        self.assertEqual(manuscript.chapter_filename(chapters[0]), "01-만남.md")
        self.assertEqual(manuscript.chapter_filename(chapters[2], suffix=".txt"),
                         "03-후일담.txt")

    def test_filename_drops_forbidden_characters(self):
        self.assertEqual(manuscript.sanitize_chapter_title('만남/이별: "끝"'),
                         "만남이별_끝")

    def test_chapter_chars_ignore_whitespace(self):
        _, chapters = manuscript.split_chapters(self.RAW)
        self.assertEqual(chapters[0].chars, len("제1화만남첫문단."))


class NoteTest(unittest.TestCase):
    RAW = ("# 1화\n\n첫 문단이다. [[여기 묘사 보강]] 이어지는 문장.\n\n"
           "※ 이 장면은 순서를 바꿀 것\n\n둘째 문단.\nTODO: 이름 통일\n"
           "<!-- 편집자 메모 -->\n끝 문단.\n")

    def test_finds_every_kind(self):
        kinds = [n.kind for n in manuscript.find_notes(self.RAW)]
        self.assertEqual(sorted(set(kinds)), sorted(["[[ ]]", "표시", "TODO", "주석"]))

    def test_line_numbers_are_not_shifted_by_blank_lines(self):
        notes = {n.kind: n.line for n in manuscript.find_notes(self.RAW)}
        self.assertEqual(notes["[[ ]]"], 3)
        self.assertEqual(notes["표시"], 5)      # 앞의 빈 줄을 먹지 않는다
        self.assertEqual(notes["TODO"], 8)

    def test_whole_line_flag(self):
        notes = {n.kind: n.whole_line for n in manuscript.find_notes(self.RAW)}
        self.assertFalse(notes["[[ ]]"])
        self.assertTrue(notes["표시"])

    def test_remove_keeps_the_sentence_readable(self):
        cleaned, count = manuscript.remove_notes(self.RAW)
        self.assertEqual(count, 4)
        self.assertIn("첫 문단이다. 이어지는 문장.", cleaned)
        self.assertNotIn("[[", cleaned)
        self.assertNotIn("※", cleaned)

    def test_remove_does_not_pile_up_blank_lines(self):
        cleaned, _ = manuscript.remove_notes(self.RAW)
        self.assertNotIn("\n\n\n", cleaned)

    def test_text_without_notes_is_unchanged(self):
        body = "# 1화\n\n그냥 글이다.\n"
        self.assertEqual(manuscript.remove_notes(body), (body, 0))
        self.assertEqual(manuscript.find_notes(body), [])


class DocxTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.dest = self.root / "투고본.docx"
        self.chapters = [("1화 만남", "첫 문단.\n\n＊\n\n둘째 <태그> 문단."),
                         ("2화 이별", "마지막 문단.")]

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, **kw):
        import zipfile

        manuscript.export_docx(self.chapters, self.dest, **kw)
        return zipfile.ZipFile(self.dest)

    def test_zip_has_the_three_required_parts(self):
        with self.make() as z:
            self.assertEqual(sorted(z.namelist()),
                             ["[Content_Types].xml", "_rels/.rels",
                              "word/document.xml"])

    def test_document_xml_parses(self):
        import xml.etree.ElementTree as ET

        with self.make(title="시험작") as z:
            ET.fromstring(z.read("word/document.xml"))

    def test_text_is_escaped_not_interpreted(self):
        with self.make() as z:
            body = z.read("word/document.xml").decode("utf-8")
        self.assertIn("&lt;태그&gt;", body)
        self.assertNotIn("<태그>", body)

    def test_each_chapter_starts_a_new_page(self):
        with self.make() as z:
            body = z.read("word/document.xml").decode("utf-8")
        self.assertEqual(body.count('w:type="page"'), 1)   # 첫 화 앞은 안 나눈다

    def test_title_page_adds_a_break_before_the_first_chapter(self):
        with self.make(title="시험작") as z:
            body = z.read("word/document.xml").decode("utf-8")
        self.assertEqual(body.count('w:type="page"'), 2)

    def test_scene_break_is_centered(self):
        with self.make() as z:
            body = z.read("word/document.xml").decode("utf-8")
        self.assertIn("＊ ＊ ＊", body)
        self.assertIn('w:jc w:val="center"', body)

    def test_korean_font_is_set(self):
        with self.make() as z:
            body = z.read("word/document.xml").decode("utf-8")
        self.assertIn(manuscript.DOCX_FONT, body)


if __name__ == "__main__":
    unittest.main()
