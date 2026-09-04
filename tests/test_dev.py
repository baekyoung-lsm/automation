"""개발 잡일: .env, JWT, 시각, 재시도, 로그, cron, 의존성 시험."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import deps, devkit, logkit, names, text
from attools.schedule import Cron, CronError


class DevkitTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_env_diff(self):
        (self.root / ".env.example").write_text(
            'DB_HOST=localhost\nAPI_KEY=your-key-here\nDEBUG=true\n', encoding="utf-8")
        (self.root / ".env").write_text(
            'DB_HOST="127.0.0.1"\nAPI_KEY=your-key-here\nDEBUG=\nEXTRA=1\n', encoding="utf-8")
        d = devkit.env_diff(self.root / ".env.example", self.root / ".env")
        self.assertEqual(d.missing, [])
        self.assertEqual(d.empty, ["DEBUG"])
        self.assertEqual(d.placeholder, ["API_KEY"])
        self.assertEqual(d.extra, ["EXTRA"])
        self.assertFalse(d.ok)

    def test_parse_env_quotes_and_comments(self):
        (self.root / ".env").write_text(
            "export A='1' # 주석\nB=\"두 단어\"\n# 통째 주석\nC=3\n", encoding="utf-8")
        self.assertEqual(devkit.parse_env(self.root / ".env"),
                         {"A": "1", "B": "두 단어", "C": "3"})

    def test_build_example_never_leaks_secrets(self):
        (self.root / ".env").write_text(
            "DB_HOST=10.0.0.5\nDB_PASSWORD=s3cr3t!\nAPI_KEY=sk_live_x\n"
            "DB_PORT=5432\nDEBUG=true\n", encoding="utf-8")

        text, added = devkit.build_example(self.root / ".env")
        self.assertNotIn("s3cr3t", text)
        self.assertNotIn("sk_live", text)
        self.assertIn("DB_PASSWORD=<db_password>", text)
        self.assertIn("DB_PORT=5432", text)      # 숫자·불리언은 그대로 둔다
        self.assertIn("DEBUG=true", text)
        self.assertEqual(len(added), 5)

    def test_build_example_keeps_comments_and_marks_removed(self):
        (self.root / ".env").write_text("A=1\nNEW=x\n", encoding="utf-8")
        (self.root / ".env.example").write_text(
            "# 주석\nA=<a>\nOLD=<old>\n", encoding="utf-8")

        text, added = devkit.build_example(self.root / ".env",
                                           existing=self.root / ".env.example")
        self.assertIn("# 주석", text)
        self.assertIn("# (지워진 키) OLD=<old>", text)
        self.assertIn("NEW=<new>", text)
        self.assertEqual(added, ["NEW"])

    def test_build_example_keep_values_still_hides_secrets(self):
        (self.root / ".env").write_text("URL=https://a.b\nTOKEN=abcdef\n",
                                        encoding="utf-8")
        text, _ = devkit.build_example(self.root / ".env", keep_values=True)
        self.assertIn("URL=https://a.b", text)
        self.assertNotIn("abcdef", text)

    def test_time_roundtrip(self):
        dt = devkit.parse_when("1700000000")
        self.assertEqual(devkit.when_report(dt)["epoch"], "1700000000")
        self.assertEqual(devkit.parse_when("1700000000000"), dt)

    def test_jwt(self):
        import base64
        import json
        import time

        def seg(obj):
            return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

        token = f"{seg({'alg': 'HS256'})}.{seg({'exp': int(time.time()) - 10})}.sig"
        info = devkit.decode_jwt(token)
        self.assertTrue(info["expired"])
        self.assertTrue(info["signed"])

    def test_open_port_dataclass(self):
        port = devkit.OpenPort(8080, 123, "python3", "127.0.0.1")
        self.assertEqual((port.port, port.pid, port.name), (8080, 123, "python3"))

    def test_listening_ports_returns_sorted_list(self):
        import shutil as _shutil

        if not (_shutil.which("lsof") or _shutil.which("ss")):
            self.skipTest("lsof 도 ss 도 없습니다")
        ports = devkit.listening_ports()
        self.assertEqual(ports, sorted(ports, key=lambda p: (p.port, p.pid)))
        self.assertTrue(all(p.port > 0 for p in ports))

    def test_bench_statistics(self):
        r = devkit.BenchResult("x", times=[0.10, 0.20, 0.30, 0.40])
        self.assertEqual(r.runs, 4)
        self.assertAlmostEqual(r.mean, 0.25)
        self.assertAlmostEqual(r.median, 0.25)
        self.assertAlmostEqual(r.fastest, 0.10)
        self.assertAlmostEqual(r.slowest, 0.40)
        self.assertGreater(r.stdev, 0)

    def test_bench_empty_and_single(self):
        self.assertEqual(devkit.BenchResult("x").mean, 0.0)
        self.assertEqual(devkit.BenchResult("x").median, 0.0)
        self.assertEqual(devkit.BenchResult("x", times=[0.5]).stdev, 0.0)
        self.assertEqual(devkit.BenchResult("x", times=[1, 2, 3]).median, 2)

    def test_bench_runs_and_skips_warmup(self):
        r = devkit.run_bench(["python3", "-c", "pass"], runs=3, warmup=1)
        self.assertEqual(r.runs, 3)          # 예열은 결과에 넣지 않는다
        self.assertEqual(r.failures, 0)
        self.assertTrue(all(t > 0 for t in r.times))

    def test_bench_counts_failures(self):
        r = devkit.run_bench(["python3", "-c", "raise SystemExit(1)"],
                             runs=2, warmup=0)
        self.assertEqual(r.failures, 2)

    def test_format_seconds(self):
        self.assertEqual(devkit.format_seconds(0.0123), "12.3ms")
        self.assertEqual(devkit.format_seconds(2.5), "2.50초")
        self.assertTrue(devkit.format_seconds(75).startswith("1분"))

    def test_mask(self):
        text = "주민 900101-1234567 폰 010-1234-5678 pw=hunter22 메일 hong@ex.com"  # attools: ignore
        masked, counts = devkit.mask_text(text)
        self.assertNotIn("1234567", masked)
        self.assertNotIn("hunter22", masked)
        self.assertIn("010-****-5678", masked)
        self.assertEqual(counts["주민등록번호"], 1)


    def test_retry_stops_at_first_success(self):
        waited = []
        attempts = devkit.retry(["sh", "-c", "exit 0"], tries=3,
                                sleeper=waited.append)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].code, 0)
        self.assertEqual(waited, [])

    def test_retry_backs_off_and_keeps_last_code(self):
        waited = []
        attempts = devkit.retry(["sh", "-c", "exit 7"], tries=4, delay=1,
                                backoff=2, sleeper=waited.append)
        self.assertEqual(len(attempts), 4)
        self.assertEqual(attempts[-1].code, 7)
        self.assertEqual(waited, [1, 2, 4])

    def test_retry_caps_the_wait(self):
        waited = []
        devkit.retry(["sh", "-c", "exit 1"], tries=5, delay=10, backoff=10,
                     max_delay=30, sleeper=waited.append)
        self.assertEqual(waited, [10, 30, 30, 30])

    def test_retry_runs_once_even_with_zero_tries(self):
        self.assertEqual(len(devkit.retry(["true"], tries=0, sleeper=lambda s: None)), 1)


class CronTest(unittest.TestCase):
    def runs(self, expr, start, n=3):
        from datetime import datetime
        return [d.strftime("%Y-%m-%d %H:%M") for d in Cron(expr).next_runs(start, n)]

    def test_weekday_schedule(self):
        from datetime import datetime
        self.assertEqual(
            self.runs("0 9 * * 1-5", datetime(2026, 9, 4, 10, 0), 3),
            ["2026-09-07 09:00", "2026-09-08 09:00", "2026-09-09 09:00"])

    def test_step_and_macro(self):
        from datetime import datetime
        self.assertEqual(self.runs("*/15 * * * *", datetime(2026, 1, 1, 0, 1), 2),
                         ["2026-01-01 00:15", "2026-01-01 00:30"])
        self.assertEqual(self.runs("@monthly", datetime(2026, 1, 5, 0, 0), 1),
                         ["2026-02-01 00:00"])

    def test_dom_or_dow(self):
        # 일/요일이 둘 다 지정되면 cron 은 OR 로 본다
        from datetime import datetime
        got = self.runs("0 0 13 * 5", datetime(2026, 3, 1, 0, 0), 3)
        self.assertEqual(got, ["2026-03-06 00:00", "2026-03-13 00:00", "2026-03-20 00:00"])

    def test_named_month_and_dow(self):
        from datetime import datetime
        self.assertEqual(self.runs("0 0 * JAN MON", datetime(2025, 12, 1), 1),
                         ["2026-01-05 00:00"])

    def test_invalid(self):
        for bad in ("0 9 * *", "99 * * * *", "0 9 * * 9", "*/0 * * * *"):
            with self.assertRaises(CronError):
                Cron(bad)


class LogkitTest(unittest.TestCase):
    SAMPLE = [
        "2026-09-03 10:00:01 INFO  요청 시작 user=1234",
        "2026-09-03 10:00:02 ERROR 결제 실패 order=8821 amount=15,000",
        "  at com.app.Pay.run(Pay.java:42)",
        "2026-09-03 10:00:05 ERROR 결제 실패 order=8822 amount=7,500",
        "2026-09-03 11:30:00 WARNING 응답 지연 1200ms",
        "2026-09-03 11:30:10 ERROR DB 연결 실패 10.0.0.5:5432",
    ]

    def test_parse_attaches_stack_traces(self):
        entries = logkit.parse(self.SAMPLE)
        self.assertEqual(len(entries), 5)          # 트레이스 줄은 앞 항목에 붙는다
        self.assertIn("Pay.java", entries[1].raw)

    def test_level_and_time_parsing(self):
        entries = logkit.parse(self.SAMPLE)
        self.assertEqual(entries[0].level, "INFO")
        self.assertEqual(entries[3].level, "WARN")   # WARNING 은 WARN 으로 통일
        self.assertEqual(entries[0].when.hour, 10)

    def test_level_counts_ordered_by_severity(self):
        counts = logkit.level_counts(logkit.parse(self.SAMPLE))
        self.assertEqual(list(counts), ["ERROR", "WARN", "INFO"])
        self.assertEqual(counts["ERROR"], 3)

    def test_normalize_collapses_varying_values(self):
        a = logkit.normalize("결제 실패 order=8821 amount=15,000")
        b = logkit.normalize("결제 실패 order=8822 amount=7,500")
        self.assertEqual(a, b)
        self.assertIn("<ip>", logkit.normalize("연결 실패 10.0.0.5:5432"))
        self.assertIn("<uuid>", logkit.normalize(
            "id=550e8400-e29b-41d4-a716-446655440000"))

    def test_group_messages_merges_same_incident(self):
        groups = logkit.group_messages(logkit.parse(self.SAMPLE), levels={"ERROR"})
        self.assertEqual(groups[0].count, 2)
        self.assertEqual(groups[0].lines, [2, 4])
        self.assertEqual(groups[0].level, "ERROR")

    def test_histogram_buckets(self):
        series = logkit.histogram(logkit.parse(self.SAMPLE), bucket="1h")
        self.assertEqual([c for _, c in series], [3, 2])
        with self.assertRaises(ValueError):
            logkit.histogram([], bucket="7초")

    def test_histogram_respects_level_filter(self):
        series = logkit.histogram(logkit.parse(self.SAMPLE), bucket="1h",
                                  levels={"ERROR"})
        self.assertEqual([c for _, c in series], [2, 1])

    def test_spikes_need_a_real_jump(self):
        from datetime import datetime, timedelta

        base = datetime(2026, 9, 3, 8)
        flat = [(base + timedelta(hours=i), 2) for i in range(6)]
        self.assertEqual(logkit.spikes(flat), [])

        flat[3] = (flat[3][0], 40)
        found = logkit.spikes(flat)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1], 40)

    def test_strip_prefix_leaves_message(self):
        self.assertEqual(
            logkit.strip_prefix("2026-09-03 10:00:02 ERROR 결제 실패"), "결제 실패")

    def test_span(self):
        first, last = logkit.span(logkit.parse(self.SAMPLE))
        self.assertEqual((first.hour, last.hour), (10, 11))
        self.assertEqual(logkit.span([]), (None, None))


    LOG = [
        "2026-09-01 10:00:01 INFO GET /api/users/12 200 34ms",
        "2026-09-01 10:00:02 INFO GET /api/users/13 200 1.2s",
        "2026-09-01 10:00:03 INFO POST /api/orders 201 250 ms",
        "2026-09-01 10:00:04 INFO 시간 없는 줄",
    ]

    def test_duration_reads_units(self):
        self.assertEqual(logkit.duration_ms("걸린 시간 34ms"), 34.0)
        self.assertEqual(logkit.duration_ms("1.2s 걸림"), 1200.0)
        self.assertEqual(logkit.duration_ms("30 seconds"), 30000.0)
        self.assertEqual(logkit.duration_ms("250 ms"), 250.0)

    def test_duration_ignores_bare_numbers(self):
        self.assertIsNone(logkit.duration_ms("status 200 bytes 1234"))

    def test_duration_takes_last_value(self):
        self.assertEqual(logkit.duration_ms("db 10ms 총 50ms"), 50.0)

    def test_route_normalizes_ids(self):
        self.assertEqual(logkit.route_of("GET /api/users/12?x=1 200"),
                         "GET /api/users/{n}")
        self.assertEqual(logkit.route_of("post /orders 201"), "POST /orders")
        self.assertEqual(logkit.route_of("그냥 줄"), "")

    def test_percentile_picks_real_values(self):
        values = [float(n) for n in range(1, 11)]
        self.assertEqual(logkit.percentile(values, 50), 5)
        self.assertEqual(logkit.percentile(values, 95), 10)
        self.assertEqual(logkit.percentile(values, 100), 10)
        self.assertEqual(logkit.percentile([], 50), 0.0)

    def test_timings_skips_lines_without_duration(self):
        timed = logkit.timings(logkit.parse(self.LOG))
        self.assertEqual([t.ms for t in timed], [34.0, 1200.0, 250.0])

    def test_timings_with_custom_pattern(self):
        import re

        lines = ["요청 처리 지연=120 완료", "지연 없음"]
        timed = logkit.timings(logkit.parse(lines), pattern=re.compile(r"지연=(\d+)"))
        self.assertEqual([t.ms for t in timed], [120.0])

    def test_by_route_groups_and_sorts(self):
        stats = logkit.by_route(logkit.timings(logkit.parse(self.LOG)), sort="p95")
        self.assertEqual(stats[0].route, "GET /api/users/{n}")
        self.assertEqual(stats[0].count, 2)
        self.assertEqual(stats[0].p(50), 34.0)
        self.assertEqual(stats[0].avg, 617.0)

    def test_by_route_keeps_unmatched_lines_visible(self):
        timed = logkit.timings(logkit.parse(["작업 완료 30s"]))
        self.assertEqual(logkit.by_route(timed)[0].route, "(경로 없음)")


class DepsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name, content):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_requirements_parsing(self):
        p = self.write("requirements.txt",
                       "# 주석\ndjango==4.2.11\npsycopg2-binary>=2.9\nrequests\n"
                       "celery[redis]~=5.3.0\n-r other.txt\n")
        result = deps.read_file(p)
        self.assertEqual([d.name for d in result.deps],
                         ["django", "psycopg2-binary", "requests", "celery"])
        self.assertTrue(result.deps[0].pinned)
        self.assertFalse(result.deps[1].pinned)
        self.assertFalse(result.deps[2].pinned)   # 조건이 없으면 고정이 아니다
        self.assertTrue(result.notes)             # -r 은 메모로 남긴다

    def test_package_json_groups(self):
        p = self.write("package.json",
                       '{"dependencies":{"react":"18.3.1","axios":"^1.6.0"},'
                       '"devDependencies":{"vitest":"~1.4.0"}}')
        result = deps.read_file(p)
        by_name = {d.name: d for d in result.deps}
        self.assertTrue(by_name["react"].pinned)      # 정확한 버전
        self.assertFalse(by_name["axios"].pinned)     # ^ 는 범위
        self.assertEqual(by_name["vitest"].group, "개발")

    def test_package_json_broken(self):
        p = self.write("package.json", "{망가짐")
        result = deps.read_file(p)
        self.assertEqual(result.deps, [])
        self.assertTrue(result.notes)

    def test_go_mod_parsing(self):
        p = self.write("go.mod",
                       "module x\ngo 1.22\nrequire (\n"
                       "    github.com/gin-gonic/gin v1.9.1\n"
                       "    github.com/x/y v1.0.0 // indirect\n)\n"
                       "require golang.org/x/sync v0.6.0\n")
        result = deps.read_file(p)
        self.assertEqual(len(result.deps), 3)
        self.assertTrue(all(d.pinned for d in result.deps))   # go.mod 는 늘 고정

    def test_pyproject_parsing(self):
        p = self.write("pyproject.toml",
                       '[project]\nname = "x"\ndependencies = ["requests>=2", "click==8.1"]\n'
                       '[project.optional-dependencies]\ntest = ["pytest==8.1"]\n')
        result = deps.read_file(p)
        names = {d.name for d in result.deps}
        self.assertEqual(names, {"requests", "click", "pytest"})
        groups = {d.name: d.group for d in result.deps}
        self.assertEqual(groups["pytest"], "test")

    def test_find_files(self):
        self.write("pyproject.toml", "[project]\n")
        self.write("requirements.txt", "x\n")
        self.write("requirements/dev.txt", "y\n")
        found = {p.name for p in deps.find_files(self.root)}
        self.assertEqual(found, {"pyproject.toml", "requirements.txt", "dev.txt"})

    def test_conflicts_between_files(self):
        a = deps.read_file(self.write("requirements.txt", "django==4.2\n"))
        b = deps.read_file(self.write("requirements/dev.txt", "django>=4.0\n"))
        found = deps.conflicts([a, b])
        self.assertEqual([name for name, _ in found], ["django"])

    def test_no_conflict_when_specs_agree(self):
        a = deps.read_file(self.write("requirements.txt", "django==4.2\n"))
        b = deps.read_file(self.write("requirements/dev.txt", "django==4.2\n"))
        self.assertEqual(deps.conflicts([a, b]), [])

    def test_unknown_file(self):
        with self.assertRaises(ValueError):
            deps.read_file(self.write("Gemfile", "gem 'rails'\n"))


if __name__ == "__main__":
    unittest.main()
