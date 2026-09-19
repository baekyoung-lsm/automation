"""«이럴 땐 이렇게» - 자주 하는 일과 그 명령.

명령이 이백 개가 넘어서 --help 만으로는 무엇부터 쳐야 할지 알기 어렵다.
하고 싶은 일에서 출발해 실제로 되는 명령 줄을 보여 준다.

여기 적힌 명령 줄은 모두 진짜 파서에 걸어 시험한다(tests/test_how.py).
안내만 그럴듯하고 안 되는 명령이면 없느니만 못하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Recipe:
    topic: str
    title: str                                   # 하고 싶은 일
    steps: list[str] = field(default_factory=list)   # 그대로 칠 수 있는 명령
    note: str = ""                               # 알아 둘 것 한 줄
    words: str = ""                              # 검색에만 쓰는 딴 이름

    @property
    def haystack(self) -> str:
        return " ".join([self.topic, self.title, self.note, self.words,
                         *self.steps]).lower()


# 주제 차례가 곧 목록에 나오는 차례다. 사무에서 자주 하는 것부터 둔다.
TOPICS = ("취합", "점검", "내보내기", "만들기", "파일", "PDF", "문서",
          "계산", "개발", "집필")

RECIPES: list[Recipe] = [
    # ------------------------------------------------------------ 취합
    Recipe("취합", "부서에서 받은 엑셀 여러 개를 한 표로 합치기",
           ["at sheet forms 제출/",
            "at sheet merge 제출/ -o 취합.xlsx"],
           "합치기 전에 forms 로 열 구성부터 본다. 열 이름이 다르면 값이 "
           "엉뚱한 열로 들어간다.",
           "머지 모으기 합본"),
    Recipe("취합", "같은 양식으로 받은 파일에서 같은 칸만 뽑기",
           ["at sheet collect 제출/ --cell B3=담당자 --cell C7=금액 -o 취합.xlsx"],
           "양식의 칸이 합쳐져 있어도 값이 든 칸을 따라간다.",
           "서식 양식 칸 취합"),
    Recipe("취합", "폴더 안 csv·엑셀에서 값이 어디 있는지 찾기",
           ["at sheet find 한빛상사 제출/"],
           "어느 파일 어느 시트 몇 행인지 알려 준다.",
           "검색 찾기"),
    Recipe("취합", "월별로 쪼개진 파일을 한 엑셀의 여러 시트로",
           ["at sheet book 1월.xlsx 2월.xlsx 3월.xlsx -o 분기.xlsx"],
           "반대로 시트를 파일로 나누려면 at sheet unbook.",
           "시트 워크북"),
    Recipe("취합", "두 표를 키로 붙이기 (VLOOKUP 대신)",
           ["at sheet join 명단.xlsx 연락처.xlsx --on 사번 -o 붙임.xlsx"],
           "키가 겹치거나 없는 행이 몇 개인지 함께 알려 준다.",
           "브이룩업 vlookup 조인"),
    Recipe("점검", "청구한 돈이 들어왔는지 통장 내역과 맞춰 보기",
           ["at sheet match 청구.xlsx 통장.csv --amount 금액 "
            "--right-amount 입금액 --name 거래처 --right-name 적요 "
            "--date 청구일 --right-date 입금일 -o 대사.xlsx"],
           "통장에는 청구서 번호가 없어 금액으로 먼저 맞춘다. 이름이 달라도 "
           "(대표자 개인명) 금액과 날짜가 맞으면 짝으로 본다. 이체 수수료는 "
           "--tol 1000 으로 감안한다.",
           "대사 미수금 미입금 수금 외상 채권 입금확인 reconcile"),
    Recipe("취합", "합치기 전에 열 이름 맞추기",
           ["at sheet rename 2팀.xlsx --map 성명=이름 -o 맞춤.xlsx"],
           "이름·성명처럼 한 글자만 달라도 다른 열이 된다.",
           "열이름 헤더"),

    # ------------------------------------------------------------ 점검
    Recipe("점검", "남이 보낸 표, 뭐부터 봐야 하나",
           ["at sheet audit 받은표.xlsx",
            "at sheet audit 받은표.xlsx --all"],
           "--all 은 엑셀 안의 시트를 한 줄씩 전부 훑는다.",
           "훑기 검수 확인"),
    Recipe("점검", "표에 적힌 합계가 맞는지 검산",
           ["at sheet total 정산서.xlsx --check",
            "at sheet total 정산서.xlsx --check --tol 1"],
           "행을 끼워 넣고 합계 식을 안 고친 표를 잡는다. 원 단위 절사는 --tol.",
           "합계 소계 총계 검산"),
    Recipe("점검", "명세서의 «수량 x 단가 = 금액» 검산",
           ["at sheet validate 명세서.xlsx --calc '금액=수량*단가'",
            "at sheet validate 계산서.xlsx --calc '세액=공급가액*0.1' --calc-tol 1"],
           "안 맞는 줄마다 적힌 값과 셈한 값을 나란히 보여 준다.",
           "세금계산서 거래명세서 부가세"),
    Recipe("점검", "중복·빈 칸·타입 섞임 찾기",
           ["at sheet check 명단.xlsx",
            "at sheet clean 명단.xlsx -o 정리본.xlsx"],
           "check 는 찾기만, clean 은 고친 사본을 만든다.",
           "중복 결측 문자숫자"),
    Recipe("점검", "전표 번호나 날짜가 빠진 곳 찾기",
           ["at sheet gaps 전표.xlsx -c 전표번호"],
           "빠진 것이 있으면 종료 코드 1 이라 점검 스크립트에 걸 수 있다.",
           "누락 결번 미제출"),
    Recipe("점검", "금액에 0 하나 더 붙은 줄 찾기",
           ["at sheet outliers 매출.xlsx -c 금액"],
           "지우지 않고 어느 행인지만 알려 준다.",
           "이상치 입력실수"),
    Recipe("점검", "거래처 이름이 제각각인 것 모으기",
           ["at sheet similar 거래처.xlsx -c 업체명"],
           "«(주)한빛»과 «한빛상사»처럼 같은 곳으로 보이는 값을 묶는다.",
           "표기흔들림 오타"),
    Recipe("점검", "규칙에 맞는 자료인지 한 번에 보기",
           ["at sheet validate 납품.csv --required 이름 --unique 사번 "
            "--format 연락처=휴대폰"],
           "규칙을 파일로 두려면 --rules 규칙.json.",
           "검증 필수 형식"),
    Recipe("점검", "두 판을 견줘 무엇이 바뀌었는지",
           ["at sheet diff 지난달.xlsx 이번달.xlsx --key 사번"],
           "추가·삭제·바뀐 값을 갈라 보여 준다. -o 로 표로 저장.",
           "비교 대조 변경"),

    # -------------------------------------------------------- 내보내기
    Recipe("내보내기", "보낼 폴더에 개인정보가 있는지 먼저 훑기",
           ["at text privacy 보낼폴더/",
            "at text privacy 보낼폴더/ --detail"],
           "워드·한글·PDF·엑셀 안까지 본다. 찾은 값은 가려서 보여 준다.",
           "주민번호 개인정보 점검"),
    Recipe("내보내기", "명단에서 개인정보 가린 사본 만들기",
           ["at sheet mask 명단.xlsx --auto -o 공유본.xlsx",
            "at sheet mask 보낼폴더 --auto -o 가린것 --apply"],
           "--auto 는 짐작이다. 무엇을 골랐는지 보고 빠진 것은 --name 으로 준다.",
           "마스킹 가리기 비식별"),
    Recipe("내보내기", "문서 속성에 남은 사람·회사 이름 지우기",
           ["at file docs 보낼폴더/",
            "at file scrub 보낼폴더/ --apply"],
           "원본은 두고 «(이름지움)» 사본을 만든다.",
           "메타데이터 작성자"),
    Recipe("내보내기", "사진에 남은 위치 정보 지우기",
           ["at file exif 사진/",
            "at file exif 사진/ --strip --apply"],
           "찍어 그대로 보낸 사진에는 집·사무실 좌표가 들어 있다.",
           "gps 위치 exif"),
    Recipe("내보내기", "메일 첨부 한도에 맞춰 나눠 담기",
           ["at file pack 자료/ --max 20MB -o 보낼것 --apply"],
           "한 파일이 한도보다 크면 그 사실을 알린다.",
           "첨부 압축 분할"),
    Recipe("내보내기", "받은 csv 무더기를 한글 안 깨지게 엑셀로",
           ["at sheet convert 받은자료 --to xlsx -o 엑셀본 --apply"],
           "cp949 로 온 파일도 알아서 읽는다.",
           "인코딩 깨짐 변환"),
    Recipe("내보내기", "표를 보고서 한 장으로",
           ["at sheet report 매출.xlsx -o 보고서.html --by 부서 --value 금액"],
           "브라우저로 열어 인쇄하면 그대로 제출본이 된다.",
           "html 보고 요약"),

    # ------------------------------------------------------------ 만들기
    Recipe("만들기", "거래처마다 견적서 한 장씩 만들기",
           ["at sheet form 견적서양식.xlsx --data 거래처.xlsx "
            "--cell B3=업체 --cell C7=금액 --name '{업체}_견적서.xlsx' "
            "-o 보낼것 --apply"],
           "양식의 서식·수식·그림은 그대로 두고 칸 값만 바꾼다.",
           "양식 서식 대량 견적서"),
    Recipe("만들기", "위촉장·수료증을 사람마다 한 장씩 (워드 양식)",
           ["at doc form 위촉장.docx --set 이름=김민수 -o 위촉장_김민수.docx",
            "at doc form 위촉장.docx --data 명단.xlsx --set 직책=자문위원 "
            "--name '{이름}_위촉장.docx' -o 결과 --apply"],
           "양식의 글꼴·표·머리글·도장 그림은 그대로 두고 «{이름}» 자리만 바꾼다.",
           "위촉장 수료증 공문 워드 양식 메일머지"),
    Recipe("만들기", "명단으로 사람마다 메일 초안 만들기",
           ["at sheet mail 명단.xlsx -t 본문.txt --subject '{이름}님 안내' "
            "--to 이메일 -o 초안 --apply"],
           "보내지는 않는다. .eml 파일을 만들어 메일 프로그램에서 열어 본다.",
           "메일머지 발송 안내문"),
    Recipe("만들기", "명단으로 사람마다 문서 만들기",
           ["at sheet fill 명단.xlsx -t 틀.md --name '{이름}.md' -o 결과 --apply"],
           "틀에 {이름} 처럼 열 이름을 적으면 채워진다.",
           "메일머지 통지문"),
    Recipe("만들기", "우편물 주소 라벨 인쇄용 만들기",
           ["at sheet labels 명단.xlsx --line '{이름}' --line '{주소}' -o 라벨.html"],
           "브라우저에서 열어 라벨지에 인쇄한다.",
           "라벨지 우편 주소"),
    Recipe("만들기", "명단을 휴대폰 연락처로",
           ["at sheet vcard 명단.xlsx --name 이름 --mobile 연락처 -o 연락처.vcf"],
           "일정은 at sheet ics 로 캘린더 파일이 된다.",
           "vcf 주소록 연락처"),
    Recipe("만들기", "그룹별 집계·교차표",
           ["at sheet pivot 매출.xlsx --row 부서 --value 금액 --agg sum",
            "at sheet pivot 매출.xlsx --row 부서 --col 월 --value 금액 --agg sum"],
           "글자로 든 숫자도 읽고, 못 읽은 칸은 몇 개인지 알려 준다.",
           "피벗 집계 합계"),
    Recipe("만들기", "표에 계산 열 붙이기",
           ["at sheet fx 급여.xlsx --add '월급=연봉/12' --round 0 -o 계산본.xlsx"],
           "--formula 를 주면 값 대신 엑셀 수식을 넣는다.",
           "수식 계산열"),
    Recipe("만들기", "표를 그림 한 장으로",
           ["at sheet chart 매출.xlsx --label 부서 --value 금액 -o 그림.svg"],
           "문서에 붙일 때 쓴다.",
           "차트 그래프"),

    # ------------------------------------------------------------ 파일
    Recipe("파일", "다운로드 폴더 한 번에 정리",
           ["at file sweep",
            "at file sweep --to 정리함 --apply"],
           "쓰임새(문서·사진·설치파일·스크린샷)별로 묶는다. 되돌리기는 at file undo.",
           "정리 청소 다운로드"),
    Recipe("파일", "확장자·날짜별로 폴더에 나눠 담기",
           ["at file organize 자료/ --by ext-date",
            "at file organize 자료/ --by ext-date --apply"],
           "미리보기가 기본이다. --apply 뒤에는 at file undo 로 되돌린다.",
           "분류 폴더"),
    Recipe("파일", "한글 파일명 깨짐·자모 분리 고치기",
           ["at file fixname 자료/",
            "at file fixname 자료/ --apply"],
           "맥에서 온 파일 이름이 «ㅎㅏㄴㄱㅡㄹ» 로 보일 때.",
           "자모분리 nfc 맥"),
    Recipe("파일", "한글 이름이 깨지는 zip 제대로 풀기",
           ["at file unzip 받은자료.zip -o 푼것"],
           "윈도우에서 만든 zip 의 cp949 이름을 알아서 읽는다.",
           "압축 zip 깨짐"),
    Recipe("파일", "내용이 같은 중복 파일 찾기·치우기",
           ["at file dupes 사진/",
            "at file dupes 사진/ --collect 중복함 --apply"],
           "지우지 않고 한곳에 모은다. at file undo 로 되돌아온다.",
           "중복 사본 정리"),
    Recipe("파일", "용량 차지하는 것 찾기",
           ["at file big .",
            "at file archive 자료/ --older 365 --apply"],
           "오래된 파일은 zip 으로 묶어 보관한다.",
           "용량 디스크 정리"),
    Recipe("파일", "받은 폴더 한 번에 훑기",
           ["at file audit 받은자료/"],
           "구성·이름 규칙·중복·찌꺼기 파일을 한 번에 본다.",
           "점검 훑기"),
    Recipe("파일", "백업 폴더에 새것·바뀐 것만 넣기",
           ["at file sync 원본/ 백업/",
            "at file sync 원본/ 백업/ --apply"],
           "지우지는 않는다. 두 폴더가 같은지는 at file diff.",
           "동기화 백업"),
    Recipe("파일", "받은 메일(.eml) 훑고 첨부 꺼내기",
           ["at file eml 메일/",
            "at file eml 메일/ -o 첨부 --apply"],
           "보내지는 않는다. 읽기만 한다.",
           "메일 첨부"),

    # ------------------------------------------------------------ PDF
    Recipe("PDF", "필요한 쪽만 뽑기",
           ["at file pdfcut 계약서.pdf --pages 1-3 -o 앞부분.pdf",
            "at file pdfcut 보고서.pdf --drop 1 -o 표지뺀것.pdf"],
           "눌린 자료를 그대로 옮겨 화질이 그대로다.",
           "자르기 분할 쪽"),
    Recipe("PDF", "여러 PDF 를 차례대로 합치기",
           ["at file pdfjoin 앞.pdf 본문.pdf 뒤.pdf -o 합본.pdf",
            "at file pdfnum 합본.pdf --skip 1 -o 번호붙임.pdf"],
           "합본에 쪽 번호까지 찍으면 제출본이 된다.",
           "합치기 병합 쪽번호"),
    Recipe("PDF", "거꾸로 스캔된 쪽 바로잡기",
           ["at file pdfturn 스캔본.pdf --rotate 180 --even -o 바로잡은.pdf",
            "at file pdfturn 스캔본.pdf --reverse -o 차례대로.pdf"],
           "낱장 급지로 양면을 뜨면 뒷면만 뒤집혀 들어온다.",
           "회전 뒤집힘 스캔"),
    Recipe("PDF", "도장·서명 얹기",
           ["at file pdfstamp 계약서.pdf --image 도장.png --where bottom-right "
            "-o 날인본.pdf"],
           "인쇄해서 찍고 다시 스캔하지 않아도 된다.",
           "도장 날인 서명"),
    Recipe("PDF", "PDF 에서 글자·그림 꺼내기",
           ["at file pdftext 자료.pdf",
            "at file pdfimg 자료.pdf -o 그림 --apply"],
           "스캔본은 글자가 없다 - 그때는 빈 쪽으로 알려 준다.",
           "복사 추출 텍스트"),
    Recipe("PDF", "사진·스캔 이미지를 PDF 한 장으로",
           ["at file pdf 사진/ -o 묶음.pdf"],
           "JPEG 은 다시 그리지 않고 그대로 넣어 화질이 그대로다.",
           "이미지 묶기"),
    Recipe("PDF", "스캔본에서 백지 쪽 찾기",
           ["at file pdfblank 스캔본.pdf"],
           "짐작이므로 열어 보고 at file pdfcut --drop 으로 뺀다.",
           "빈쪽 백지"),

    # ------------------------------------------------------------ 문서
    Recipe("문서", "받은 워드·한글·슬라이드를 글로 열기",
           ["at doc from-docx 보고서.docx -o 보고서.md",
            "at doc from-hwpx 공문.hwpx -o 공문.md"],
           "옛 .hwp 는 못 읽는다 - 한글에서 hwpx 로 저장해야 한다.",
           "한글 워드 변환 열기"),
    Recipe("문서", "문서 안의 표만 엑셀로 뽑기",
           ["at sheet from-docx 보고서.docx -o 표.xlsx",
            "at doc tables 문서.md -o 표.csv"],
           "표가 여럿이면 --index 로 고른다.",
           "표추출 도표"),
    Recipe("문서", "마크다운을 워드·HTML 로 내기",
           ["at doc docx 보고서.md -o 보고서.docx",
            "at doc html 보고서.md -o 보고서.html"],
           "제출본은 워드, 공유는 HTML 이 편하다.",
           "제출 변환"),
    Recipe("문서", "문서 점검 한 번에",
           ["at doc lint 문서/",
            "at doc toc README.md --apply"],
           "깨진 링크·없는 그림·제목 건너뜀·용어 흔들림을 본다.",
           "링크 목차 점검"),
    Recipe("문서", "회의록에 적어 둔 할 일 모으기",
           ["at doc todo 회의록/"],
           "«- [ ]» 로 적은 줄을 모은다.",
           "할일 체크박스 회의"),

    # ------------------------------------------------------------ 계산
    Recipe("계산", "월급에서 4대보험이 얼마나 빠지나",
           ["at life insure 300만",
            "at life insure 4800만 --annual --tax 84850"],
           "근로소득세는 간이세액표를 봐야 해서 세지 않는다.",
           "국민연금 건강보험 실수령액"),
    Recipe("계산", "퇴직금·연차·주휴수당",
           ["at life severance 2020-03-02 2026-09-01 --pay 1500만",
            "at life annual 2020-03-02",
            "at life weekly 10030 --hours 20"],
           "모두 세전이고, 회사 규정이 우선이다.",
           "퇴직금 연차 주휴"),
    Recipe("계산", "영업일·마감일 세기",
           ["at life workday 2026-09-17 +10",
            "at life cal 2026-10"],
           "설날·추석은 음력이라 계산하지 않고 경고를 띄운다.",
           "영업일 공휴일 마감"),
    Recipe("계산", "부가세·원천징수",
           ["at life tax 1100000",
            "at life tax 300만 --withhold-rate 8"],
           "사업소득 3.3%, 기타소득 8.8%.",
           "부가세 세금 3.3"),
    Recipe("계산", "근무 시간과 수당",
           ["at life time 09:00-18:30 --break 60",
            "at life hourly 300만 --overtime 10"],
           "연장·야간 가산은 근로기준법 제56조 기준이다.",
           "근무시간 연장 야근"),

    # ------------------------------------------------------------ 개발
    Recipe("개발", "API 를 순서대로 불러 보기",
           ["at dev calls api.http",
            "at dev calls api.http --run --var user=kim"],
           "기본은 미리보기다. POST·DELETE 는 한 번 더 묻는다.",
           "http rest api 테스트"),
    Recipe("개발", "HTTP 한 번 부르기",
           ["at dev http localhost:8080/api/users",
            "at dev http api.example.com/orders --json '{\"수량\":2}'"],
           "4xx·5xx 도 결과로 보여 준다.",
           "curl 요청"),
    Recipe("개발", "Dockerfile 훑기",
           ["at dev docker .",
            "at dev docker . --strict"],
           "latest 태그·root 실행·캐시를 깨는 COPY 차례를 짚는다.",
           "도커 컨테이너"),
    Recipe("개발", "로그에서 무슨 일이 있었는지",
           ["at dev log app.log",
            "at dev slow access.log"],
           "반복 에러를 묶고 응답 시간 백분위를 낸다.",
           "로그 에러 분석"),
    Recipe("개발", "커밋 전 점검",
           ["at git ready",
            "at git scan"],
           "시크릿·충돌 표시·디버그 자국을 본다.",
           "시크릿 커밋"),
    Recipe("개발", "새로 받은 저장소 훑기",
           ["at dev doctor .",
            "at dev loc ."],
           "무엇으로 만들었고 시험은 어떻게 돌리는지 알려 준다.",
           "온보딩 저장소"),
    Recipe("개발", "가짜 자료·가짜 API 로 시험하기",
           ["at dev fake -c 이름 -c 연락처=전화 -n 200 -o 시험자료.xlsx",
            "at dev mock openapi.json"],
           "한글 이름·전화·주소로 만든다.",
           "목업 테스트데이터"),

    # ------------------------------------------------------------ 집필
    Recipe("집필", "원고 분량 세기",
           ["at novel stats 원고/",
            "at text count 원고/ -g '*.md'"],
           "원고지 매수와 단행본 쪽수로 환산해 준다.",
           "매수 분량 원고지"),
    Recipe("집필", "퇴고 점검 한 번에",
           ["at novel check 원고/",
            "at novel pov 원고/",
            "at novel punct 원고/"],
           "반복·상투구·긴 문장, 시제 혼용, 문장 부호를 본다.",
           "퇴고 교정"),
    Recipe("집필", "인물 이름 바꾸기 (조사까지)",
           ["at novel rename 리안 세하 원고/",
            "at novel rename 리안 세하 원고/ --apply"],
           "«리안은» → «세하는» 처럼 뒤에 붙은 조사까지 맞춘다.",
           "개명 치환"),
    Recipe("집필", "복선이 회수됐는지 보기",
           ["at novel thread 원고/ -w 목걸이 -w 편지",
            "at novel cast 원고/"],
           "소재와 인물이 어느 화부터 안 나오는지 짚는다.",
           "복선 회수 등장"),
    Recipe("집필", "투고본 만들기",
           ["at novel export 원고/ -o 투고본.docx",
            "at novel export 원고/ -o 원고.epub"],
           "화 차례는 파일 이름 순이다.",
           "epub 투고 제출"),
]


def topics() -> list[str]:
    """레시피가 하나라도 있는 주제만, 정해 둔 차례대로."""
    있는 = {one.topic for one in RECIPES}
    return [t for t in TOPICS if t in 있는]


def by_topic(topic: str) -> list[Recipe]:
    key = topic.strip().lower()
    return [one for one in RECIPES if one.topic.lower() == key]


def search(needle: str) -> list[Recipe]:
    """제목·명령·딴 이름에서 찾는다. 띄어쓰기를 지운 꼴도 본다."""
    key = needle.strip().lower()
    if not key:
        return []
    flat = key.replace(" ", "")
    return [one for one in RECIPES
            if key in one.haystack or flat in one.haystack.replace(" ", "")]


def commands() -> list[str]:
    """레시피에 적힌 모든 명령 줄. 시험에서 파서에 걸어 본다."""
    return [step for one in RECIPES for step in one.steps]
