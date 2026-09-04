# 검증 체크리스트

[service.md](service.md)의 기능 정의와 [design.md](design.md)의 설계에 대한 판정 기준.
실제 실행 결과는 이 파일이 아니라 [evaluation/report.md](evaluation/report.md)에 기록한다
(report.md는 아래 표 스타일을 그대로 재사용한다).

## 사용법

- 각 항목은 `python -m src.main`을 통하지 않고 도구 함수(`src.tools.detect_matches`,
  `src.tools.query_matches`)를 직접 호출해서 확인할 수 있다. LLM 응답 품질과 무관하게
  수집·탐지·저장·조회·알림이 맞는지 보는 것이 목적이다.
- 판정은 **Pass / Fail / N/A** 셋 중 하나로 적는다. 확인하지 못한 항목은 Fail이 아니라
  `미실행`으로 남기고, 통과율 계산에서 분모에 포함한다.
- **출시 기준: 전체 테스트 케이스 중 90% 이상 Pass** ([service.md](service.md) 성공 기준 8).
  아래 케이스는 총 71건(수집 13 / 탐지 12 / 매칭 기록 7 / 저장 8 / 조회 14 / 알림 7 / 패턴 도출 10)이므로
  Fail + 미실행이 7건을 넘으면 출시 불가다.

---

## 1. 수집

`src/_browser.py`(`record_session`), `tools.collect_traffic()`, `collect` 테이블

브라우저를 띄워 사람이 직접 둘러보는 동안의 관측 데이터를 모으는 단계다.
점검 대상 URL 목록 파일은 쓰지 않는다.

| ID | 확인 항목 | 절차 | 판정 기준 |
|---|---|---|---|
| 1-1 | 요청 헤더 수집 | 로컬 페이지 방문 | 요청 헤더가 `header` 위치로 저장되고 `detail`에 `direction: request`, `method`가 담긴다 |
| 1-2 | 응답 헤더 수집 | 응답에 커스텀 헤더를 실은 페이지 방문 | 응답 헤더가 `header` 위치로 저장되고 `detail`에 `direction: response`, `status`가 담긴다 |
| 1-3 | 응답 바디 수집 | 본문에 문자열이 있는 페이지 방문 | 본문이 `body` 위치로 저장된다. 핸들러가 아니라 대기 루프에서 읽으므로 교착이 없다 |
| 1-4 | 요청 페이로드 수집 | POST를 보내는 페이지 방문 | POST 본문이 `request_body` 위치로 저장되고 `detail.method`가 `POST`다 |
| 1-5 | 쿠키 수집 | `Set-Cookie`를 내려주는 페이지 방문 | 쿠키가 `cookie` 위치로 저장된다 (창이 살아 있는 마지막 시점에 한 번) |
| 1-6 | 콘솔 로그·JS 에러 수집 | `console.log`와 던져진 예외가 있는 페이지 방문 | 둘 다 `console` 위치로 저장되고 `detail.kind`로 구분된다 |
| 1-7 | targets 설정 반영 | patterns.json에서 `body`/`console`을 false로 | 해당 위치의 저장이 0건이 된다 |
| 1-8 | targets 전부 꺼짐 거부 | 수집 대상을 모두 false로 | 스캔 시작 전에 실패한다 (설정 실수를 "유출 없음"으로 오해하지 않게) |
| 1-9 | 새 탭 로딩·수집 | `target=_blank` 링크를 클릭 | 새 탭이 정지하지 않고 로딩되며 그 탭의 요청도 저장된다 (`input()`으로 메인 흐름을 막으면 새 탭이 "디버거 붙기 대기"로 멈춘다) |
| 1-10 | 종료 신호 | 터미널에서 Enter / 창을 먼저 닫기 | 두 경우 모두 수집이 끝나고 저장 건수를 알린다. 창을 닫은 경우도 30초 기다리지 않는다 |
| 1-11 | chromePath 처리 | `null`과 실제 Chrome 경로 두 가지로 실행 | `null`이면 Playwright 관리 Chromium, 문자열이면 그 실행 파일로 뜬다 |
| 1-12 | 로그인 세션 미저장 | 수집 중 로그인한 뒤 파일 확인 | `storage_state` 파일을 만들지 않는다. 무관한 사이트 세션까지 한 파일에 모이는 위험을 피하려 의도적으로 뺀 기능이다 |
| 1-13 | 저장 형식 | 수집 후 `collect` 테이블 조회 | `url`/`location`/`content`/`detail_json`/`collected_at`이 채워진다. `_browser`의 emit과 같은 모양이라 수집·저장 형식이 어긋날 수 없다 |

## 2. 탐지

`src/_matcher.py`, `data/patterns.json`

| ID | 확인 항목 | 절차 | 판정 기준 |
|---|---|---|---|
| 2-1 | 거짓 음성 없음 | 등록 패턴에 매칭되는 값을 4개 위치에 모두 심음 | 4건 모두 탐지된다 |
| 2-2 | 거짓 양성 없음 | 어떤 패턴에도 걸리지 않는 페이지 방문 | 매칭 0건 |
| 2-3 | 패턴 이름 중복 거부 | 같은 `name`을 두 번 등록 | 스캔 시작 전에 중복된 이름을 알려주며 실패한다 |
| 2-4 | 잘못된 정규식 거부 | 컴파일 불가능한 `regex` 등록 | 스캔 시작 전에 **패턴 이름과 함께** 실패한다 |
| 2-5 | 빈 패턴 목록 거부 | `patterns`를 `[]`로 | 스캔 시작 전에 실패한다 |
| 2-6 | 동일 값 중복 제거 | 한 수집 덩어리(응답 1건의 바디 등)에 같은 값을 여러 번 심음 | 1건으로 합쳐 저장한다. 단, 서로 다른 리소스에서 나온 같은 값은 출처가 다르므로 각각 저장한다 |
| 2-7 | 다중 패턴 동시 적용 | 서로 다른 두 패턴에 걸리는 값을 한 페이지에 심음 | 패턴별로 각각 탐지된다 |
| 2-8 | 설정 파일 부재 | patterns.json 삭제 후 실행 | 경로를 알려주며 실패한다 |
| 2-9 | method 필터 적용 | `filters.methods: ["POST"]`로 두고 GET·POST가 섞인 페이지 방문 | `detail.method`가 POST인 항목만 매칭된다. GET 요청과 `method`가 없는 항목(응답 헤더·바디·쿠키·콘솔)은 모두 제외된다 |
| 2-11 | collect 기준 탐지 | collect에 행이 있는 상태로 `detect_matches()` | 브라우저를 띄우지 않고 저장된 덩어리를 검사한다. `source`가 `data/scan.db#collect`이고 `chunks_total`이 collect 행 수와 같다 |
| 2-12 | 대상 없음 | collect를 비운 뒤 `detect_matches()` | 사유와 다음 할 일(`collect_traffic` 먼저 실행)을 담은 `ValueError`로 실패한다 |
| 2-10 | method 필터 미설정 | `filters` 키 삭제 / `filters: {}` / `methods: []` / `methods: null` 네 가지로 각각 실행 | 네 경우 모두 수집된 전부를 매칭하고 반환값 `method_filter`가 `null`이다. 빈 배열은 에러가 아니다 |

## 3. 매칭 기록

`matches` 테이블 컬럼 구성

| ID | 확인 항목 | 절차 | 판정 기준 |
|---|---|---|---|
| 3-1 | 매칭 값 원본 보존 | 매칭 발생 후 DB 조회 | `matched_value`가 마스킹·절삭 없이 원본과 바이트 단위로 같다 |
| 3-2 | URL / 요청 출처 | 페이지와 다른 호스트의 리소스에서 매칭 발생 | `url`에 매칭이 나온 **리소스** URL이 들어가고, `detail.page_url`에 방문한 페이지 URL이 들어간다 |
| 3-3 | 위치 구분 | 5개 위치 각각에서 매칭 발생 | `location`이 `header` / `body` / `request_body` / `cookie` / `console` 중 정확한 값이다 |
| 3-4 | 타임스탬프 | 매칭 발생 후 DB 조회 | `matched_at`이 UTC ISO 8601 문자열이고, 스캔 시작·종료 시각 사이에 있다 |
| 3-5 | 패턴 이름 | 매칭 발생 후 DB 조회 | `pattern_name`이 patterns.json에 등록한 이름과 같다 |
| 3-6 | 부가 정보 | 헤더 매칭 후 `detail` 확인 | 요청/응답 구분, method 또는 status가 담겨 있다 |
| 3-7 | 매칭 문맥 | 한 덩어리에서 서로 다른 값이 2건 이상 매칭된 뒤 DB 조회 | `detail.context`에 매칭 자리 앞뒤 40자가 담긴다. 잘린 쪽에는 `...`이 붙는다. **매칭마다 값이 달라야 한다** (공유 dict를 복사하지 않으면 마지막 문맥이 전부에 덮인다) |

## 4. 저장

`src/_storage.py`, `scans`/`matches` 스키마

| ID | 확인 항목 | 절차 | 판정 기준 |
|---|---|---|---|
| 4-1 | 스키마 자동 생성 | scan.db 삭제 후 실행 | `data/` 디렉토리와 두 테이블, 인덱스 4개가 만들어진다 |
| 4-2 | 스캔 시작 기록 | 스캔 도중 DB 조회 | `scans` 행이 `status='running'`, `started_at` 채워진 상태로 존재한다 |
| 4-3 | 스캔 종료 기록 | 스캔 완료 후 DB 조회 | `finished_at`, `chunks_scanned`가 채워지고 `status`가 `completed`(1건 이상 검사) 또는 `failed`(하나도 못 함)다 |
| 4-4 | 예외 시에도 상태 정리 | 스캔 도중 강제로 예외 발생 | `scans.status`가 `running`으로 남지 않는다 |
| 4-5 | 스캔-매칭 연결 | 두 번 연속 스캔 후 조회 | 각 매칭의 `scan_id`가 자기 스캔의 id를 가리킨다 |
| 4-6 | 누적 저장 | 같은 DB에 스캔을 두 번 실행 | 이전 스캔의 매칭이 지워지지 않고 함께 남는다 |
| 4-7 | 재현성 | 같은 collect 데이터에 같은 patterns.json으로 두 번 `detect_matches()` | 두 스캔의 매칭 건수와 (패턴, 위치, 값) 조합이 같다. 브라우저를 쓰지 않으므로 사이트 변화에 영향받지 않는다 |
| 4-8 | collect 테이블 저장 | `save_collected()` 호출 후 DB 조회 | `collect`에 url/method/headers_json/body/time이 저장된다. 본문 없는 요청은 `body`가 NULL이고, 헤더는 JSON 문자열이다 |

## 5. 조회

`src/retriever.py`(`find_matches`), `tools.query_matches()`

| ID | 확인 항목 | 절차 | 판정 기준 |
|---|---|---|---|
| 5-1 | 무조건 조회 | 인자 없이 `query_matches()` | 최근 매칭이 `limit`건까지 반환된다 |
| 5-2 | pattern_name 필터 | 패턴 이름 하나를 지정 | 그 패턴의 매칭만 반환된다 |
| 5-3 | url_substring 부분 일치 | URL 일부 문자열을 지정 | 해당 문자열을 포함하는 URL의 매칭만 반환된다 |
| 5-4 | 날짜 범위 필터 | `date_from` / `date_to` 지정 | 범위 밖 매칭이 제외된다. 날짜 접두사(`2026-09-02`)만 줘도 동작한다 |
| 5-5 | scan_id 필터 | 특정 스캔 id 지정 | 그 스캔의 매칭만 반환된다 |
| 5-6 | 복합 조건 | 두 개 이상 조건 동시 지정 | AND로 결합되어 좁혀진다 |
| 5-7 | 정렬과 limit | limit을 전체 건수보다 작게 | 최신순으로 정확히 limit건 반환된다 |
| 5-8 | 데이터 무결성 | 저장된 값과 조회 결과 비교 | 매칭 값·URL·위치·패턴명·타임스탬프가 저장된 값과 정확히 일치한다 |
| 5-9 | detail 역직렬화 | 조회 결과의 `detail` 확인 | `detail_json`이 dict로 파싱되어 반환된다 |
| 5-10 | 조회는 상태를 바꾸지 않음 | 조회 전후 DB 비교 | `scans`/`matches` 행 수와 내용이 그대로다 |
| 5-11 | 결과 없음 | 매칭되지 않는 조건 지정 | 에러 없이 빈 목록을 반환한다 |
| 5-12 | 중복 없는 값 집계 | `find_distinct_values()` 호출 | 같은 값이 하나로 묶이고 `hits`가 실제 등장 횟수와 같다. 빈도 내림차순으로 정렬된다 |
| 5-13 | 검증 코퍼스 수집 | `find_context_texts()` 호출 | `url`과 `detail_json`의 문자열만 모으고 `matched_value`는 포함하지 않는다 (편향 방지) |
| 5-14 | collect 조회 | `find_collected()` 호출 | 저장 순서대로 반환되고, `headers_json` 컬럼이 dict로 파싱되어 **`headers` 키**로 넘어온다 (`headers_json` 키는 없다) |

## 6. 알림

`src/_notify.py`

| ID | 확인 항목 | 절차 | 판정 기준 |
|---|---|---|---|
| 6-1 | 매칭 즉시 출력 | 매칭이 있는 페이지 방문 | 매칭마다 `[MATCH]` 한 줄이 출력된다. 필터로 제외된 항목은 출력되지 않는다 |
| 6-2 | 출력 형식 | `[MATCH]` 줄 확인 | `[MATCH] pattern=<이름>\|location=<위치>\|matched_value=<값>\|url=<URL>\|context=<문맥>\|detail=<부가정보>` 형식이며 한 줄이다. 필드는 `\|`로 구분한다. `context`와 `detail`은 각각 200자까지만 싣고 넘치면 `...`으로 자른다. 값에 줄바꿈이 있어도 공백으로 접어 한 줄을 유지한다 |
| 6-3 | 즉시성 | URL 2개를 스캔하고 출력 순서 확인 | 첫 URL의 `[MATCH]`가 두 번째 URL 처리 시작 전에 출력된다 (버퍼링 지연 없음) |
| 6-4 | 스트림 분리 | 표준출력만 파이프로 받음 | `[MATCH]`와 에이전트 최종 응답은 stdout, `[RECORD]`·`[TRACE]` 같은 진행 알림은 stderr로 나가 서로 섞이지 않는다 |
| 6-5 | 값 노출 정책 | `[MATCH]` 줄 확인 | 매칭된 값 자체는 콘솔에 출력한다 (DB에도 원본 저장). `matched_value`는 자르지 않고 원본 전체를 싣는다 |
| 6-6 | 문맥 분리 출력 | `page_url`이 긴 페이지에서 매칭 발생 | `context`가 `detail`과 별개 필드로 나와, `detail`이 200자에 잘려도 문맥이 사라지지 않는다 |

## 7. 패턴 도출

`src/_induce.py`, `tools.suggest_patterns()`

| ID | 확인 항목 | 절차 | 판정 기준 |
|---|---|---|---|
| 7-1 | 구분자 기반 귀납 | 서브도메인 깊이가 다른 URL 여러 개로 `induce_regex()` | 공통 접두/접미가 앵커로 고정되고 가변부가 `(?:[문자클래스]+\.){lo,hi}` 형태로 일반화된다. strict/open/bounded 3변형이 나온다 |
| 7-2 | 구분자 없는 값 귀납 | 공통 접두사만 있는 토큰 여러 개(JWT 조각 등)로 `induce_regex()` | 접두사가 리터럴로 고정되고 나머지가 문자 클래스 + 길이 범위가 된다 (문자 단위 시그니처처럼 폭발하지 않는다) |
| 7-3 | 완화 사다리 | 매칭 0건인 tight 패턴으로 `suggest_patterns()` | 수량자/문자클래스/구분자/리터럴/스킴 축별 변형이 만들어지고, 코퍼스에서 매칭이 생기는 축만 병목으로 보고된다 |
| 7-4 | 회귀 없음 게이트 | 표본이 적어 과적합한 후보가 나오는 상황 | 기존 패턴이 잡던 값을 놓치는 후보(`lost` 있음)는 채택되지 않고, 탈락 이유가 note에 표시된다 |
| 7-5 | 과일반화 점검 | 후보의 합성 음성 차단율 확인 | 앵커를 훼손한 값(`notnaver.com`, `naver.com.attacker.io` 등)을 후보가 잡지 않는다 |
| 7-6 | 제안 전용 | `suggest_patterns()` 호출 전후 비교 | `data/patterns.json`이 바뀌지 않는다 (해시 동일) |
| 7-7 | collect 본문 귀납 | `suggest_patterns(source="collect")` | JSON 본문의 같은 키끼리 값을 모아 키별로 후보를 만든다. 반환값에 `json_key`가 담기고 `rows_analyzed`가 본문 있는 행 수와 같다 |
| 7-8 | limit이 본문 행만 센다 | 본문 없는 행이 대다수인 상태에서 `source="collect"` | 본문 있는 행이 `limit`보다 적으면 전부 분석된다 (본문 없는 행이 limit을 먹지 않는다) |
| 7-9 | 표본 부족 키 제외 | 값이 `min_cluster` 미만인 키가 섞인 상태 | 그 키는 후보를 만들지 않고 `keys_too_few_values`로 센다 |
| 7-10 | source 검증 | `source`에 `matches`/`collect` 외 값 지정 | `ValueError`로 거부한다. 두 경로 모두 반환값에 `source` 필드가 있어 어느 테이블을 분석했는지 알 수 있다 |
| 7-11 | 컬럼 지목 조회 | `suggest_patterns(column="content", json_key="sectionId")` | 그 컬럼·키를 WHERE 절로 걸러 조회한 행만 분석하고, 후보를 상위 몇 개로 자르지 않는다 |
| 7-12 | 없는 컬럼을 지목 | `suggest_patterns(column="detail_json", json_key="sectionId")` | `rows_analyzed`가 0이고, `found_in_other_columns`에 실제로 있는 컬럼과 행 수가 담긴다 (조용한 0건으로 끝나지 않는다) |
| 7-13 | 컬럼 화이트리스트 | `column`에 `content`/`detail_json` 외 값 지정 | `ValueError`로 거부한다 (컬럼명은 SQL에 그대로 들어가므로 조회 전에 막는다) |

---

## 성공 기준 대비

[service.md](service.md) 「성공 기준」 8개 항목과 위 체크리스트의 대응.

| # | 기준 | 대응 케이스 |
|---|---|---|
| 1 | 단발 실행 | `python -m src.main "<요청>"`이 서버 없이 종료 (별도 확인) |
| 2 | 도구 선택 정확성 | [evaluation/test_queries.csv](evaluation/test_queries.csv) 15건의 `expected_tool` |
| 3 | 탐지 정확도 | 2-1, 2-2, 2-9, 2-10, 7-4, 7-5 |
| 4 | 내결함성 | 1-9, 2-12, 4-3, 4-4 |
| 5 | 데이터 무결성 | 3-1 ~ 3-7, 5-8 |
| 6 | 즉시성 | 6-1, 6-3 |
| 7 | 재현성 | 4-7 |
| 8 | 전체 통과율 90% | 위 73건 전체 |

## 현재까지 확인된 항목

로컬 HTTP 서버(5개 위치에 데이터를 심고 새 탭 링크 포함)로 `record_session`을 돌리고,
이관된 collect 2082행으로 `detect_matches`·`suggest_patterns`를 돌려 아래를 확인했다:

**1-1, 1-2, 1-3, 1-4, 1-5, 1-6, 1-9, 1-10, 1-13, 2-1, 2-2, 2-7, 2-9, 2-10, 2-11, 2-12, 3-1, 3-3, 3-7, 4-3, 4-8, 5-1, 5-2, 5-3, 5-12, 5-13, 5-14, 6-1, 6-2, 6-6, 7-1, 7-2, 7-3, 7-4, 7-5, 7-6, 7-7, 7-8, 7-9, 7-10, 7-11, 7-12, 7-13** (43 / 73)

나머지 항목과 정식 판정 결과는 [evaluation/report.md](evaluation/report.md)에 기록한다.
성공 기준 1·2(에이전트 경로)는 아직 미실행이다. `.env`의 `BEDROCK_MODEL_ID`·`AWS_REGION`은 채워져 있고 Bedrock 호출까지 도달하지만, 현재 Bedrock 일일 토큰 쿼터(`ThrottlingException: Too many tokens per day`)에 걸려 응답을 받지 못한 상태다.
