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
| `at file recent [경로]` | 최근에 손댄 파일을 오늘·어제별로 |
| `at file tree [경로]` | 프로젝트 구조. `.gitignore` 를 그대로 따르고 줄 수·크기도 |
| `at file big [경로]` | 어디가 용량을 먹는지 디렉터리·파일 순위로 보여준다 |
| `at file hash [경로]` | 체크섬 만들기·검증. `sha256sum -c` 와 같은 형식 |
| `at file diff <왼쪽> <오른쪽>` | 두 디렉터리 비교 — 한쪽에만 있는 파일, 내용이 다른 파일 |
| `at file archive <디렉터리>` | 오래된 파일을 zip 으로 묶고, 검증에 성공하면 원본 정리 |
| `at file unzip <zip>` | 윈도우에서 만든 zip 의 깨진 한글 이름(cp949)을 되살려 푼다 |
| `at file image [경로]` | 이미지 크기·비율·용량 훑기 (png·jpg·gif·bmp·webp) |
| `at file route [경로] --rules <json>` | 내 규칙대로 폴더에 나눠 담는다 (이름 패턴 → 폴더) |
| `at file undo [저널]` | 직전 organize/fixname 을 되돌린다 |

```bash
at file organize ~/Downloads --by ext-date --min-age 7 -v   # 미리보기
at file organize ~/Downloads --by ext-date --min-age 7 --apply
at file fixname ~/Documents -r --apply
at file rename ~/사진 -g '*.JPG' --date --seq --sort date --apply
at file rename ~/문서 --prefix '기획팀_' --replace '최종(수정)=v2' --apply
at file rename ~/스캔 -t '{parent}_{seq:03d}{ext}' --apply
at file hash dist/ -o SHA256SUMS.txt
at file hash dist/ --check SHA256SUMS.txt      # 달라진 게 있으면 exit 1
at file diff 배포전/ 배포후/ -g '*.py'
at file archive ~/로그 --older 365 -g '*.log'            # 미리보기
at file archive ~/로그 --older 365 -g '*.log' --apply --remove
at file route --example > 규칙.json        # 예시부터 보고 고쳐 쓴다
at file route ~/받은자료 --rules 규칙.json          # 미리보기
at file route ~/받은자료 --rules 규칙.json --apply
at file image ~/블로그 --over 2000        # 긴 변이 2000px 넘는 것만
at file unzip 첨부파일.zip                # 미리보기 (고친 이름까지)
at file unzip 첨부파일.zip -o 받은자료/ --apply
at file dupes ~/Pictures --script > 삭제후보.sh
at file watch src -p '*.py' -- pytest -q
at file recent ~/문서 -d 3          # 사흘 안에 건드린 것
at file recent . --git             # 이 저장소에서 오늘 바꾼 것
at file tree -d 2 --lines --summary      # LLM 에 붙여넣기 좋은 구조 요약
at file big ~/Downloads --depth 2
at file undo
```

`tree` 는 `.gitignore` 를 직접 해석하지 않고 `git ls-files` 에게 묻는다. 부정 패턴이나 `**`
같은 규칙을 흉내 내다 어긋나는 것보다 정확하다. git 저장소가 아니면 숨김·빌드 디렉터리를
이름으로 거르고, 그렇게 했다는 사실을 함께 알린다.

`hash` 가 적는 형식은 `sha256sum` 과 같아서(`<해시><공백 두 칸><경로>`) 다른 도구로도
검증할 수 있다. `--check` 는 달라진 파일·없어진 파일을 따로 알려 주고 하나라도 어긋나면
종료 코드 1을 돌려준다.

`diff` 는 크기가 같아도 해시를 비교하므로 **크기가 같고 내용만 바뀐 파일**을 잡는다.
`--quick` 은 크기만 봐서 빠르지만 그런 변경은 놓치고, 결과에 그 사실을 함께 알려 준다.

`archive` 는 압축한 뒤 zip 을 다시 열어 **모든 파일이 같은 크기로 들어갔는지 확인한 다음에만**
원본을 지운다. 확인에 실패하면 원본을 그대로 두고 무엇이 문제인지 알려 준다. 이미 있는
zip 파일에는 덮어쓰지 않는다.

`route` 는 `organize` 가 못 하는 일을 한다. `organize` 는 확장자와 날짜로만 나누지만
`route` 는 "세금계산서*.pdf 는 회계/{연}/{달} 로" 처럼 **내 규칙**대로 옮긴다. 폴더 이름에는
`{년} {월} {일} {이름} {확장자} {분류}` 와 정규식의 이름 그룹을 넣을 수 있다. 먼저 걸리는
규칙이 이기고, **어느 규칙에도 안 걸린 파일은 건드리지 않고 따로 알려 준다** — 예상 못 한
파일이 '기타' 폴더로 쓸려 들어가는 것보다 낫다. 옮긴 뒤에는 `at file undo` 로 되돌린다.

`image` 는 파일 **헤더만** 읽어 크기를 알아낸다. 픽셀을 건드리지 않으므로 의존성 없이
빠르다. 대신 화질이나 회전(EXIF) 정보는 보지 않는다. 확장자가 이미지인데 헤더를 못 읽은
파일은 따로 모아 알려 준다 — 확장자만 바뀐 파일이나 깨진 파일이다.

`unzip` 은 윈도우에서 만든 zip 을 푼다. 표준 zip 에는 파일명 인코딩을 적는 칸이 없어서
UTF-8 표시가 없으면 대부분의 도구가 cp437 로 읽고, 그래서 한글이 `║╕░φ╝¡` 처럼 깨진다.
이름 바이트를 되돌려 cp949 로 다시 읽고, 이미 UTF-8 표시가 있는 항목은 건드리지 않는다.
`../` 나 절대 경로처럼 **압축 바깥을 가리키는 항목은 풀지 않고** 이유와 함께 알린다.
이미 있는 파일도 덮어쓰지 않는다(`--overwrite`).

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
| `at dev deps [경로]` | 의존성 파일 훑기 — 개수, 버전 고정 여부, 파일 사이 충돌 |
| `at dev ports [이름\|번호]` | 지금 열려 있는 포트 전부 (프로세스·PID와 함께) |
| `at dev bench -- <명령>` | 명령을 여러 번 돌려 실행 시간을 재고 두 방식을 비교 |
| `at dev log <파일…>` | 레벨 집계, 시간대 분포, 급증 구간, 반복되는 에러 묶기 |
| `at dev slow <파일…>` | 로그의 응답 시간 - 경로별 p50/p95/최대와 가장 느린 요청 |
| `at dev retry -- <명령>` | 성공할 때까지 다시 돌린다. 기다리는 시간을 배로 늘린다 |
| `at dev db <파일>` | sqlite 파일 훑기 - 표 목록, 열 구성, 조회 (읽기 전용) |
| `at dev api <openapi.json>` | API 문서 훑기 - 엔드포인트·인자·응답, 빠진 문서 찾기 |
| `at dev mask [파일]` | 로그를 공유하기 전에 주민등록번호·전화·카드·이메일·토큰·비밀번호를 가린다 |
| `at dev wait <대상>` | `host:port` 나 URL 이 응답할 때까지 기다린다. 컨테이너 띄운 뒤 헬스체크용 |
| `at dev cron <표현식>` | cron 표현식을 한국어로 풀어 주고 다음 실행 시각을 KST로 보여준다 |
| `at dev gen [종류]` | 비밀번호·토큰·hex·UUID·PIN 을 CSPRNG 로 만든다 |
| `at dev enc <값>` | base64/base64url/hex/URL 인코딩과 해시를 한 번에, 디코딩도 자동 시도 |

```bash
at dev env                       # 배포 전 .env 점검, 문제 있으면 exit 1
at dev env --sync                # .env 에서 .env.example 을 만든다 (미리보기)
at dev env --sync --apply
at dev deps --loose              # 버전이 고정되지 않은 것만
at dev deps -l                   # 목록까지
at dev ports                     # 지금 뭐가 떠 있나
at dev ports node                # 이름으로 거르기
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
at dev slow app.log --over 500          # 500ms 넘는 요청 비율까지
at dev slow app.log --sort total        # 총 소요 시간이 큰 경로부터
at dev slow app.log --pattern 'took=(\d+)'
at dev api openapi.json                                # 엔드포인트 한눈에
at dev api openapi.json --find orders --detail         # 인자와 본문까지
at dev api openapi.json --holes                        # 요약·오류 응답이 빠진 것
at dev db app.sqlite                                   # 표·뷰 목록과 행 수
at dev db app.sqlite --table users                     # 열 구성과 앞 몇 행
at dev db app.sqlite -q 'select 부서, count(*) from 사원 group by 부서' -o 집계.xlsx
at dev retry -n 5 -- curl -sf http://localhost:8080/health
at dev retry --delay 5 --backoff 1 -- ./deploy.sh      # 5초 간격으로 그대로
```

`at dev deps` 는 `pyproject.toml`, `package.json`, `go.mod`, `requirements*.txt` 를 읽는다.
같은 패키지가 파일마다 다른 조건으로 적혀 있으면 따로 알려 주고 종료 코드 1을 돌려주므로
CI 에 넣을 수 있다. `requirements.txt` 의 `-r` 은 따라가지 않고 그런 줄이 있다는 것만 알린다.

`at dev bench` 는 첫 실행(캐시가 비어 느린 회차)을 예열로 빼고 잰다. 두 명령을 비교할 때
중앙값 차이가 편차보다 작으면 "차이가 뚜렷하지 않다"고 알려 준다 — 측정 잡음을 개선으로
착각하지 않기 위해서다.

`at dev log` 는 숫자·UUID·IP·경로·따옴표 문자열을 `<n>`, `<uuid>` 같은 자리표시자로 바꿔서
같은 사고끼리 묶는다. `결제 실패 order=8821` 과 `order=8822` 가 한 줄로 합쳐지므로
"무엇이 몇 번 터졌는지"가 바로 보인다. 스택 트레이스 줄은 앞 항목에 붙이고,
평소 건수의 3배 이상 튄 구간은 급증으로 따로 알려 준다.

`at dev slow` 는 `34ms`, `1.2s` 처럼 **단위가 붙은 값만** 응답 시간으로 센다. 상태 코드나
바이트 수를 시간으로 잘못 세는 것보다 못 세는 편이 낫다고 봤다. 형식이 다르면 `--pattern`
으로 알려 준다. `GET /api/users/12` 는 `GET /api/users/{n}` 으로 묶어 경로별로 집계하고,
경로를 못 찾은 줄도 버리지 않고 `(경로 없음)` 으로 함께 센다. 시간을 읽은 줄이 절반이 안
되면 그 사실을 알려 준다 — 통계가 일부만 보고 나온 값일 수 있어서다.

백분위는 보간하지 않고 실제 값 중에서 고른다. 값이 몇 개 없을 때 보간하면 로그에 없는
숫자를 지어내게 된다.

`at dev api` 는 **json 만** 읽는다. 표준 라이브러리에 yaml 파서가 없어서인데, 그 사실을
숨기지 않고 말한다. 문서 안의 `$ref` 는 따라가고 외부 파일 참조는 따라가지 않는다.
`--holes` 는 요약이 없거나 4xx·5xx 응답을 안 적은 엔드포인트를 모은다 — 성공 응답만 적힌
문서가 흔한데, 그 문서를 보고 만든 클라이언트는 오류를 처리하지 않는다.

`at dev db` 는 **읽기 전용**으로 연다. 훑어보다가 원본을 고치는 일이 없어야 해서다. 값을
바꾸는 문장은 돌리기 전에 막고 그 이유를 말한다. 파일이 sqlite 인지는 확장자가 아니라
헤더로 판단하고, 조회 결과는 `-o` 로 csv·xlsx 에 그대로 저장한다. 결과가 잘리면 잘렸다고
알려 준다 — 앞 20행만 보고 전부라고 믿으면 안 된다.

`at dev retry` 는 마지막 시도의 종료 코드를 그대로 돌려주므로 스크립트에서 그대로 판단할
수 있다. 몇 번째에 성공했는지, 얼마나 기다렸는지를 함께 찍는다 — "가끔 되는" 것과 "한 번에
되는" 것은 다른 문제라서다.

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
| `at text extract <정규식> <파일…>` | 정규식으로 뽑아 표로 만든다 (로그 → csv) |
| `at text lines <파일>` | 줄 단위 정리·대조 — 중복 제거, 정렬, 빈도, 두 파일 비교 |
| `at text diff <이전> <이후>` | 두 글을 줄·문장·문단 단위로 대조 (고친 낱말까지 표시) |
| `at text typo <경로…>` | 흔한 한글 표기 오류를 찾는다 (몇일→며칠, 갈께→갈게) |
| `at text undo [저널]` | 직전 작업 되돌리기 |

```bash
at text replace old.example.com api.example.com src/          # 미리보기 (차이까지)
at text replace old.example.com api.example.com src/ --apply
at text replace -e '(\d+)\.(\d+)\.(\d+)' 'v\1.\2' -g '*.md' --apply
at text encoding 인수인계자료/ --apply     # 예전 파일 무더기 utf-8 로
at text trim . -g '*.py' --apply
at text extract '(?P<시각>\S+ \S+) (?P<레벨>\w+) (?P<메시지>.+)' app.log -o 로그.csv
at text lines 명단.txt --unique -o 정리본.txt
at text lines 작년명단.txt --compare 올해명단.txt      # 빠진 사람·새로 온 사람
at text lines 로그.txt --count 10                      # 많이 나온 줄 상위 10개
at text diff 계약서_1차.md 계약서_2차.md               # 줄 단위, 바뀐 낱말만 강조
at text diff 원고_초고.md 원고_퇴고.md --unit 문장 --full
at text typo 원고/ -g '*.md'                           # 찾기만 (exit 1)
at text typo 안내문.md --apply                         # 고치고 백업
at text undo
```

기본은 미리보기다. 바뀌는 줄을 diff 로 먼저 보여 주고, `--apply` 를 붙여야 실제로 쓴다.
원본은 `~/.attools/text/<시각>/` 에 통째로 백업하므로 `at text undo` 로 되돌릴 수 있다.

`extract` 는 이름 붙인 그룹 `(?P<이름>…)` 을 열 이름으로 쓴다. 몇 줄이 맞았고 몇 줄이
안 맞았는지, 안 맞은 줄의 예까지 보여 주므로 정규식을 고쳐 가며 맞출 수 있다. 뽑은 표는
`-o` 로 저장해 그대로 `at sheet pivot` 이나 `at sheet report` 에 넘길 수 있다.

`lines` 는 명단·목록을 맞춰볼 때 쓴다. `--compare` 는 공통·왼쪽만·오른쪽만으로 갈라
보여 주고, `-o` 와 `--pick` 을 함께 주면 그중 하나를 파일로 저장한다. 인코딩은
`text` 의 다른 명령과 같은 규칙으로 알아서 읽는다.

`diff` 는 고친 자리를 `[-지운말-] {+넣은말+}` 으로 보여 준다. 문장이 반쯤 닮았을 때만
한 곳을 '수정' 으로 묶고, 그만큼 닮지 않았으면 삭제와 추가로 따로 센다(`--similar`).
전혀 다른 두 문장을 한 번 고친 것처럼 보여주면 지워진 내용을 놓치기 때문이다. 자리만
옮긴 문단도 추가와 삭제로 센다. 다른 곳이 있으면 종료 코드 1 이다.

`typo` 는 **맞춤법 검사기가 아니다.** 문맥을 봐야 하는 것(되/돼 전반, 낳다/낫다,
들리다/들르다, 바램)은 넣지 않고 어떤 문맥에서도 틀린 표기만 규칙으로 둔다. `찌게`(살이
찌게), `일부로`(일부로 나뉘다)처럼 다른 뜻으로 쓰일 수 있는 말은 아예 빼거나 `김치찌게`
처럼 앞말을 붙여 좁혔다. `갈께`는 ㄹ 받침 뒤의 `께`만 보므로 `선생님께`는 건드리지 않는다.
걸린 게 있으면 종료 코드 1이라 CI 에 넣을 수 있고, `--apply` 로 고친 파일은 백업이 남는다.

정규식이 아니면 `.` 이나 `\` 도 문자 그대로 다룬다. BOM 이 있던 파일은 BOM 을 유지하고,
없던 파일에 BOM 을 붙이지 않는다. 이진 파일과 `node_modules`, `.git` 같은 디렉터리는
건너뛴다.

## json — API 응답 훑기와 비교

| 명령 | 하는 일 |
| --- | --- |
| `at json show [파일]` | 한글이 깨지지 않게 예쁘게 출력 (`--sort`, `--compact`) |
| `at json schema [파일]` | 키 경로·타입·가끔 없는 키·예시 값 요약 |
| `at json diff <이전> <이후>` | 사라진 키, 타입 바뀜, 새 키, 값 바뀜을 경로 단위로 |
| `at json get <파일> <경로>` | `users[0].name` 처럼 경로로 값 하나 꺼내기 |
| `at json set <파일> <경로=값>` | 설정 파일의 값 바꾸기. 되돌릴 수 있다 |
| `at json flat [파일]` | `경로<탭>값` 한 줄씩 출력해서 grep 하기 좋게 |
| `at json merge <파일…>` | 설정 JSON 을 겹친다. 무엇을 덮어썼는지 함께 보여 준다 |

```bash
curl -s ... | at json schema -
at json diff 어제응답.json 오늘응답.json --key id
at json diff v1.json v2.json --breaking      # 깨질 변화만, 있으면 exit 1
at json get package.json version --raw
at json set package.json 'version="2.0.0"' --apply
at json set 설정.json config.port=9090 --apply
at json merge 기본설정.json 운영설정.json -o 배포설정.json
at json merge 기본.json 지역.json --list append
at json flat 응답.json --grep 'error|실패'
```

`--key id` 를 주면 객체 배열을 그 필드 값으로 짝지어 비교한다. 순서만 바뀐 응답이
전부 바뀐 것처럼 보이는 일을 막는다. `--breaking` 은 **사라진 키와 타입 변경**만 보고
하나라도 있으면 종료 코드 1을 돌려주므로 계약 회귀 검사로 CI 에 넣을 수 있다.

`set` 의 값은 JSON 으로 먼저 읽는다. `8080` 은 숫자, `true` 는 참, `"글자"` 는 문자열이 되고
읽히지 않으면 문자열 그대로 쓴다. 무조건 문자열로 넣으려면 `--string` 을 준다. 기본은
미리보기이고 `--apply` 로 쓰면 원본을 백업해 `at text undo` 로 되돌릴 수 있다.
파일 전체를 다시 쓰므로 들여쓰기와 키 순서가 통일된다는 점은 감안해야 한다.

`merge` 는 뒤에 오는 파일이 이긴다(기본설정 → 운영설정). 객체는 키 단위로 깊게 겹치고
배열은 통째로 바꾼다(`--list append` 로 이어붙일 수 있다). **무엇을 덮어썼는지 경로와 값을
함께 보여 준다** — 설정이 조용히 바뀐 채로 배포되는 것을 막으려는 것이다. 같은 값이면
덮어썼다고 보고하지 않는다.

파일이 JSON 으로 안 읽히면 JSON Lines 로 한 번 더 시도한다.

## doc — 마크다운 유지보수

| 명령 | 하는 일 |
| --- | --- |
| `at doc toc <경로…>` | 제목에서 목차를 만들어 `<!-- toc -->` 사이를 갈아 끼운다 |
| `at doc links <경로…>` | 깨진 상대 경로 링크와 없는 앵커(`#제목`)를 찾는다 |
| `at doc check <경로…>` | 제목 단계 건너뜀(H2 → H4), 같은 제목 반복, H1 중복 |
| `at doc split <파일>` | 긴 문서를 제목 단위 파일로 쪼갠다 (번호를 앞에 붙여 순서 유지) |
| `at doc table <경로…>` | 마크다운 표의 칸 너비를 맞춘다. 한글을 두 칸으로 센다 |

```bash
at doc toc README.md              # 미리보기
at doc toc docs/ --apply --depth 2
at doc links docs/                # 깨진 게 있으면 exit 1
at doc check README.md --outline
at doc split 기획서.md -o 기획서/          # 미리보기
at doc split 기획서.md -o 기획서/ --apply  # H2 마다 01-…md, 02-…md
at doc table README.md                     # 미리보기 (차이까지)
at doc table docs/ --apply
```

앵커는 GitHub 규칙과 같게 만든다 — 소문자로 바꾸고 구두점을 떼고 공백을 `-` 로,
같은 제목이 또 나오면 `-1` 을 붙인다. 한글은 그대로 남는다. 코드 블록 안의 `#` 는
제목으로 세지 않는다. 외부 URL 은 확인하지 않는다(네트워크를 쓰지 않는다).

`table` 은 한글·한자·전각 문자를 두 칸으로 세서 칸을 맞춘다. 대부분의 포매터가 글자 수로
세기 때문에 한글 표는 소스에서 어긋나 보인다. 정렬 표시(`:---`, `:-:`, `---:`)는 그대로
두고, `\|` 로 escape 한 막대는 칸 구분으로 보지 않는다. 코드 블록 안의 표는 건드리지
않는다. 고친 파일은 `~/.attools/text/<시각>/` 에 백업하므로 `at text undo` 로 되돌린다.

`split` 은 원본을 건드리지 않고 새 파일만 만든다. 쓰려는 자리에 같은 이름이 하나라도
있으면 아무것도 쓰지 않고 멈춘다 — 덮어쓴 것을 되돌릴 방법이 없기 때문이다.
첫 제목 앞의 글은 `00-머리말.md` 로 따로 남는다(`--drop-preface` 로 버릴 수 있다).

이 README 의 목차도 `at doc toc README.md --apply` 로 만든 것이다.

## git — 저장소 정리와 검사

| 명령 | 하는 일 |
| --- | --- |
| `at git sweep [경로]` | 기준 브랜치에 병합이 끝난 로컬 브랜치, 원격이 사라진 추적 브랜치를 찾아 지운다 |
| `at git scan [경로]` | 코드에 하드코딩된 API 키·토큰·개인 키·접속 문자열 비밀번호·주민등록번호를 찾는다 |
| `at git branches [경로]` | 브랜치별 마지막 커밋·사람·원격 차이. `--stale 30` 으로 방치된 것만 |
| `at git release [경로]` | 태그 이후 커밋으로 변경 로그 초안을 만든다 |
| `at git stats [경로]` | 커밋 통계, 사람별 기여, **자주 바뀌는 파일**, 기간·요일 분포 |
| `at git todo [경로]` | 코드의 TODO·FIXME·HACK·XXX·BUG 를 모아 담당자와 방치된 기간까지 보여준다 |
| `at git conflicts [경로]` | 충돌 표시가 남은 자리를 찾는다. 어느 쪽이 몇 줄인지까지 |

```bash
at git sweep --fetch              # 미리보기
at git sweep --fetch --apply
at git scan                       # 추적 중인 파일 전체
at git scan --staged --quiet      # 커밋 직전 검사, 발견되면 exit 1
at git scan --install-hook "$HOME/.local/bin/at"   # pre-commit 훅으로 설치
at git conflicts                  # 병합 중이면 충돌 파일만, 아니면 전체
at git todo                       # 오래 방치된 순
at git todo -m FIXME -m BUG -s severity
at git todo --no-blame -g '*.py'  # 작성자 조회 없이 빠르게
at git branches --stale 30
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

`at git` 명령은 모두 `git ls-files` 로 대상을 고르므로 `.gitignore` 를 그대로 따른다.
아직 `git add` 하지 않은 저장소에서는 "추적하는 파일이 없다"고 분명히 알린다 —
검사할 게 없는 것과 문제가 없는 것은 다르기 때문이다. `--all` 을 붙이면 추적 안 되는
파일까지 본다.

`at git conflicts` 는 병합 중이면 충돌난 파일만, 아니면 추적 파일 전부에서 `<<<<<<<`
표시를 찾는다. 자리마다 우리 쪽과 저쪽이 각각 몇 줄인지 보여 주고, **한쪽이 비어 있으면**
따로 짚는다 — 그건 "고친 내용"이 아니라 "지웠는가 남겼는가"의 문제라 판단이 다르다.
끝 표시(`>>>>>>>`)가 없는 것은 세지 않는다(문서 안의 예시일 수 있다). 어느 쪽을 남길지는
사람이 정한다. 남은 표시가 있으면 종료 코드 1이다.

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
| `at sheet melt <파일> --keep <열>` | 1월~12월처럼 옆으로 늘어선 열을 항목/값 두 열로 눕힌다 |
| `at sheet transpose <파일>` | 행과 열을 바꾼다. 첫 열의 값이 새 머리글이 된다 |
| `at sheet expand <파일> --col <열>` | 한 열을 구분자로 갈라 여러 열로 (엑셀 '텍스트 나누기') |
| `at sheet combine <파일> --cols <열,열>` | 여러 열을 한 열로 합친다 (expand 의 반대) |
| `at sheet cut <파일> -c <열>` | 열 고르기·순서 바꾸기 (`--drop` 이면 빼기) |
| `at sheet where <파일> --eq <열=값>` | 조건에 맞는 행만. `--gte`, `--lt`, `--has` 등 |
| `at sheet sort <파일> --by <열>` | 정렬. 빈 칸은 항상 뒤로 |
| `at sheet sample <파일> -n 100` | 표본 뽑기 (`--seed` 로 같은 표본 재현) |
| `at sheet split <파일> --by <열>` | 부서별·월별로 파일 쪼개기. `--rows 1000` 이면 행 수로 |
| `at sheet from-json <파일>` | JSON 배열을 표로 (API 응답 → 엑셀) |
| `at sheet to-json <파일>` | 표를 JSON 배열로 (엑셀 → API) |
| `at sheet validate <파일>` | 규칙으로 검증 — 필수·중복·타입·정규식·범위·목록 |
| `at sheet fx <파일> --add <새열=수식>` | 수식으로 계산한 열 붙이기 (엑셀 수식 대신) |
| `at sheet dedupe <파일> -k <열>` | 키가 같은 행 중 하나만 남긴다 (최신 것만 등) |
| `at sheet join <왼쪽> <오른쪽> --on <열>` | 두 표를 키로 합친다 (VLOOKUP 대신) |
| `at sheet report <파일>` | 요약·그래프·표를 담은 HTML 보고서 |
| `at sheet fill <명단> -t <틀>` | 행마다 틀을 채워 개인별 문서를 만든다 (메일 머지) |
| `at sheet convert <파일> -o <출력>` | csv ↔ xlsx 변환, 깨진 인코딩 정리 |

```bash
at sheet peek 매출.xlsx --sheet 1분기 -n 10
at sheet check 직원명부.xlsx --key 사번 --required 입사일
at sheet clean 원본.csv --dedupe -o 정리본.xlsx
at sheet merge 2026-*.csv -o 통합.xlsx
at sheet diff 지난달.xlsx 이번달.xlsx --key 사번
at sheet pivot 매출.xlsx --rows 부서 --cols 분기 --values 금액 --agg sum
at sheet melt 월별매출.xlsx --keep 부서 --keep 이름 --name 월 --value 매출 -o 긴표.csv
at sheet transpose 요약.csv
at sheet expand 거래처.xlsx --col 주소 --sep ' ' --names 시,구,동 -o 정리본.xlsx
at sheet combine 거래처.xlsx --cols 시,구,동 --into 주소 -o 합본.xlsx
at sheet convert 깨진파일.csv -o 정상.xlsx
at sheet cut 직원.xlsx -c 사번 -c 이름 -c 연봉 -o 요약.xlsx
at sheet where 직원.xlsx --eq 부서=개발 --gte 연봉=6000만 -o 대상.csv
at sheet sort 매출.xlsx --by 금액 --desc -o 정렬본.xlsx
at sheet split 전체.xlsx --by 부서 -o 부서별/ --apply
at sheet split 큰파일.csv --rows 5000 --apply     # 메일 첨부 크기로 쪼갤 때
curl -s https://api.example.com/users | at sheet from-json - -o 사용자.xlsx
at sheet from-json 응답.json --path data.users -o 표.csv
at sheet to-json 명단.xlsx --nest -o 요청.json
at sheet to-json 명단.xlsx --lines --compact | while read r; do curl -d "$r" ...; done
at sheet validate 거래처.csv --format 사업자등록번호=사업자번호 --format 연락처=휴대폰
at sheet validate 납품.csv --required 이름 --unique 사번 \
    --match '사번=^E\d{3}$' --range '연봉=0:' --oneof 부서=영업,개발,인사
at sheet validate 납품.csv --rules 규칙.json      # 규칙을 파일로 두고 CI 에서
at sheet fx 급여.csv --add '월급=연봉/12' --add '실수령=월급*0.88' --round 0 -o 계산본.xlsx
at sheet dedupe 명부.csv -k 사번 --keep max --by 수정일 -o 최신.csv
at sheet join 직원.xlsx 급여.csv --on 사번 -o 통합.xlsx
at sheet join 주문.csv 고객.csv --on 고객번호 --how inner -o 매칭본.csv
at sheet report 주문.csv --by 지역 --value 금액 --date 주문일 -o 보고서.html
at sheet fill 명단.csv -t 안내문틀.md -o 안내문/ --name '{사번}_{이름}.md' --apply
# 틀 안에서: {이름:님/님} 대신 {이름:은/는}, {도시:으로/로} 처럼 받침에 맞는 조사
at sheet fill 명단.csv -t 틀.txt --single -o 합본.txt      # 한 파일로 이어 붙이기
```

`melt` 는 피벗의 반대다. `1월 2월 3월`처럼 옆으로 늘어선 열을 `항목/값` 두 열로 눕혀서
피벗테이블이나 `at sheet pivot` 에 그대로 넣을 수 있는 모양으로 만든다. 빈 칸은 행으로
만들지 않는다 — 안 판 달과 0원 판 달이 섞이면 평균이 조용히 달라진다(`--keep-blank`).

`expand` 는 조각 수가 행마다 다를 수 있다는 것을 전제로 한다. 열 개수는 **가장 많이
갈라진 행**에 맞추고 모자란 자리는 빈칸으로 둔다 — 잘라내면 값이 조용히 사라진다. 행마다
조각 수가 다르면 그 분포를 알려 주므로 주소처럼 들쭉날쭉한 자료를 눈으로 확인할 수 있다.

`combine` 은 그 반대다. 빈 칸은 건너뛰므로 `서울시  역삼동`처럼 구분자가 겹치지 않는다
(`--keep-blank` 로 자리를 남길 수 있고, 그래야 `expand` 로 정확히 되돌아간다).

`transpose` 는 첫 열의 값을 새 머리글로 삼아 행과 열을 바꾼다. 같은 값이 겹치면 뒤에
번호를 붙여 열 이름이 사라지지 않게 한다.

`to-json` 은 그 반대다. `--nest` 를 주면 `meta.부서` 열을 다시 중첩 객체로 되돌리므로
`from-json` → 엑셀에서 손질 → `to-json --nest --parse-json` 하면 원래 구조가 그대로
돌아온다. 빈 칸은 키 자체를 넣지 않는다 — API 에 `null` 을 보내는 것과 키를 안 보내는 것은
다르게 처리되는 일이 많아서다(`--keep-blank` 로 바꿀 수 있다).

`from-json` 은 객체 배열을 표로 편다. 열은 모든 원소의 키 합집합이라 어떤 원소에만 있는
키도 빠지지 않고, 없는 값은 빈 칸이 된다. 중첩된 객체는 `meta.부서` 처럼 펴고, 정한 깊이를
넘거나 배열이면 JSON 글자로 남긴다. `--path` 를 생략하면 가장 큰 객체 배열을 알아서 찾는다.

`--format` 은 국내에서 자주 쓰는 형식을 본다 — `사업자번호`(국세청 검증번호 계산),
`휴대폰`, `전화번호`, `우편번호`(5자리), `이메일`. 사업자번호는 **규칙에 맞는 번호인지만**
확인한다. 실제로 등록된 사업자인지는 알 수 없다 — 오타를 잡는 용도다.

`validate` 는 규칙을 어긴 행 번호와 값 예시를 보여 주고, 하나라도 어기면 종료 코드 1을
돌려주므로 데이터를 받거나 넘기기 전 검사로 CI 에 넣을 수 있다. 규칙은 `--rules 규칙.json`
으로 파일에 두고 재사용한다. 빈 칸은 `--required` 로만 잡는다 — 규칙마다 다시 잡으면
같은 행이 여러 번 나와 정작 볼 것을 못 본다.

`fx` 의 수식은 파이썬 문법이지만 **쓸 수 있는 문법만 열어 뒀다**. 사칙연산, 비교, `and/or`,
`A if 조건 else B`, 그리고 `abs round min max int float len str` 만 된다. `__import__` 나
`open` 같은 것은 파싱 단계에서 막힌다 — 표 하나로 아무 코드나 돌게 두면 안 되기 때문이다.
열 이름에 공백이 있으면 `{매출 합계}` 처럼 감싼다. 빈 칸이나 0으로 나누는 행은 그 행만
비우고 **왜 비었는지, 몇 행인지** 알려 준다.

`dedupe` 는 `clean --dedupe` 와 다르다. `clean` 은 완전히 똑같은 행만 지우고, `dedupe` 는
**키가 같으면 나머지가 달라도** 하나만 남긴다. 사번이 같은 여러 행에서 수정일이 가장
최근인 것만 남기는 쪽이 실무에서 필요한 정리다.

`join` 은 VLOOKUP 이 조용히 틀리는 자리를 짚어 준다. 오른쪽 키가 겹치면 VLOOKUP 은
첫 짝만 가져와 합계가 어긋나는데, `join` 은 짝마다 행을 만들고 **몇 행이 늘었는지, 어떤
키가 겹쳤는지** 알려 준다. 짝을 못 찾은 행 수, 이름이 겹쳐 바꾼 열도 함께 보고한다.

`report` 는 KPI 타일, 그룹별 가로 막대, 기간별 추이, 열 요약, 데이터 표를 한 장으로 묶는다.
그래프는 의존성 없이 SVG 를 직접 그리고, 계열이 하나뿐이라 색은 파란색 한 가지만 쓴다.
그래프마다 값을 직접 붙이고 "값을 표로 보기"를 함께 넣어, 색을 못 보거나 인쇄한 경우에도
읽을 수 있게 했다. 밝은/어두운 모드 각각의 색을 따로 정해 두었다.

`fill` 은 틀 안의 `{열이름}` 을 행 값으로 바꾼다. `{번호:03d}` 처럼 형식도 쓸 수 있고
`{{` 와 `}}` 는 중괄호 자체를 뜻한다. 표에 없는 자리표시자가 있으면 **먼저 알려 주고 멈춘다** —
오타 하나로 수백 개 파일에 빈칸이 들어가는 걸 막기 위해서다(`--force` 로 강행 가능).

`{이름:을/를}` 처럼 조사 짝을 적으면 **받침에 맞는 조사**를 붙인다. `민수를`·`지현을`,
`서울로`·`부산으로`(ㄹ 받침), `2를`·`3을`(숫자는 읽는 소리로)까지 맞춘다. "홍길동님이(가)"
같은 괄호 표기를 안 써도 된다. 한글 한두 글자 `/` 한글 한두 글자 꼴만 조사로 보므로
`{번호:03d}` 같은 형식 지정과 섞이지 않는다.

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
at keys --gaps                   # 아직 확인 못 한 칸만 모아 보기
at keys --set 'doc/표 만들기/word=Alt+N,T'
at keys --set 'doc/편집 용지/gdocs=없음'
at keys --fill                   # 확인 못 한 칸을 하나씩 물어 채운다
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

확인해서 채우려면 `at keys --set '그룹/기능/앱=값'` 을 쓴다. 값에 `없음` 을 주면 그 앱에
기본 단축키가 없다는 뜻으로 기록되어 `?` 에서 빠진다. `--fill` 은 남은 칸을 하나씩
물어 가며 채운다. 어느 쪽이든 `~/.attools/shortcuts.json` 에만 쓰고 기본 데이터는
건드리지 않으므로, 도구를 갱신해도 내가 채운 것이 남는다.

단축키는 제품 버전과 설정에 따라 다르다. 출처는 `at keys --list` 에 있다.

## life — 일상 계산

| 명령 | 하는 일 |
| --- | --- |
| `at life dday <날짜…>` | D-day, 만 나이, 다가올 100일·주년 기념일 |
| `at life split <이름=금액…>` | 더치페이 정산. 송금 횟수가 가장 적게 나오도록 짝지어 준다 |
| `at life loan <원금> <연이율> [년]` | 원리금균등·원금균등·만기일시 상환액과 총 이자, 상환표 |
| `at life workday <시작> [끝\|+N]` | 영업일 수 세기, N영업일 뒤 날짜, 공휴일 목록 |
| `at life unit <값+단위>` | 평↔㎡, 근·돈·관, 되·말, 마일·파운드·인치, 화씨↔섭씨 |
| `at life cal [연-월]` | 달력. 공휴일과 그 달 영업일 수를 함께 본다 |
| `at life tz [시각]` | 시차. 여러 도시의 같은 시각과 겹치는 근무 시간 |
| `at life tax <금액>` | 부가세 더하기·빼기와 원천징수 실수령액 |
| `at life save --monthly\|--deposit` | 적금·예금 만기 수령액과 세후 수익률 |

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
at life tz                             # 지금, 주요 도시
at life tz "2026-09-05 14:00" --to 뉴욕 --to 런던
at life tz --overlap 샌프란시스코       # 겹치는 근무 시간
at life cal                            # 이번 달
at life cal 2026-10 -n 3               # 10~12월
at life tax 1100000                    # 공급가로 볼 때와 합계로 볼 때 둘 다
at life tax 300만 --withhold-rate 8    # 기타소득 8.8%
at life save --monthly 50만 --months 24 --rate 3.5
at life save --deposit 1000만 --months 12 --rate 3.5
```

`workday` 는 양력 고정 공휴일과 대체공휴일을 계산한다(2026년이면 삼일절·광복절·개천절이
주말과 겹쳐 3월 2일, 8월 17일, 10월 5일이 대체공휴일로 잡힌다). 현충일·신정·성탄절은
대체공휴일 대상이 아니라 붙지 않는다.

`tz` 는 파이썬이 들고 있는 IANA 시간대 자료를 그대로 쓰므로 서머타임도 그때그때 반영된다.
`--overlap` 은 양쪽 근무 시간(09~18시, 주중)이 겹치는 때를 찾고, 하나도 없으면 상대 근무
시간이 내 몇 시인지 알려 준다 — 자정을 넘는 구간은 `22시~06시`처럼 이어서 보여 준다.

`cal` 은 그 달 영업일 수와 공휴일을 함께 보여 준다(`*` 공휴일, `.` 오늘). `workday` 와
같은 공휴일 표를 쓰므로 음력 명절에 대한 한계도 같다.

**설날·추석·부처님오신날은 음력이라 계산하지 않는다.** 빠져 있으면 결과 아래에 항상
경고를 띄우고, `~/.attools/holidays.txt` 에 `2026-02-17 설날` 처럼 한 줄씩 적어 두면
반영한다. 조용히 틀린 날짜를 내놓는 것보다 낫다고 봤다.

`tax` 는 준 금액이 공급가액일 때와 부가세가 포함된 합계일 때를 함께 보여 준다 — 어느
쪽인지 물어보지 않고 하나만 고르면 절반은 틀린 답이 된다. 공급가액을 먼저 내림하고
부가세를 차액으로 두므로 둘의 합이 원래 금액과 어긋나지 않는다. 원천징수는 3.3%를 한 번에
곱하지 않고 소득세를 뗀 뒤 그 10%를 지방소득세로 떼는 실제 순서대로 계산한다(1~2원 다르다).

`save` 는 은행 표시 금리와 같은 **단리** 기준이다. 적금은 먼저 넣은 돈만 오래 이자가
붙으므로 같은 금리의 예금보다 실제 수익률이 절반쯤이고, 그 값을 '원금 대비 세후 수익률'로
따로 낸다. 월복리 상품이나 중도해지 이율은 계산하지 않는다.

금액은 `3억5000만`, `1.5억`, `350,000,000` 다 받는다. `100일` 은 한국식으로 시작일을
1일로 세어 계산한다(시작일 + 99일).

## novel — 소설 집필

| 명령 | 하는 일 |
| --- | --- |
| `at novel stats <파일/디렉터리…>` | 공백 포함·제외 글자수, 200자 원고지 매수, 문장·문단 수, 평균 문장 길이, 대사 비율, 읽는 시간, 단행본 환산 |
| `at novel check <파일>` | 상투 표현, 군더더기 부사, 반복 어구, 같은 종결 어미 연속, 같은 말로 시작하는 문장 연속, 너무 긴 문장 |
| `at novel outline <경로…>` | 장면 목록 — 분량, 대사 비율, 등장인물, 첫 문장 (`-o` 로 xlsx 저장) |
| `at novel wordlist <경로…>` | 어휘 목록 — 빈도, 처음 나온 화, 그 화에서만 쓰인 말 |
| `at novel dialogue <경로…>` | 인물별 대사량과 말투 — 존댓말 비율, 자주 쓰는 어미 |
| `at novel export <경로…>` | 여러 화를 한 파일로 — 투고·인쇄용 html / txt / md / epub |
| `at novel style <경로…>` | 화별 문체 지표를 나란히 놓고 유난히 다른 화를 짚는다 |
| `at novel timeline <경로…>` | 시간 표현을 모아 보고, 한 장면 안에서 시간대·계절이 어긋난 곳을 짚는다 |
| `at novel find <찾을것> <경로…>` | 앞뒤 문장과 함께 찾고 처음·마지막 등장 위치를 알려준다 |
| `at novel names <경로…>` | 인물·지명 후보를 뽑아 표기 흔들림과 이름 뒤 조사 오류를 찾는다 |
| `at novel snap <디렉터리>` | 원고 전체를 스냅샷으로 복사하고 분량 변화를 기록한다. `-l` 로 목록 |
| `at novel pace <디렉터리>` | 스냅샷으로 집필 속도를 재고 목표·마감까지 하루 몇 자인지 계산 |
| `at novel cast <경로…>` | 화별 인물 등장 흐름. 오래 안 나온 인물을 짚는다 |

```bash
at novel stats 원고/ --each
at novel check 원고/12화.txt --run 3 --long 80
at novel outline 원고/ -o 장면목록.xlsx
at novel wordlist 원고/ --min 3 -o 어휘.xlsx
at novel wordlist 원고/ --new           # 화마다 처음 나온 말
at novel wordlist 원고/ --only 12화     # 그 화에서만 쓰인 말
at novel dialogue 원고/ --samples 3
at novel export 원고/ --title "겨울 성문" --author 필명 --indent -o 투고본.html
at novel export 원고/ -f txt -o 투고본.txt
at novel export 원고/ -f epub --title "겨울 성문" --author 필명 -o 원고.epub
at novel style 원고/               # 화별 비교
at novel style 원고/12화.txt --by scene
at novel timeline 원고/ --context
at novel find "붉은 열쇠" 원고/          # 복선이 언제 깔리고 언제 회수됐는지
at novel names 원고/ --min 3
at novel names 원고/12화.txt --name 리안 --name 세드릭   # 이름을 직접 지정
at novel cast 원고/ --gone 5           # 5화 넘게 안 나온 인물
at novel snap 원고/ --note "3부 초고 완료"
at novel snap 원고/ -l
at novel pace 원고/ --goal 1500매 --due 2026-12-31
at novel pace 원고/ --window 14 --days 10        # 최근 2주 속도, 날짜별 표
```

`at novel cast` 는 화마다 인물이 몇 번 나오는지를 `.` `o` `+` 로 늘어놓아 등장 흐름을
한 줄로 보여 준다. 이름을 셀 때 조사는 붙여 세고(`리안이`, `리안에게`) **더 긴 이름의
일부는 세지 않는다**(`리안나`는 `리안`이 아니다). 오래 안 나온 인물을 따로 짚지만,
사라진 인물인지 잊은 인물인지는 판단하지 않는다.

`at novel pace` 는 `snap` 이 남긴 기록만 본다. 하루에 여러 번 찍었으면 그날 마지막 것만
세고, 첫 기록일은 그 전에 얼마를 썼는지 알 수 없으므로 '기준' 으로 표시하고 증가량에서
뺀다 — 0자 쓴 날과 섞이면 평균이 조용히 틀어진다. 하루 평균은 쉰 날까지 나눈 값과 실제로
쓴 날만 나눈 값을 따로 낸다. 도착일은 그 평균으로 민 어림값이지 계획이 아니다.

`at novel wordlist` 는 용어가 **어느 화에서 처음 나왔는지**와 **어느 화에서만 쓰였는지**를
본다. 설정 용어를 언제 도입했는지 되짚거나, 한 화에만 튀는 말을 찾을 때 쓴다.
`탑에·탑은·탑을`처럼 한 글자 어간에 조사가 붙은 것들은 서로 다른 조사가 두 종류 넘게
나올 때만 합친다 — 그래야 `가을`을 `가`+`을`로 자르지 않는다.

`at novel dialogue` 는 인물마다 대사 수·평균 길이·존댓말 비율·자주 쓰는 종결 어미를 낸다.
"카일만 유독 반말인가", "두 인물의 말투가 구별되는가"를 숫자로 본다. 화자는 **같은 줄
안에서만** 찾고 못 찾으면 비워 둔다 — 줄을 넘어가 다음 문단의 이름을 집으면 인물별
집계가 통째로 어긋나기 때문이다. 못 찾은 비율이 30%를 넘으면 그 사실을 알려 준다.

`-f epub` 은 e북 리더에서 읽을 수 있는 EPUB 3 를 만든다. 화마다 XHTML 한 편, 목차는
`nav.xhtml`, `mimetype` 은 압축하지 않고 맨 앞에 넣는다(그 순서가 어긋나면 리더가 파일을
열지 못한다). 종이나 화면이 바뀌면 안 보이던 것이 보이므로 퇴고에 쓴다.

`at novel export` 는 화마다 첫 제목 줄을 장 제목으로 삼아 한 파일로 묶는다. HTML 은
목차와 인쇄용 CSS(화마다 쪽 나눔)를 넣고, 들여쓰기는 공백 문자가 아니라 `text-indent` 로
준다 — 브라우저가 문단 앞 공백을 접어 버리기 때문이다. 앞서 내보낸 파일이 원고 디렉터리에
있으면 원고에서 빼므로, 형식을 바꿔 가며 다시 내보내도 자기 자신이 한 화로 끼어들지 않는다.

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
