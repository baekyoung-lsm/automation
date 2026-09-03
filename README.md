# attools

파일 정리, 백엔드 개발 잡일, git 관리, 일상 계산, 소설 원고 관리를 한 CLI로 묶은 도구.
표준 라이브러리만 쓰고 외부 의존성은 없다. Python 3.10+.

- `file` 파일 분류·이름 정리·중복 탐지·변경 감시
- `dev` .env 대조, 포트, JWT, 시각 변환, 로그 마스킹, 헬스체크 대기, cron 해석, 키 생성
- `git` 병합된 브랜치 정리, 커밋 전 시크릿 검사
- `life` D-day, 더치페이 정산, 대출 계산, 단위 변환
- `novel` 원고 분량 집계, 반복·상투구 점검, 스냅샷

```
git clone <repo> && cd automation
./at --help                 # 그대로 실행
ln -s "$PWD/at" ~/.local/bin/at   # 또는 PATH 에 링크
pip install -e .            # 또는 패키지로 설치 (at 명령 생성)
```

파일을 옮기거나 이름을 바꾸는 명령은 **기본이 미리보기**다. `--apply` 를 붙여야 실제로 실행되고,
실행 내역은 `~/.attools/journal/` 에 남아 `at file undo` 로 통째로 되돌릴 수 있다.

## file — 파일 정리

| 명령 | 하는 일 |
| --- | --- |
| `at file organize <디렉터리>` | 확장자 종류(문서/이미지/영상/압축/코드…)나 날짜별로 분류해 옮긴다 |
| `at file fixname <디렉터리>` | macOS에서 넘어온 한글 자모 분리(NFD) 파일명을 완성형으로 고치고, 윈도우 금지문자·중복 공백을 정리한다 |
| `at file dupes <디렉터리>` | 내용이 같은 파일을 찾는다. 직접 지우지 않고 `--script` 로 삭제 명령만 출력한다 |
| `at file watch <경로> -- <명령>` | 파일이 바뀌면 명령을 다시 실행한다 (테스트·빌드 자동 재실행) |
| `at file big [경로]` | 어디가 용량을 먹는지 디렉터리·파일 순위로 보여준다 |
| `at file undo [저널]` | 직전 organize/fixname 을 되돌린다 |

```bash
at file organize ~/Downloads --by ext-date --min-age 7 -v   # 미리보기
at file organize ~/Downloads --by ext-date --min-age 7 --apply
at file fixname ~/Documents -r --apply
at file dupes ~/Pictures --script > 삭제후보.sh
at file watch src -p '*.py' -- pytest -q
at file big ~/Downloads --depth 2
at file undo
```

분류 카테고리는 `attools/files.py` 의 `CATEGORIES` 에 있다. `hwp`, `hwpx`, `alz`, `egg` 처럼
한국에서 자주 쓰는 확장자를 포함한다.

## dev — 백엔드 개발

| 명령 | 하는 일 |
| --- | --- |
| `at dev env [예시] [실제]` | `.env.example` 과 `.env` 를 대조해 빠진 키·빈 값·예시 값 그대로인 키를 찾는다 (기본값: `.env.example` `.env`) |
| `at dev port <포트>` | 포트를 잡고 있는 프로세스를 찾고 `--kill` 로 종료한다 |
| `at dev jwt <토큰>` | JWT 헤더·페이로드를 디코드하고 `exp`/`iat` 를 KST로 보여준다 (서명 검증 안 함) |
| `at dev time [값]` | epoch(초/밀리초)·ISO 문자열·`now` 를 KST/UTC/epoch 로 상호 변환한다 |
| `at dev mask [파일]` | 로그를 공유하기 전에 주민등록번호·전화·카드·이메일·토큰·비밀번호를 가린다 |
| `at dev wait <대상>` | `host:port` 나 URL 이 응답할 때까지 기다린다. 컨테이너 띄운 뒤 헬스체크용 |
| `at dev cron <표현식>` | cron 표현식을 한국어로 풀어 주고 다음 실행 시각을 KST로 보여준다 |
| `at dev gen [종류]` | 비밀번호·토큰·hex·UUID·PIN 을 CSPRNG 로 만든다 |
| `at dev enc <값>` | base64/base64url/hex/URL 인코딩과 해시를 한 번에, 디코딩도 자동 시도 |

```bash
at dev env                       # 배포 전 .env 점검, 문제 있으면 exit 1
at dev port 8080 --kill
at dev time 1750000000
kubectl logs pod | at dev mask > 공유용.log
pbpaste | at dev jwt -
at dev wait localhost:5432 -t 60 && ./migrate.sh
at dev cron "30 2 * * 6"
at dev gen password -l 20 --readable
at dev enc "SGVsbG8gd29ybGQ="
```

`at dev env` 는 문제가 있으면 종료 코드 1을 돌려주므로 CI나 배포 스크립트에 그대로 넣을 수 있다.

## git — 저장소 정리와 검사

| 명령 | 하는 일 |
| --- | --- |
| `at git sweep [경로]` | 기준 브랜치에 병합이 끝난 로컬 브랜치, 원격이 사라진 추적 브랜치를 찾아 지운다 |
| `at git scan [경로]` | 코드에 하드코딩된 API 키·토큰·개인 키·접속 문자열 비밀번호·주민등록번호를 찾는다 |

```bash
at git sweep --fetch              # 미리보기
at git sweep --fetch --apply
at git scan                       # 추적 중인 파일 전체
at git scan --staged --quiet      # 커밋 직전 검사, 발견되면 exit 1
at git scan --install-hook "$HOME/.local/bin/at"   # pre-commit 훅으로 설치
```

`your-key-here`, `${VAULT_SECRET}`, `os.environ[...]` 같은 플레이스홀더는 걸러 낸다.
테스트 픽스처처럼 일부러 넣은 값은 그 줄에 `# attools: ignore` 를 달면 넘어간다.
`--entropy 4.0` 을 주면 패턴에 안 걸리는 무작위 문자열도 함께 신고한다.

## life — 일상 계산

| 명령 | 하는 일 |
| --- | --- |
| `at life dday <날짜…>` | D-day, 만 나이, 다가올 100일·주년 기념일 |
| `at life split <이름=금액…>` | 더치페이 정산. 송금 횟수가 가장 적게 나오도록 짝지어 준다 |
| `at life loan <원금> <연이율> [년]` | 원리금균등·원금균등·만기일시 상환액과 총 이자, 상환표 |
| `at life unit <값+단위>` | 평↔㎡, 근·돈·관, 되·말, 마일·파운드·인치, 화씨↔섭씨 |

```bash
at life dday 2024-03-15 2027-01-01
at life split 홍길동=45000 김철수=12000 --extra 박민수
at life loan 3억5000만 4.2 30 --table 12
at life loan 2억 3.9 --months 240 --kind 원금균등 --grace 12
at life unit 84㎡        # 25.41평
at life unit 100F        # 37.78℃
```

금액은 `3억5000만`, `1.5억`, `350,000,000` 다 받는다. `100일` 은 한국식으로 시작일을
1일로 세어 계산한다(시작일 + 99일).

## novel — 소설 집필

| 명령 | 하는 일 |
| --- | --- |
| `at novel stats <파일/디렉터리…>` | 공백 포함·제외 글자수, 200자 원고지 매수, 문장·문단 수, 평균 문장 길이, 대사 비율, 읽는 시간, 단행본 환산 |
| `at novel check <파일>` | 상투 표현, 군더더기 부사, 반복 어구, 같은 종결 어미 연속, 같은 말로 시작하는 문장 연속, 너무 긴 문장 |
| `at novel snap <디렉터리>` | 원고 전체를 스냅샷으로 복사하고 분량 변화를 기록한다. `-l` 로 목록 |

```bash
at novel stats 원고/ --each
at novel check 원고/12화.txt --run 3 --long 80
at novel snap 원고/ --note "3부 초고 완료"
at novel snap 원고/ -l
```

집계 기준: 원고지는 공백 포함 200자, 읽는 속도는 분당 550자, 단행본은 공백 제외 10만자를
1권으로 잡는다. 출판사마다 다르므로 어림값이다. 기준은 `attools/manuscript.py` 상단 상수에서 바꾼다.
상투 표현·부사 목록도 같은 파일의 `CLICHES`, `FILLER_ADVERBS` 에서 고칠 수 있다.

## 테스트

```bash
python3 -m unittest discover -s tests
```
