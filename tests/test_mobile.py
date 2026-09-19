"""폰 화면(mobile/) 시험.

브라우저 없이 볼 수 있는 것만 본다 - 파일이 다 있는지, 집 규칙을 지키는지,
그리고 무엇보다 터미널 쪽과 수가 어긋나지 않는지. 셈법을 한쪽만 고치면
폰과 PC 가 다른 답을 내고, 그건 조용히 틀리는 쪽이라 여기서 잡는다.
"""

import json
import re
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import life, sheet

여기 = Path(__file__).resolve().parents[1] / "mobile"
sys.path.insert(0, str(여기 / "tools"))


def 만드는이():
    """데이터를 만드는 그 코드를 그대로 불러 본다."""
    import make_data

    return make_data

앱 = (여기 / "index.html").read_text(encoding="utf-8")


class FilesTest(unittest.TestCase):
    def test_every_file_the_manifest_needs_is_there(self):
        데이터 = json.loads((여기 / "manifest.webmanifest").read_text(encoding="utf-8"))
        for one in 데이터["icons"]:
            self.assertTrue((여기 / one["src"]).is_file(), one["src"])
        for name in ("index.html", "sw.js", "README.md"):
            self.assertTrue((여기 / name).is_file(), name)

    def test_service_worker_caches_exactly_what_ships(self):
        """캐시 목록에 없는 파일은 오프라인에서 안 나온다."""
        sw = (여기 / "sw.js").read_text(encoding="utf-8")
        적힌 = set(re.findall(r'"\./([\w.-]+)"', sw))
        # sw.js 자신은 브라우저가 따로 받는다. 캐시에 넣으면 새 판이 안 깔린다.
        # .bat 은 폰이 받는 것이 아니라 PC 에서 서버를 띄우는 도구다.
        있는 = {p.name for p in 여기.iterdir()
                if p.is_file() and p.suffix not in (".md", ".bat") and p.name != "sw.js"}
        self.assertEqual(있는 - 적힌, set())

    def test_icons_are_real_png(self):
        for name in ("icon-192.png", "icon-512.png"):
            self.assertEqual((여기 / name).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_page_declares_korean_and_a_viewport(self):
        self.assertIn('<html lang="ko">', 앱)
        self.assertIn("viewport-fit=cover", 앱)
        self.assertIn('<link rel="manifest"', 앱)

    def test_no_emoji(self):
        """집 규칙이다 - 터미널이든 화면이든 이모지는 쓰지 않는다."""
        나온것 = [c for c in 앱 if ord(c) > 0x1F000]
        self.assertEqual(나온것, [])

    def test_dark_theme_only_redefines_tokens(self):
        """색을 어두운 블록 안에서만 정하면 밝은 화면에서 글자가 사라진다."""
        밝은 = set(re.findall(r"--([\w-]+):", 앱.split("@media")[0]))
        어두운 = set(re.findall(r"--([\w-]+):", 앱.split("@media")[1].split("}")[0]))
        self.assertEqual(어두운 - 밝은, set())


class SameNumbersTest(unittest.TestCase):
    """폰과 터미널이 같은 수를 써야 한다."""

    def 숫자(self, 이름):
        찾음 = re.search(r"\b" + 이름 + r" = ([\d.]+)", 앱)
        self.assertIsNotNone(찾음, 이름)
        return float(찾음.group(1))

    def test_minimum_wage_matches(self):
        self.assertEqual(self.숫자("최저시급"), life.MIN_WAGE)
        self.assertEqual(self.숫자("최저해"), life.MIN_WAGE_YEAR)

    def test_monthly_hours_match(self):
        self.assertEqual(self.숫자("월시간"), life.MONTHLY_HOURS)
        self.assertEqual(self.숫자("주수"), life.WEEKS_IN_MONTH)

    def test_insurance_rates_match(self):
        적힌 = dict((이름, float(값)) for 이름, 값 in
                    re.findall(r'\["(국민연금|건강보험|장기요양|고용보험)", ([\d.]+),', 앱))
        self.assertEqual(적힌, {
            "국민연금": life.PENSION_RATE, "건강보험": life.HEALTH_RATE,
            "장기요양": life.CARE_RATE, "고용보험": life.JOB_RATE,
        })

    def test_daily_wage_tax_matches(self):
        self.assertIn(str(life.DAILY_DEDUCT), 앱)
        self.assertIn("0.027", 앱)
        self.assertIn("0.03", 앱)            # 사업소득 3%

    def test_meal_cap_matches(self):
        self.assertIn(str(life.MEAL_CAP), 앱)

    def test_period_multipliers_match(self):
        적힌 = dict((이름, eval(식)) for 이름, 식 in       # noqa: S307 - 시험 안의 상수식
                    re.findall(r'"(월|년|주|분기|반기)": ([\d /.]+?)[,}]', 앱))
        for 이름, 값 in 적힌.items():
            self.assertAlmostEqual(값, sheet.PERIODS[이름], places=6, msg=이름)

    def test_export_header_is_what_the_cli_reads(self):
        """폰에서 내보낸 csv 를 at sheet ledger 가 그대로 읽어야 한다."""
        머리 = re.search(r'const 줄 = \["([^"]+)"\]', 앱).group(1)
        self.assertEqual(머리, "날짜,내용,분류,구분,금액")
        표 = sheet.Table(머리.split(","),
                         [["2026-09-01", "월세", "주거", "지출", 450000],
                          ["2026-09-25", "월급", "급여", "수입", 2810000]])
        got = sheet.ledger(표, when="날짜", amount="금액", name="내용",
                           group="분류", kind="구분")
        달 = got.months()[0]
        self.assertEqual((달.income, 달.expense), (2810000, 450000))

    def test_repeat_threshold_matches(self):
        self.assertIn("되풀이찾기(3)", 앱)


class EmbeddedDataTest(unittest.TestCase):
    """화면 안에 끼운 명령·레시피·단축키가 지금 저장소와 같아야 한다.

    명령을 더하고 make_data.py 를 안 돌리면 폰의 «명령 찾기» 가 조용히 옛것이
    된다. 여기서 세어 본다.
    """

    def setUp(self):
        찾음 = re.search(r"window\.ATDATA = (\{.*?\});\n", 앱, re.S)
        self.assertIsNotNone(찾음, "끼운 데이터를 찾지 못했습니다")
        self.데이터 = json.loads(찾음.group(1))

    def test_command_list_matches_the_parser(self):
        self.assertEqual(self.데이터["명령"], 만드는이().commands())

    def test_recipes_match(self):
        self.assertEqual(self.데이터["레시피"], 만드는이().cookbook())

    def test_shortcuts_match(self):
        self.assertEqual(self.데이터["단축키"], 만드는이().shortcuts())

    def test_every_tool_names_a_real_command(self):
        """도구가 적어 둔 «짝이 되는 명령» 이 진짜 있는 명령이어야 한다."""
        있는 = {갈래 + " " + 이름 for 갈래, 이름, _말 in self.데이터["명령"]}
        for 한줄 in re.findall(r'명령: "([^"]+)"', 앱):
            for 하나 in 한줄.split(" · "):
                말 = 하나.replace("at ", "").strip()
                if " " not in 말:
                    continue
                갈래 = 말.split()[0]
                for 이름 in 말.split()[1:]:
                    if 이름.startswith("("):
                        continue
                    self.assertIn(갈래 + " " + 이름, 있는, 한줄)


if __name__ == "__main__":
    unittest.main()
