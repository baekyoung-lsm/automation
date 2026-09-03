# attools 작업 규칙

한국에서 쓰는 파일 정리·백엔드 개발·엑셀 실무·단축키·일상 계산·소설 집필
자동화를 한 CLI(`at`)로 묶은 저장소.

## 지켜야 할 것

**표준 라이브러리만 쓴다.** 외부 의존성은 넣지 않는다. xlsx 도 zipfile 과
xml.etree 로 직접 읽고 쓴다(`attools/xlsx.py`). 새 의존성이 필요해 보이면
먼저 물어본다.

**파일을 바꾸는 명령은 기본이 미리보기다.** `--apply` 를 붙여야 실제로 쓰고,
되돌릴 수 있어야 한다.
- 파일 이동·개명: `files.apply_moves` → `~/.attools/journal/` → `at file undo`
- 파일 내용 변경: `text.apply_changes` → `~/.attools/text/<시각>/` → `at text undo`
- 지우는 동작(`archive --remove`)은 먼저 검증하고, 검증에 실패하면 지우지 않는다.

**출력은 한국어다.** 도움말, 오류 메시지, 표 머리글 전부. 이모지는 쓰지 않는다.

**모르는 것을 그럴듯하게 채우지 않는다.** `attools/data/shortcuts.json` 은
확인한 단축키만 넣고, 확인 못 한 칸은 `null`(표시는 `?`), 기본 단축키가 없는
기능은 `"없음"`(표시는 `—`)으로 구분한다. `at keys --gaps` 로 남은 것을 본다.
`life.py` 의 공휴일도 음력 명절은 계산하지 않고 경고를 띄운다.

## 구조

```
at                  실행 스크립트
attools/
  cli.py            argparse 배선과 명령 핸들러 (여기만 사용자에게 보이는 문구)
  files.py          분류·개명·중복·감시·용량·압축·디렉터리 비교
  text.py           여러 파일 찾아 바꾸기·인코딩·줄바꿈·공백
  hangul.py         NFC 정규화, 파일명 정리, 받침·조사
  devkit.py         .env, 포트, JWT, 시각, 마스킹, 대기, 생성기, 벤치
  gitkit.py         브랜치 정리, 시크릿 검사, 커밋 통계
  todo.py           TODO/FIXME 수집 (주석 안에 있을 때만)
  logkit.py         로그 집계·분포·반복 에러 묶기
  jsonkit.py        JSON 스키마·비교·평탄화
  mdkit.py          마크다운 목차·링크·제목 점검
  sheet.py          표 모델과 csv/xlsx 입출력, 정리·검증·집계·필터·메일머지
  xlsx.py           의존성 없는 xlsx 리더/라이터
  keys.py keytui.py keyhtml.py   단축키 데이터·터미널 화면·HTML 내보내기
  life.py           금액·D-day·정산·대출·단위·공휴일
  manuscript.py     원고 분량·반복·장면·시간선·문체
  names.py          고유명사 추출, 표기 흔들림, 이름 뒤 조사 검사
  schedule.py       cron 해석
  data/shortcuts.json
tests/test_attools.py
```

## 명령을 추가할 때

1. 로직은 해당 모듈에 순수 함수·데이터클래스로 넣는다. 출력(`print`)은 하지 않는다.
2. `cli.py` 에 `cmd_<그룹>_<이름>` 핸들러와 서브파서를 더한다. 표는 `_grid`,
   한글 폭 맞춤은 `_pad`·`_cut` 를 쓴다.
3. 테스트를 쓴다. 로직 단위 테스트 + `CliWiringTest` 가 배선을 자동으로 훑는다.
4. README 표와 예시에 한 줄 더한다. 그 뒤 `at doc toc README.md --apply`.

## 확인

```bash
python3 -m unittest discover -s tests    # 전부 통과해야 한다
./at git scan                            # 자기 저장소 시크릿 검사
./at doc links README.md                 # 링크 검사
```

커밋 전에 셋 다 돌린다. CI 도 같은 것을 돌린다.

## 커밋 메시지

무엇을 왜 바꿨는지 한국어로 쓴다. 특히 **왜 그렇게 했는지**(오탐을 줄이려고,
조용히 틀리는 것을 막으려고 같은 이유)를 남긴다. 나중에 그 판단을 되짚을 때 쓴다.
