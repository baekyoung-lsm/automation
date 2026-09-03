# attools

파일 정리, 백엔드 개발 잡일, 소설 원고 관리를 한 CLI로 묶은 도구.
표준 라이브러리만 쓰고 외부 의존성은 없다. Python 3.10+.

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
| `at file undo [저널]` | 직전 organize/fixname 을 되돌린다 |

```bash
at file organize ~/Downloads --by ext-date --min-age 7 -v   # 미리보기
at file organize ~/Downloads --by ext-date --min-age 7 --apply
at file fixname ~/Documents -r --apply
at file dupes ~/Pictures --script > 삭제후보.sh
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

```bash
at dev env                       # 배포 전 .env 점검, 문제 있으면 exit 1
at dev port 8080 --kill
at dev time 1750000000
kubectl logs pod | at dev mask > 공유용.log
pbpaste | at dev jwt -
```

`at dev env` 는 문제가 있으면 종료 코드 1을 돌려주므로 CI나 배포 스크립트에 그대로 넣을 수 있다.

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
