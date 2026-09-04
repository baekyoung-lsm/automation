# attools

파일 정리, 백엔드 개발 잡일, git 관리, 엑셀 실무, 단축키 찾기, 일상 계산,
소설 원고 관리를 한 CLI로 묶은 도구.
표준 라이브러리만 쓰고 외부 의존성은 없다. Python 3.10+.

- `file` 파일 분류·이름 정리·중복 탐지·변경 감시
- `dev` .env 대조, 포트, JWT, 시각 변환, 로그 마스킹, 헬스체크 대기, cron 해석, 키 생성
- `git` 병합된 브랜치 정리, 커밋 전 시크릿 검사
- `text` 여러 파일 찾아 바꾸기, 인코딩·줄바꿈 통일, 공백 정리
- `json` API 응답 구조 요약, 두 응답 비교, 평탄화
- `doc` 마크다운 목차 갱신, 깨진 링크·앵커 검사
- `sheet` 엑셀·CSV 훑어보기, 검증, 정리, 병합, 비교, 집계, 변환
- `keys` 한글·Word·엑셀·PPT·구글 문서 단축키를 탭으로 넘겨 보고 검색
- `life` D-day, 더치페이 정산, 대출 계산, 단위 변환
- `novel` 원고 분량 집계, 반복·상투구 점검, 스냅샷

```
git clone <repo> && cd automation
./at --help                 # 그대로 실행
ln -s "$PWD/at" ~/.local/bin/at   # 또는 PATH 에 링크
pip install -e .            # 또는 패키지로 설치 (at 명령 생성)
```

<!-- toc -->

- [file — 파일 정리](#file--파일-정리)
- [dev — 백엔드 개발](#dev--백엔드-개발)
- [text — 여러 파일 텍스트 일괄 처리](#text--여러-파일-텍스트-일괄-처리)
- [json — API 응답 훑기와 비교](#json--api-응답-훑기와-비교)
- [doc — 마크다운 유지보수](#doc--마크다운-유지보수)
- [git — 저장소 정리와 검사](#git--저장소-정리와-검사)
- [sheet — 엑셀·CSV 실무](#sheet--엑셀csv-실무)
- [keys — 단축키 찾기](#keys--단축키-찾기)
- [life — 일상 계산](#life--일상-계산)
- [novel — 소설 집필](#novel--소설-집필)
- [테스트](#테스트)

<!-- /toc -->

파일을 옮기거나 이름을 바꾸는 명령은 **기본이 미리보기**다. `--apply` 를 붙여야 실제로 실행되고,
실행 내역은 `~/.attools/journal/` 에 남아 `at file undo` 로 통째로 되돌릴 수 있다.

## file — 파일 정리

| 명령 | 하는 일 |
| --- | --- |
| `at file organize <디렉터리>` | 확장자 종류(문서/이미지/영상/압축/코드…)나 날짜별로 분류해 옮긴다 |
| `at file fixname <디렉터리>` | macOS에서 넘어온 한글 자모 분리(NFD) 파일명을 완성형으로 고치고, 윈도우 금지문자·중복 공백을 정리한다 |
| `at file rename <디렉터리>` | 규칙에 맞춰 이름 일괄 변경 (날짜·번호·치환·접두사) |
| `at file dupes <디렉터리>` | 내용이 같은 파일을 찾는다. 직접 지우지 않고 `--script` 로 삭제 명령만 출력한다 |
| `at file watch <경로> -- <명령>` | 파일이 바뀌면 명령을 다시 실행한다 (테스트·빌드 자동 재실행) |
| `at file big [경로]` | 어디가 용량을 먹는지 디렉터리·파일 순위로 보여준다 |
| `at file diff <왼쪽> <오른쪽>` | 두 디렉터리 비교 — 한쪽에만 있는 파일, 내용이 다른 파일 |
| `at file archive <디렉터리>` | 오래된 파일을 zip 으로 묶고, 검증에 성공하면 원본 정리 |
| `at file undo [저널]` | 직전 organize/fixname 을 되돌린다 |

```bash
at file organize ~/Downloads --by ext-date --min-age 7 -v   # 미리보기
at file organize ~/Downloads --by ext-date --min-age 7 --apply
at file fixname ~/Documents -r --apply
at file rename ~/사진 -g '*.JPG' --date --seq --sort date --apply
at file rename ~/문서 --prefix '기획팀_' --replace '최종(수정)=v2' --apply
at file rename ~/스캔 -t '{parent}_{seq:03d}{ext}' --apply
at file diff 배포전/ 배포후/ -g '*.py'
at file archive ~/로그 --older 365 -g '*.log'            # 미리보기
at file archive ~/로그 --older 365 -g '*.log' --apply --remove
at file dupes ~/Pictures --script > 삭제후보.sh
at file watch src -p '*.py' -- pytest -q
at file big ~/Downloads --depth 2
at file undo
```

`diff` 는 크기가 같아도 해시를 비교하므로 **크기가 같고 내용만 바뀐 파일**을 잡는다.
`--quick` 은 크기만 봐서 빠르지만 그런 변경은 놓치고, 결과에 그 사실을 함께 알려 준다.

`archive` 는 압축한 뒤 zip 을 다시 열어 **모든 파일이 같은 크기로 들어갔는지 확인한 다음에만**
원본을 지운다. 확인에 실패하면 원본을 그대로 두고 무엇이 문제인지 알려 준다. 이미 있는
zip 파일에는 덮어쓰지 않는다.

`rename` 의 템플릿에는 `{seq}` `{date}` `{time}` `{stem}` `{ext}` `{name}` `{parent}` `{size}`
를 쓸 수 있고, `{seq:03d}` 처럼 자리수도 지정된다. 번호를 매기는 순서는 `--sort name|date|size`
로 고른다. 이름이 겹치면 ` (1)` 을 붙이고, `at file undo` 로 통째로 되돌린다.

분류 카테고리는 `attools/files.py` 의 `CATEGORIES` 에 있다. `hwp`, `hwpx`, `alz`, `egg` 처럼
한국에서 자주 쓰는 확장자를 포함한다.

## dev — 백엔드 개발

| 명령 | 하는 일 |
| --- | --- |
| `at dev env [예시] [실제]` | `.env.example` 과 `.env` 를 대조해 빠진 키·빈 값·예시 값 그대로인 키를 찾는다 (기본값: `.env.example` `.env`) |
| `at dev port <포트>` | 포트를 잡고 있는 프로세스를 찾고 `--kill` 로 종료한다 |
| `at dev jwt <토큰>` | JWT 헤더·페이로드를 디코드하고 `exp`/`iat` 를 KST로 보여준다 (서명 검증 안 함) |
| `at dev time [값]` | epoch(초/밀리초)·ISO 문자열·`now` 를 KST/UTC/epoch 로 상호 변환한다 |
| `at dev bench -- <명령>` | 명령을 여러 번 돌려 실행 시간을 재고 두 방식을 비교 |
| `at dev log <파일…>` | 레벨 집계, 시간대 분포, 급증 구간, 반복되는 에러 묶기 |
| `at dev mask [파일]` | 로그를 공유하기 전에 주민등록번호·전화·카드·이메일·토큰·비밀번호를 가린다 |
| `at dev wait <대상>` | `host:port` 나 URL 이 응답할 때까지 기다린다. 컨테이너 띄운 뒤 헬스체크용 |
| `at dev cron <표현식>` | cron 표현식을 한국어로 풀어 주고 다음 실행 시각을 KST로 보여준다 |
| `at dev gen [종류]` | 비밀번호·토큰·hex·UUID·PIN 을 CSPRNG 로 만든다 |
| `at dev enc <값>` | base64/base64url/hex/URL 인코딩과 해시를 한 번에, 디코딩도 자동 시도 |

```bash
at dev env                       # 배포 전 .env 점검, 문제 있으면 exit 1
at dev env --sync                # .env 에서 .env.example 을 만든다 (미리보기)
at dev env --sync --apply
at dev port 8080 --kill
at dev time 1750000000
kubectl logs pod | at dev mask > 공유용.log
pbpaste | at dev jwt -
at dev wait localhost:5432 -t 60 && ./migrate.sh
at dev cron "30 2 * * 6"
at dev gen password -l 20 --readable
at dev enc "SGVsbG8gd29ybGQ="
at dev bench -n 20 -- pytest -q
at dev bench --cmd "sort a.txt" --cmd "sort -S1M a.txt"   # 두 방식 비교
at dev log app.log                      # 전체 요약
at dev log app.log -l ERROR -b 10m      # 에러만 10분 단위로
kubectl logs pod | at dev log -
```

`at dev bench` 는 첫 실행(캐시가 비어 느린 회차)을 예열로 빼고 잰다. 두 명령을 비교할 때
중앙값 차이가 편차보다 작으면 "차이가 뚜렷하지 않다"고 알려 준다 — 측정 잡음을 개선으로
착각하지 않기 위해서다.

`at dev log` 는 숫자·UUID·IP·경로·따옴표 문자열을 `<n>`, `<uuid>` 같은 자리표시자로 바꿔서
같은 사고끼리 묶는다. `결제 실패 order=8821` 과 `order=8822` 가 한 줄로 합쳐지므로
"무엇이 몇 번 터졌는지"가 바로 보인다. 스택 트레이스 줄은 앞 항목에 붙이고,
평소 건수의 3배 이상 튄 구간은 급증으로 따로 알려 준다.

`at dev env` 는 문제가 있으면 종료 코드 1을 돌려주므로 CI나 배포 스크립트에 그대로 넣을 수 있다.

`--sync` 는 `.env` 에서 `.env.example` 을 만든다. 비밀값은 항상 `<이름>` 자리표시자로 바꾸고,
포트 번호나 `true/false` 처럼 감출 것 없는 값은 그대로 둔다. 기존 example 이 있으면 주석과
순서를 살리고, 사라진 키는 주석 처리, 새 키는 아래에 덧붙인다.

## text — 여러 파일 텍스트 일괄 처리

| 명령 | 하는 일 |
| --- | --- |
| `at text replace <찾을것> <바꿀것> [경로]` | 여러 파일에서 찾아 바꾸기. `-e` 정규식, `-i` 대소문자 무시, `-w` 단어 단위 |
| `at text encoding [경로]` | cp949·euc-kr 로 저장된 파일을 utf-8 로 통일 |
| `at text eol [경로]` | 줄바꿈을 LF 또는 CRLF 로 통일 |
| `at text trim [경로]` | 줄 끝 공백 제거, 파일 끝 개행 보정, 탭 → 공백 |
| `at text undo [저널]` | 직전 작업 되돌리기 |

```bash
at text replace old.example.com api.example.com src/          # 미리보기 (차이까지)
at text replace old.example.com api.example.com src/ --apply
at text replace -e '(\d+)\.(\d+)\.(\d+)' 'v\1.\2' -g '*.md' --apply
at text encoding 인수인계자료/ --apply     # 예전 파일 무더기 utf-8 로
at text trim . -g '*.py' --apply
at text undo
```

기본은 미리보기다. 바뀌는 줄을 diff 로 먼저 보여 주고, `--apply` 를 붙여야 실제로 쓴다.
원본은 `~/.attools/text/<시각>/` 에 통째로 백업하므로 `at text undo` 로 되돌릴 수 있다.

정규식이 아니면 `.` 이나 `\` 도 문자 그대로 다룬다. BOM 이 있던 파일은 BOM 을 유지하고,
없던 파일에 BOM 을 붙이지 않는다. 이진 파일과 `node_modules`, `.git` 같은 디렉터리는
건너뛴다.

## json — API 응답 훑기와 비교

| 명령 | 하는 일 |
| --- | --- |
| `at json show [파일]` | 한글이 깨지지 않게 예쁘게 출력 (`--sort`, `--compact`) |
| `at json schema [파일]` | 키 경로·타입·가끔 없는 키·예시 값 요약 |
| `at json diff <이전> <이후>` | 사라진 키, 타입 바뀜, 새 키, 값 바뀜을 경로 단위로 |
| `at json flat [파일]` | `경로<탭>값` 한 줄씩 출력해서 grep 하기 좋게 |

```bash
curl -s ... | at json schema -
at json diff 어제응답.json 오늘응답.json --key id
at json diff v1.json v2.json --breaking      # 깨질 변화만, 있으면 exit 1
at json flat 응답.json --grep 'error|실패'
```

`--key id` 를 주면 객체 배열을 그 필드 값으로 짝지어 비교한다. 순서만 바뀐 응답이
전부 바뀐 것처럼 보이는 일을 막는다. `--breaking` 은 **사라진 키와 타입 변경**만 보고
하나라도 있으면 종료 코드 1을 돌려주므로 계약 회귀 검사로 CI 에 넣을 수 있다.

파일이 JSON 으로 안 읽히면 JSON Lines 로 한 번 더 시도한다.

## doc — 마크다운 유지보수

| 명령 | 하는 일 |
| --- | --- |
| `at doc toc <경로…>` | 제목에서 목차를 만들어 `<!-- toc -->` 사이를 갈아 끼운다 |
| `at doc links <경로…>` | 깨진 상대 경로 링크와 없는 앵커(`#제목`)를 찾는다 |
| `at doc check <경로…>` | 제목 단계 건너뜀(H2 → H4), 같은 제목 반복, H1 중복 |

```bash
at doc toc README.md              # 미리보기
at doc toc docs/ --apply --depth 2
at doc links docs/                # 깨진 게 있으면 exit 1
at doc check README.md --outline
```

앵커는 GitHub 규칙과 같게 만든다 — 소문자로 바꾸고 구두점을 떼고 공백을 `-` 로,
같은 제목이 또 나오면 `-1` 을 붙인다. 한글은 그대로 남는다. 코드 블록 안의 `#` 는
제목으로 세지 않는다. 외부 URL 은 확인하지 않는다(네트워크를 쓰지 않는다).

이 README 의 목차도 `at doc toc README.md --apply` 로 만든 것이다.

## git — 저장소 정리와 검사

| 명령 | 하는 일 |
| --- | --- |
| `at git sweep [경로]` | 기준 브랜치에 병합이 끝난 로컬 브랜치, 원격이 사라진 추적 브랜치를 찾아 지운다 |
| `at git scan [경로]` | 코드에 하드코딩된 API 키·토큰·개인 키·접속 문자열 비밀번호·주민등록번호를 찾는다 |
| `at git release [경로]` | 태그 이후 커밋으로 변경 로그 초안을 만든다 |
| `at git stats [경로]` | 커밋 통계, 사람별 기여, **자주 바뀌는 파일**, 기간·요일 분포 |
| `at git todo [경로]` | 코드의 TODO·FIXME·HACK·XXX·BUG 를 모아 담당자와 방치된 기간까지 보여준다 |

```bash
at git sweep --fetch              # 미리보기
at git sweep --fetch --apply
at git scan                       # 추적 중인 파일 전체
at git scan --staged --quiet      # 커밋 직전 검사, 발견되면 exit 1
at git scan --install-hook "$HOME/.local/bin/at"   # pre-commit 훅으로 설치
at git todo                       # 오래 방치된 순
at git todo -m FIXME -m BUG -s severity
at git todo --no-blame -g '*.py'  # 작성자 조회 없이 빠르게
at git release --title 0.12.0 --authors
at git release --since v0.11.0 -o CHANGELOG.md
at git stats --since '30 days ago' --by week
at git stats --path src/ --weekday
```

`at git release` 는 `feat:` `fix:` 같은 관례 접두사가 있으면 그것으로 묶고, `attools:` 처럼
저장소 나름의 말머리도 살려 쓴다. 접두사가 아예 없으면 바뀐 파일의 위치로 묶는다.
`feat!:` 처럼 `!` 가 붙은 커밋은 호환성 주의로 따로 표시한다. `-o CHANGELOG.md` 는
기존 내용 위에 새 절을 붙인다.

`at git stats` 의 "자주 바뀐 파일"은 그냥 통계가 아니다. 같은 파일이 계속 고쳐진다면
설계가 그 자리에 몰려 있거나 버그가 반복된다는 뜻이라, 리팩터링 대상을 고를 때 쓴다.

`at git todo` 는 표시가 **주석 안에 있을 때만** 센다. 문자열 리터럴의 `"TODO"` 까지 잡으면
쓸모가 없기 때문이다. `TODO(이름)` 이나 `TODO @이름` 으로 적힌 담당자가 있으면 그것을
쓰고, 없으면 `git blame` 이 알려준 마지막 수정자를 보여준다. 방치 기간도 blame 기준이다.

`your-key-here`, `${VAULT_SECRET}`, `os.environ[...]` 같은 플레이스홀더는 걸러 낸다.
테스트 픽스처처럼 일부러 넣은 값은 그 줄에 `# attools: ignore` 를 달면 넘어간다.
`--entropy 4.0` 을 주면 패턴에 안 걸리는 무작위 문자열도 함께 신고한다.

## sheet — 엑셀·CSV 실무

xlsx 는 XML 을 담은 zip 이라 **openpyxl 없이** 표준 라이브러리만으로 읽고 쓴다.
CSV 는 인코딩(utf-8 / cp949 / euc-kr)을 자동으로 알아내고, 저장할 때는 엑셀에서
한글이 깨지지 않도록 UTF-8 BOM 을 붙인다.

| 명령 | 하는 일 |
| --- | --- |
| `at sheet peek <파일>` | 시트 목록, 행·열 수, 열마다 타입·결측·고유값·최소/최대·예시 |
| `at sheet check <파일>` | 중복 키, 키 결측, 타입 혼재, 앞뒤·전각 공백, **문자로 저장된 숫자/날짜** |
| `at sheet clean <파일>` | 공백·전각 공백 정리, `"1,234원"` → 숫자, `2024.01.05` → 날짜, 빈 행·열·중복 행 제거 |
| `at sheet merge <파일들>` | 월별·부서별로 쪼개진 파일을 세로로 합치고 출처 열을 붙인다 |
| `at sheet diff <이전> <이후> --key <열>` | 키 기준으로 추가·삭제·변경된 값을 찾는다 |
| `at sheet pivot <파일> --rows <열>` | 그룹별 합계·평균·건수, `--cols` 로 교차표 |
| `at sheet cut <파일> -c <열>` | 열 고르기·순서 바꾸기 (`--drop` 이면 빼기) |
| `at sheet where <파일> --eq <열=값>` | 조건에 맞는 행만. `--gte`, `--lt`, `--has` 등 |
| `at sheet sort <파일> --by <열>` | 정렬. 빈 칸은 항상 뒤로 |
| `at sheet sample <파일> -n 100` | 표본 뽑기 (`--seed` 로 같은 표본 재현) |
| `at sheet split <파일> --by <열>` | 부서별·월별로 파일 쪼개기. `--rows 1000` 이면 행 수로 |
| `at sheet fill <명단> -t <틀>` | 행마다 틀을 채워 개인별 문서를 만든다 (메일 머지) |
| `at sheet convert <파일> -o <출력>` | csv ↔ xlsx 변환, 깨진 인코딩 정리 |

```bash
at sheet peek 매출.xlsx --sheet 1분기 -n 10
at sheet check 직원명부.xlsx --key 사번 --required 입사일
at sheet clean 원본.csv --dedupe -o 정리본.xlsx
at sheet merge 2026-*.csv -o 통합.xlsx
at sheet diff 지난달.xlsx 이번달.xlsx --key 사번
at sheet pivot 매출.xlsx --rows 부서 --cols 분기 --values 금액 --agg sum
at sheet convert 깨진파일.csv -o 정상.xlsx
at sheet cut 직원.xlsx -c 사번 -c 이름 -c 연봉 -o 요약.xlsx
at sheet where 직원.xlsx --eq 부서=개발 --gte 연봉=6000만 -o 대상.csv
at sheet sort 매출.xlsx --by 금액 --desc -o 정렬본.xlsx
at sheet split 전체.xlsx --by 부서 -o 부서별/ --apply
at sheet split 큰파일.csv --rows 5000 --apply     # 메일 첨부 크기로 쪼갤 때
at sheet fill 명단.csv -t 안내문틀.md -o 안내문/ --name '{사번}_{이름}.md' --apply
at sheet fill 명단.csv -t 틀.txt --single -o 합본.txt      # 한 파일로 이어 붙이기
```

`fill` 은 틀 안의 `{열이름}` 을 행 값으로 바꾼다. `{번호:03d}` 처럼 형식도 쓸 수 있고
`{{` 와 `}}` 는 중괄호 자체를 뜻한다. 표에 없는 자리표시자가 있으면 **먼저 알려 주고 멈춘다** —
오타 하나로 수백 개 파일에 빈칸이 들어가는 걸 막기 위해서다(`--force` 로 강행 가능).

`where` 의 값은 열 타입에 맞춰 비교한다. 숫자 열이면 `--gte 연봉=6000만` 처럼 한글 단위도
숫자로 읽고, 날짜 열이면 `--gte 입사일=2024-01-01` 로 날짜끼리 비교한다. 조건 여러 개는
기본이 AND 이고 `--any` 를 주면 OR 이다.

`check` 가 잡아 주는 것 중 실무에서 제일 자주 사고 나는 건 **문자로 저장된 숫자**다.
`SUM` 이 0으로 나오거나 정렬이 `1, 10, 2` 순으로 되는 원인이고, `clean` 을 돌리면
숫자·날짜로 바뀐다. 행 번호는 헤더를 1행으로 센 엑셀 기준으로 알려 준다.

값 해석 규칙: 앞에 0이 붙은 숫자(우편번호·사번)와 16자리 넘는 숫자(계좌번호)는
문자로 남긴다. `20240105` 처럼 날짜로도 읽히는 8자리 숫자는 날짜로 본다 —
그런 열이 코드값이라면 `--header-row` 로 읽은 뒤 `clean` 을 돌리지 말거나,
`peek` 로 먼저 확인하면 된다.

## keys — 단축키 찾기

같은 기능을 프로그램별로 나란히 놓고 비교한다. 터미널에서 `at keys` 만 치면
탭으로 묶음을 넘겨 보는 화면이 열리고, 검색어를 주면 표로 바로 나온다.

| 묶음 | 비교하는 프로그램 |
| --- | --- |
| `doc` 문서 | 한글 · Word · Google 문서 |
| `slide` 슬라이드 | PowerPoint · Google 슬라이드 |
| `calc` 스프레드시트 | Excel · Google 스프레드시트 |
| `os` 공통 | Windows · macOS |

```bash
at keys                          # 탭으로 넘겨 보는 화면
at keys 붙여넣기                 # 기능 이름으로
at keys "ctrl+shift+v"           # 키 조합으로 거꾸로 찾기
at keys -g calc -s abc           # 스프레드시트만, 가나다 순
at keys --html ~/단축키.html      # 브라우저용 한 장짜리 파일로
at keys --list                   # 묶음·출처 보기
at keys --edit                   # 내 단축키를 추가할 파일 틀 만들기
```

정렬은 네 가지다. `-s` 로 고르고, 화면에서는 `s` 로 돌려 가며 본다.

| 정렬 | 기준 |
| --- | --- |
| `freq` 자주 찾는 순 | 내가 찾아본 횟수 → 일반적인 사용 빈도 |
| `abc` 가나다 순 | 기능 이름 |
| `custom` 사용자 순 | 내가 `K`/`J` 로 직접 옮긴 순서 |
| `cat` 분류 순 | 파일 · 편집 · 서식 · 삽입 … |

화면 조작: `Tab`/`←→` 묶음 전환, `↑↓` 이동, `/` 검색, `Enter` 찾아본 것으로 기록,
`p` 맨 위에 고정, `K`/`J` 사용자 순서 변경, `s` 정렬 전환, `?` 도움말, `q` 종료.
기록은 `~/.attools/keys.json` 에 남고, `--html` 로 뽑은 파일은 브라우저 localStorage 에
따로 쌓인다.

**내 단축키 추가** — `at keys --edit` 로 `~/.attools/shortcuts.json` 틀을 만든 뒤
항목을 적으면 기본 데이터에 얹힌다. 이름이 같으면 내 값이 이기고, `apps` 와 `items` 를
함께 적으면 새 묶음(포토샵, IDE, 사내 시스템 같은 것)도 통째로 넣을 수 있다.

빈칸은 두 가지로 나눠 둔다. 이걸 구분해야 "아직 찾아봐야 할 것"이 보인다.

| 표시 | 뜻 | 데이터 값 |
| --- | --- | --- |
| `—` | 확인했고, 그 프로그램에 기본 단축키가 없는 기능 | `"없음"` |
| `?` | 아직 확인하지 못한 칸 | `null` |

```bash
at keys --gaps        # ? 로 남은 칸만 모아 보기
```

확인해서 채웠으면 `attools/data/shortcuts.json` 을 고치거나, 내 것만 쓸 거면
`~/.attools/shortcuts.json` 에 적으면 된다. 기본 단축키가 없는 기능이면 `"없음"` 이라고
적어 두면 `?` 에서 빠진다.

단축키는 제품 버전과 설정에 따라 다르다. 출처는 `at keys --list` 에 있다.

## life — 일상 계산

| 명령 | 하는 일 |
| --- | --- |
| `at life dday <날짜…>` | D-day, 만 나이, 다가올 100일·주년 기념일 |
| `at life split <이름=금액…>` | 더치페이 정산. 송금 횟수가 가장 적게 나오도록 짝지어 준다 |
| `at life loan <원금> <연이율> [년]` | 원리금균등·원금균등·만기일시 상환액과 총 이자, 상환표 |
| `at life workday <시작> [끝\|+N]` | 영업일 수 세기, N영업일 뒤 날짜, 공휴일 목록 |
| `at life unit <값+단위>` | 평↔㎡, 근·돈·관, 되·말, 마일·파운드·인치, 화씨↔섭씨 |

```bash
at life dday 2024-03-15 2027-01-01
at life split 홍길동=45000 김철수=12000 --extra 박민수
at life loan 3억5000만 4.2 30 --table 12
at life loan 2억 3.9 --months 240 --kind 원금균등 --grace 12
at life workday 2026-08-14 +5      # 5영업일 뒤
at life workday 2026-03-01 2026-03-31
at life workday --list 2026
at life unit 84㎡        # 25.41평
at life unit 100F        # 37.78℃
```

`workday` 는 양력 고정 공휴일과 대체공휴일을 계산한다(2026년이면 삼일절·광복절·개천절이
주말과 겹쳐 3월 2일, 8월 17일, 10월 5일이 대체공휴일로 잡힌다). 현충일·신정·성탄절은
대체공휴일 대상이 아니라 붙지 않는다.

**설날·추석·부처님오신날은 음력이라 계산하지 않는다.** 빠져 있으면 결과 아래에 항상
경고를 띄우고, `~/.attools/holidays.txt` 에 `2026-02-17 설날` 처럼 한 줄씩 적어 두면
반영한다. 조용히 틀린 날짜를 내놓는 것보다 낫다고 봤다.

금액은 `3억5000만`, `1.5억`, `350,000,000` 다 받는다. `100일` 은 한국식으로 시작일을
1일로 세어 계산한다(시작일 + 99일).

## novel — 소설 집필

| 명령 | 하는 일 |
| --- | --- |
| `at novel stats <파일/디렉터리…>` | 공백 포함·제외 글자수, 200자 원고지 매수, 문장·문단 수, 평균 문장 길이, 대사 비율, 읽는 시간, 단행본 환산 |
| `at novel check <파일>` | 상투 표현, 군더더기 부사, 반복 어구, 같은 종결 어미 연속, 같은 말로 시작하는 문장 연속, 너무 긴 문장 |
| `at novel outline <경로…>` | 장면 목록 — 분량, 대사 비율, 등장인물, 첫 문장 (`-o` 로 xlsx 저장) |
| `at novel style <경로…>` | 화별 문체 지표를 나란히 놓고 유난히 다른 화를 짚는다 |
| `at novel timeline <경로…>` | 시간 표현을 모아 보고, 한 장면 안에서 시간대·계절이 어긋난 곳을 짚는다 |
| `at novel find <찾을것> <경로…>` | 앞뒤 문장과 함께 찾고 처음·마지막 등장 위치를 알려준다 |
| `at novel names <경로…>` | 인물·지명 후보를 뽑아 표기 흔들림과 이름 뒤 조사 오류를 찾는다 |
| `at novel snap <디렉터리>` | 원고 전체를 스냅샷으로 복사하고 분량 변화를 기록한다. `-l` 로 목록 |

```bash
at novel stats 원고/ --each
at novel check 원고/12화.txt --run 3 --long 80
at novel outline 원고/ -o 장면목록.xlsx
at novel style 원고/               # 화별 비교
at novel style 원고/12화.txt --by scene
at novel timeline 원고/ --context
at novel find "붉은 열쇠" 원고/          # 복선이 언제 깔리고 언제 회수됐는지
at novel names 원고/ --min 3
at novel names 원고/12화.txt --name 리안 --name 세드릭   # 이름을 직접 지정
at novel snap 원고/ --note "3부 초고 완료"
at novel snap 원고/ -l
```

`at novel style` 은 문장 길이(평균·중앙·긴 문장 비율), 대사 비율, 문단 길이,
종결 어미 상위 3개가 차지하는 비중(어미 쏠림), 어휘 다양성을 화마다 재서 표로 놓는다.
표준편차 1.5배를 벗어난 화는 따로 짚어 준다 — "12화만 유난히 문장이 길다"를 눈이 아니라
숫자로 확인할 때 쓴다. 의도한 변주일 수 있으니 판단은 사람이 한다.

`at novel timeline` 은 날짜·시각·요일·상대 표현(이듬해, 사흘 뒤)·시간대·계절을 뽑아 순서대로
늘어놓고, **한 장면 안에서** 아침과 한밤중이 함께 나오는 것처럼 어긋난 곳을 표시한다.
회상이나 의도한 시간 경과일 수 있으므로 판단은 사람이 한다.

`at novel find` 는 문장 단위로 찾아 앞뒤 문장을 붙여 보여 주고, 몇 번째 파일·행·장면인지와
**처음·마지막 등장**을 알려 준다. 소품이나 복선이 깔린 자리와 회수된 자리를 짚을 때 쓴다.

`at novel outline` 은 마크다운 제목, `***`·`---` 같은 구분선, 빈 줄 세 개를 장면 경계로
본다. 장편에서 어느 장면이 늘어졌는지, 대사만 있는 장면이 어디인지, 누가 오래 안 나왔는지
한눈에 볼 때 쓴다.

`at novel names` 는 조사가 여러 종류 붙어 반복 등장하는 말을 고유명사로 본다.
표기 흔들림은 **드물게 나오는 쪽이 오타**라는 전제로, 확정된 이름과 편집 거리 1인
희귀 어간을 찾는다(리안 5회 vs 리언 1회). 조사 검사는 **아는 이름 뒤에서만** 한다 —
어간 경계를 모르면 "사과"를 "사"+"과"로 잘라 오탐이 쏟아지기 때문이다. 받침이 ㄹ이면
`로`가 맞다는 것(서울로)까지 본다.

집계 기준: 원고지는 공백 포함 200자, 읽는 속도는 분당 550자, 단행본은 공백 제외 10만자를
1권으로 잡는다. 출판사마다 다르므로 어림값이다. 기준은 `attools/manuscript.py` 상단 상수에서 바꾼다.
상투 표현·부사 목록도 같은 파일의 `CLICHES`, `FILLER_ADVERBS` 에서 고칠 수 있다.

## 테스트

```bash
python3 -m unittest discover -s tests
```

푸시할 때마다 GitHub Actions 가 Python 3.10 과 3.13 에서 테스트를 돌리고,
모든 그룹의 `--help`, 자기 저장소 시크릿 검사(`at git scan`), README 링크 검사
(`at doc links`)까지 확인한다. 도구로 도구를 검사하는 셈이다.
