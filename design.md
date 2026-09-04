# 세부 설계

[service.md](service.md)의 기능 정의와 [CLAUDE.md](CLAUDE.md)의 프로젝트 규칙
(Python + LangChain/LangGraph + Bedrock + `create_agent`, ReAct/LangGraph 실습 목적)을
기준으로 한 설계. HTTP 서버·RAG(임베딩 검색)는 사용하지 않는다 — CLI로 한 번 실행하고
종료하는 온디맨드 도구이며, `retriever.py`는 저장된 매칭을 SQLite에서 조건으로 걸러오는
단순 조회 헬퍼일 뿐이다.

## 1. 디렉토리 구조

`CLAUDE.md`가 고정한 구조(`src/main.py`, `src/agent.py`, `src/tools.py`, `src/retriever.py`, `data/`, `evaluation/`)는
이름·위치를 바꾸지 않는다. "파일 하나에 한 가지 역할만 둔다" 규칙을 지키기 위해,
브라우저 제어/매칭/저장/알림처럼 `tools.py`·`retriever.py`가 내부적으로 쓰는 로직은
`src/` 밑에 언더스코어 접두사 헬퍼 모듈로 분리한다 (제출 규약 대상이 아닌 내부 구현).

```
my-pjt/
├── CLAUDE.md
├── service.md
├── verification.md
├── design.md
├── requirements.txt
├── .env.example
├── src/
│   ├── main.py                  # CLI 진입점: 자연어 요청 1개를 받아 에이전트 실행
│   ├── agent.py                 # 메인 에이전트 그래프 (LangGraph ReAct 루프, create_agent 활용)
│   ├── tools.py                 # 도메인 도구 4개: detect_matches / query_matches / suggest_patterns / collect_traffic
│   ├── retriever.py             # SQLite 조회 헬퍼 (query_matches가 내부적으로 사용, RAG/임베딩 아님)
│   ├── _browser.py              # (내부) Playwright 세션, 페이지 방문 수집, 트래픽 기록
│   ├── _matcher.py              # (내부) 정규식 패턴 매칭 (정규식 → 값)
│   ├── _induce.py               # (내부) 매칭 값에서 정규식 후보 귀납 (값 → 정규식)
│   ├── _storage.py              # (내부) SQLite 연결/저장
│   └── _notify.py               # (내부) 매칭 즉시 출력, 추적 출력, 수집 종료 대기
├── data/                        # 사용한 문서와 데이터
│   ├── patterns.json            # 정규식 패턴 + 실행 설정
│   └── scan.db                  # SQLite 저장소 (scans/matches/collect, gitignore 대상)
└── evaluation/
    ├── test_queries.csv         # 평가용 자연어 질의 목록
    └── report.md                # 평가 리포트
```

## 2. 수집과 탐지의 분리

점검 대상 URL 목록 파일은 쓰지 않는다. 대신 두 단계로 나눈다.

```
collect_traffic   창을 띄워 사람이 직접 둘러본다 → 오간 데이터를 collect 테이블에 저장
     │
detect_matches          collect 테이블을 대상으로 정규식 탐지 (브라우저 없이, 몇 번이든)
```

- 사람이 직접 이동하므로 **로그인해야 보이는 페이지도 수집된다.** 목록 파일 방식으로는
  세션이 없어 접근할 수 없던 부분이다
- 탐지가 저장된 데이터를 보므로 **브라우저·네트워크 없이 반복 실행**할 수 있다.
  패턴을 고쳐 다시 검사할 때 사이트를 또 방문하지 않는다
- 같은 수집 데이터에 같은 `patterns.json`을 적용하면 결과가 항상 같다 (재현성)

대신 **수집 시점 이후의 변화는 보지 못한다.** 사이트가 바뀐 뒤를 보려면 다시 수집해야 한다.

## 3. `data/patterns.json` — 설정

```json
{
  "patterns": [
    { "name": "jwt-token", "regex": "eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+" },
    { "name": "custom-secret", "regex": "sk_live_[A-Za-z0-9]{24,}" }
  ],
  "targets": {
    "network": { "headers": true, "body": true, "requestBody": true, "cookies": true },
    "console": true
  },
  "filters": { "methods": ["POST"] },
  "browser": { "chromePath": null }
}
```

수집 대상(`targets.network`):

| 키 | 수집 항목 | location |
|---|---|---|
| `headers` | 요청·응답 헤더 | `header` |
| `body` | **응답** 바디 (들어오는 데이터) | `body` |
| `requestBody` | **요청** 페이로드 = POST 본문 (나가는 데이터) | `request_body` |
| `cookies` | 컨텍스트 쿠키 | `cookie` |

`targets.console`은 콘솔 로그·JS 에러를 `console` 위치로 수집한다.

`filters.methods` (선택):
- 지정하면 `detail.method`가 그 목록에 있는 수집 항목만 매칭한다. 대소문자는 무시한다
- `method`는 **요청** 항목(요청 헤더, 요청 페이로드)에만 붙으므로, 필터를 켜면
  응답 헤더·응답 바디·쿠키·콘솔은 함께 제외된다. "나가는 데이터만 검사"할 때 쓴다
- **값을 지정하지 않으면 수집된 전부를 매칭한다 (기본).** 네 가지가 모두 같은 뜻이다 —
  `filters` 키 자체가 없거나, `filters: {}`이거나, `methods: []`이거나, `methods: null`.
  필터를 잠시 끌 때 키를 지웠다 되살리는 것보다 `[]`로 비우는 편이 편하기 때문이다

검증 규칙:
- `patterns[].name` 중복 불가, `regex`는 로드 시 `re.compile(...)`로 컴파일 검증 (실패 시 이름과 함께 에러)
- `targets`에 켜진 수집 대상이 하나도 없으면 스캔 시작 전에 실패한다
- `filters.methods`는 문자열 배열이어야 한다. 문자열이나 숫자를 그대로 넣으면 실패한다
  (오타를 조용히 넘기면 필터가 통째로 무력화되기 때문). 빈 배열은 "제한 없음"으로 읽는다
- `browser.chromePath`가 `null`이면 Playwright 관리 Chromium 사용, 문자열이면 그 경로를 `executable_path`로 사용

## 4. SQLite 스키마 (`src/_storage.py`가 관리)

```sql
CREATE TABLE IF NOT EXISTS scans (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source        TEXT NOT NULL,   -- 'data/scan.db#collect'
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  chunks_total   INTEGER NOT NULL,
  chunks_scanned INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'running'  -- running | completed | failed
);

CREATE TABLE IF NOT EXISTS matches (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id       INTEGER NOT NULL REFERENCES scans(id),
  pattern_name  TEXT NOT NULL,
  matched_value TEXT NOT NULL,
  location      TEXT NOT NULL,   -- header | body | request_body | cookie | console
  url           TEXT NOT NULL,
  detail_json   TEXT,
  matched_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collect (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  url           TEXT NOT NULL,
  location      TEXT NOT NULL,   -- header | body | request_body | cookie | console
  content       TEXT NOT NULL,   -- 그 위치에서 수집한 텍스트 원본
  detail_json   TEXT,            -- direction/method/status/kind 등 부가정보
  collected_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_matches_scan_id      ON matches(scan_id);
CREATE INDEX IF NOT EXISTS idx_matches_pattern_name ON matches(pattern_name);
CREATE INDEX IF NOT EXISTS idx_matches_url          ON matches(url);
CREATE INDEX IF NOT EXISTS idx_matches_matched_at   ON matches(matched_at);

CREATE INDEX IF NOT EXISTS idx_collect_url          ON collect(url);
CREATE INDEX IF NOT EXISTS idx_collect_location     ON collect(location);
CREATE INDEX IF NOT EXISTS idx_collect_collected_at ON collect(collected_at);
```

`collect`는 `collect_traffic`이 모아 둔 **정규식을 거치지 않은 원본**이다. 컬럼 구성이
`_browser`의 `emit(위치, 텍스트, URL, 부가정보)`과 같은 모양이라, 수집 경로와 저장 형식이
어긋날 수 없고 `detect_matches`이 그대로 되돌려 검사한다. `location`은 `matches`와 같은 어휘를 쓴다.

`matches`가 "패턴에 걸린 것"이라면 `collect`는 "오간 것 전부"이므로, 쿠키·`Authorization`
헤더·POST 본문의 자격증명이 그대로 담긴다 — **`matches`보다 민감하다.**

**주의:** `CREATE TABLE IF NOT EXISTS`는 이미 있는 테이블의 컬럼을 바꾸지 않는다.
스키마를 고쳐도 기존 `scan.db`에는 반영되지 않아 실행 시점에 `OperationalError`로
드러난다. 컬럼을 변경했으면 해당 테이블을 지우고 다시 만들어야 한다.

## 5. `src/retriever.py` — SQLite 조회 헬퍼

```python
def find_matches(
    pattern_name: str | None = None,
    url_substring: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    scan_id: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """조건에 맞는 매칭 기록을 data/scan.db에서 그대로 조회해 반환한다.

    임베딩이나 의미 기반 검색을 하지 않는다 — 전달된 조건으로 SQL WHERE 절을 구성해
    filtering만 수행하는 단순 조회 함수다. 조건을 하나도 주지 않으면 최근 limit건을 반환한다.
    """
```

함께 두는 조회 함수들 (모두 상태를 바꾸지 않는다):

| 함수 | 용도 |
|---|---|
| `find_matches(...)` | 조건별 매칭 조회. `tools.query_matches()`가 그대로 감싼다 |
| `find_distinct_values(...)` | 중복 없는 `matched_value` + 빈도. 정규식 귀납의 양성 표본 |
| `find_context_texts(...)` | 정규식이 적용된 적 없는 부수 텍스트(url, detail). 후보 검증 코퍼스 |
| `find_collected(limit, location)` | `collect` 테이블의 원본 관측 데이터. `detect_matches`의 탐지 대상 |
| `find_collect_column(column, contains, location, limit)` | `collect`의 지정 텍스트 컬럼 원문. 컬럼·키를 지목한 분석 요청의 조회 |
| `count_collect_column(column, contains)` | 그 문자열을 포함한 행 수. "다른 컬럼엔 있나" 확인용 |

`find_collected`는 `detail_json` 컬럼을 dict로 파싱해 **`detail` 키로 바꿔** 넘긴다
(컬럼명과 반환 키가 다르다). 반면 `find_collect_column`은 지정한 컬럼 원문을 `text`로
그대로 넘긴다 — 파싱 전 텍스트를 봐야 하는 귀납의 입력이기 때문이다.

컬럼명은 SQL 파라미터로 넘길 수 없어 문자열로 끼워 넣으므로, `COLLECT_TEXT_COLUMNS`
화이트리스트(`content`, `detail_json`)에 없으면 조회 전에 `ValueError`로 막는다.

`location`을 주면 그 위치만 **SQL 단계에서** 걸러 온다. 특정 위치(예: `request_body`)는
전체의 일부이므로, 파이썬에서 걸러내면 `limit`이 먼저 잘려 원하는 행을 놓친다 —
실제로 요청 본문 14건 중 6건만 분석되던 버그의 원인이었다.

- 이 파일은 순수 조회 로직만 담당 (상태 변경 없음)

## 6. `src/tools.py` — 도메인 도구

```python
def detect_matches() -> dict:
    """collect 테이블에 모아 둔 트래픽에서 등록된 정규식 패턴을 탐지한다.

    collect_traffic이 수집해 둔 원본 관측 데이터를 대상으로 하므로 브라우저를 띄우지
    않고 네트워크도 쓰지 않는다. 수집 당시의 상태(로그인 후 페이지 포함)가 그대로
    검사되고, 같은 데이터로 몇 번 돌려도 결과가 같다.

    내부적으로 다음을 고정 순서로 실행한다:
    1) data/patterns.json 로드 및 검증
    2) collect 테이블을 저장 순서대로 읽어 filters를 통과한 것만 정규식으로 매칭
    3) 매칭 발생 즉시 콘솔에 출력
    4) scans/matches를 data/scan.db에 저장

    반환값은 scan_id, source, chunks_total, chunks_scanned, status,
    매칭 건수 요약, method_filter를 포함한다.
    """


def collect_traffic(start_url: str | None = None) -> dict:
    """브라우저를 띄워 사용자가 직접 둘러보는 동안 오간 데이터를 수집해 저장한다.

    내부적으로 다음을 고정 순서로 실행한다:
    1) 창을 띄우고(start_url이 있으면 그 페이지로) 오가는 데이터를 관찰
    2) 사용자가 터미널에서 Enter를 누를 때까지 대기
    3) 관측 덩어리마다 위치/텍스트/URL/부가정보를 collect 테이블에 즉시 저장

    수집 위치는 patterns.json의 targets 설정이 정한다. 정규식 매칭을 거치지 않은
    원본을 그대로 남기며, 이후 detect_matches가 이 데이터를 대상으로 탐지한다.
    """


def query_matches(
    pattern_name: str | None = None,
    url_substring: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    scan_id: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """저장된 매칭 기록을 조건에 맞게 조회한다 (src.retriever.find_matches를 그대로 호출).

    pattern_name/url_substring/date_from/date_to/scan_id는 모두 선택 조건이며,
    지정하지 않으면 해당 조건은 적용하지 않는다.
    """
```

```python
def suggest_patterns(
    pattern_name: str | None = None,
    scan_id: int | None = None,
    min_cluster: int = 3,
    limit: int = 1000,
    source: str = "matches",
    column: str | None = None,
    json_key: str | None = None,
) -> dict:
    """정규식 후보를 제안한다. 분석 대상은 source로 고른다.

    - source="matches"(기본): 이미 패턴에 걸린 값들을 분석해 더 좁은 후보를 만든다.
    - source="collect": collect 테이블을 분석해 새 후보를 만든다.
      아직 어떤 패턴에도 안 걸린 값에서 패턴을 찾을 때 쓴다.

    요청이 컬럼(column)이나 JSON 키(json_key)를 지목하면 그것을 조건으로 collect
    테이블을 먼저 SQL로 조회하고, 돌아온 행에만 귀납을 돌린다. 둘 중 하나라도
    주어지면 source는 "collect"로 본다.

    data/patterns.json을 변경하지 않는다 — 제안만 돌려주고 채택은 사람이 판단한다.
    """
```

#### `source="matches"` — 기존 패턴을 좁히는 경로

1. `retriever.find_distinct_values()` — 중복 없는 매칭 값과 빈도 (양성 표본)
2. `retriever.find_context_texts()` — 정규식이 적용된 적 없는 부수 텍스트 (검증 코퍼스)
3. `_induce.cluster_by_shape()` → `_induce.induce_regex()` — 군집화 후 strict/open/bounded 3변형 귀납
4. `_induce.evaluate_candidate()` — coverage / gained / lost / 합성 음성 차단율 계산
5. 채택 게이트 통과분만 정렬해 반환

**채택 게이트**: 기존 패턴이 잡던 값을 놓치지 않을 것(`lost` 없음), 컴파일될 것,
중첩 수량자가 없을 것(ReDoS). 정렬은 `gained` 내림차순 → 음성 차단율 내림차순 → 길이 오름차순.

#### `source="collect"` — 아직 안 잡힌 값에서 새 패턴을 찾는 경로

1. `retriever.find_collect_column(column, contains=json_key, location, limit)` — **조회가 먼저다**
2. `_induce.values_by_key()` — 조회된 텍스트에서 **같은 키의 값끼리** 모은다
3. 키별로 `_induce.induce_regex()` → `evaluate_candidate()`
4. `support`(값 종류 수) 내림차순 → `tightness` → 길이 순으로 정렬해 반환

**요청이 지목한 조건은 WHERE 절로 내린다.** "collect 테이블 content 컬럼에서 sectionId를
찾는 패턴"처럼 컬럼·키를 지목한 요청은 `column`/`json_key`로 받아 조회 조건으로 쓰고,
돌아온 행에만 귀납을 돌린다. 파이썬에서 걸러내면 `limit`이 먼저 잘려 행을 놓치고,
"그 컬럼엔 없다"는 사실도 후보 목록에 묻혀 드러나지 않는다.

- 컬럼을 지목하지 않으면 기존대로 요청 본문(`request_body`)의 `content`만 본다.
  지목하면 위치를 제한하지 않는다 — `detail_json`에는 요청 본문이 아닌 행도 있다
- 키를 지목한 요청은 후보를 상위 몇 개로 자르지 않는다. 값 종류가 적어 `support`가
  낮은 키는 자르면 정작 요청받은 키가 잘려 나간다 (`sectionId`는 값이 3종뿐이라
  전체 36개 후보 중 30위였고, 상위 20개 컷에 걸려 사라졌다)
- 조회가 0건이면 후보 대신 **어느 컬럼에 있는지**를 `found_in_other_columns`로 돌려준다.
  조용한 0건이 "그런 값이 없다"로 오해되는 것을 막는다 — `detail_json`에는
  `direction`/`method`밖에 없어 `sectionId`를 거기서 찾으면 항상 0건이다

**본문을 통째로 귀납하지 않는다.** 2600자 JSON을 그대로 넣으면 의미 있는 정규식이
나오지 않는다. 반면 여러 요청의 같은 키(예: `bizCd`) 값들은 형식이 같을 가능성이 높아
귀납 입력으로 적합하다. 서로 다른 값이 `min_cluster` 미만인 키는 과적합하므로 건너뛴다.

**채택 게이트가 다르다.** 기준이 될 기존 정규식이 없어 회귀(`lost`)를 판정할 수 없으므로
컴파일 가능·ReDoS 없음·커버리지만 본다. 이 한계를 반환값 `note`에 적는다.

두 경로 모두 반환값에 **`source` 필드**를 넣는다. `matches` 경로의 `corpus_size`가
`collect` 테이블의 데이터 양으로 오해된 적이 있어, 어느 테이블을 분석했는지 명시한다.
`source`가 두 값 외이면 `ValueError`로 거부한다.

`tightness`는 **같은 귀납 계열 안에서만** 비교 가능하다(strict < bounded < open). 무한 반복을
상수로 근사하므로 구조가 다른 정규식끼리 비교하면 오해를 부른다 — 채택 판단은 `coverage`와
음성 차단율로 한다.

### 수집과 탐지가 나뉜 이유

```
collect_traffic ──> collect 테이블 ──> detect_matches ──> matches 테이블
  (브라우저, 1회)     (원본 보관)      (브라우저 없음, 반복)   (패턴에 걸린 것)
```

- **탐지를 몇 번이든 다시 돌릴 수 있다.** 패턴을 고쳐 재검사할 때 사이트를 또 방문하지
  않으므로 빠르고, 대상 사이트에 부담을 주지 않는다
- **로그인 후 페이지가 검사 대상에 들어온다.** 사람이 직접 이동해 수집하므로, 세션이
  없어 접근 못 하던 페이지의 데이터도 남는다
- `filters.methods`는 탐지 단계에 걸린다 — 수집은 전부 해 두고 검사 범위만 좁히므로,
  필터를 바꿔 다시 검사해도 데이터를 다시 모을 필요가 없다
- `collect`가 비어 있으면 `ValueError`로 사유와 다음 할 일(`collect_traffic` 먼저 실행)을 알린다

### `collect_traffic`의 수집 세션

- 종료 신호는 `_notify.recording_stopper()`가 만드는 판정 함수로 받는다.
  `input()`으로 메인 흐름을 막으면 **Playwright가 이벤트를 처리하지 못해 새 탭·팝업이
  "디버거 붙기 대기" 상태로 정지한 채 페이지가 로딩되지 않는다.** 그래서 `_pump_until()`이
  짧게 반복 대기하며 이벤트 루프를 돌린다
- 새 탭은 `framenavigated` 핸들러가 붙기 전에 첫 이동을 끝낼 수 있어 현재 위치도 함께 남긴다
- 사용자가 창을 먼저 닫으면 그것도 종료 신호로 본다. 컨텍스트 기본 타임아웃을 짧게 줄여
  30초 기다리지 않고 알아챈다
- **로그인 세션(`storage_state`)은 저장하지 않는다.** 구현했다가 제거했다 —
  컨텍스트의 모든 쿠키가 평문 파일 하나에 모여, 점검 대상과 무관한 메일·금융 세션까지
  함께 노출되기 때문이다. 그 대가로 로그인 후에만 보이는 페이지는 재현되지 않는다

- 이 파일이 갖는 "한 가지 역할"은 **에이전트에 노출되는 도구 함수 정의**이며,
  실제 브라우저 제어/매칭/저장/알림/조회 구현은 `_browser.py`/`_matcher.py`/`_storage.py`/`_notify.py`/`retriever.py`에 위임한다.

## 7. `src/agent.py` — 메인 에이전트 그래프

```python
from langchain.agents import create_agent
from langchain_aws import ChatBedrockConverse
import os

def build_agent():
    """Bedrock 모델과 도구를 연결한 패턴 탐지 에이전트를 생성한다."""
    from src.tools import query_matches, detect_matches

    model = ChatBedrockConverse(
        model=_required_env("BEDROCK_MODEL_ID"),
        region_name=_required_env("AWS_REGION"),
    )

    return create_agent(
        model=model,
        tools=[detect_matches, query_matches],
        system_prompt=SYSTEM_PROMPT,
    )
```

- `SYSTEM_PROMPT`는 모듈 상수로 두며, 요청을 **수집·탐지·분석 세 유형**으로 나눠 유형별 규칙만 담는다. 탐지 요약에는 **검사한 덩어리 수·매칭 건수·패턴별/위치별 분포**를 넣고, `method_filter`가 걸려 있으면 검사 범위가 좁았다는 사실을 함께 밝히게 한다 (매칭 0건을 "유출 없음"으로 요약하는 것을 막는다). 값 자체는 `[MATCH]` 줄과 DB에 그대로 남으므로([verification.md](verification.md) 6-5) 요약에서 따로 가리지 않는다
- 분석 요청이 컬럼이나 JSON 키를 지목하면 **`column`/`json_key`로 그대로 넘기게** 한다. LLM이 임의로 다른 컬럼으로 바꾸면 "그 컬럼엔 없다"는 조회 결과 자체가 사라진다
- 패턴 개선 요청에는 `suggest_patterns`를 호출하되, **도구가 돌려준 `candidates` 밖의 정규식을 새로 지어내지 말 것**을 명시한다. LLM은 후보를 고르고·이름 붙이고·위험도를 설명하는 편집자 역할이며, 정규식의 저자가 아니다 (검증 불가능한 환각이 탐지 규칙이 되는 것을 막는다)
- `_required_env(name)`로 필수 환경변수를 읽어, 값이 없으면 무엇이 빠졌는지 알리는 `RuntimeError`를 던진다 (`main.py`가 이를 잡아 `[ERROR]`로 출력)
- ReAct 루프: LLM이 요청을 보고 `detect_matches`/`query_matches` 중 무엇을, 몇 번 호출할지 스스로 판단 (`create_agent`가 이 루프를 LangGraph 그래프로 컴파일)
- 도구 내부(수집→탐지→저장, 조회)의 순서는 고정이며 LLM이 그 세부 단계를 정하지 않음

## 8. `src/main.py` — 실행 진입점

### 준비 (최초 1회)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (bash: source .venv/Scripts/activate)
pip install -r requirements.txt
playwright install chromium      # 브라우저 바이너리는 pip이 받지 않는다 — 없으면 detect_matches가 실패
copy .env.example .env           # 복사 후 BEDROCK_MODEL_ID / AWS_REGION 을 채운다
```

### 실행 방법

```bash
python -m src.main "<자연어 요청>"
```

예시:
```bash
python -m src.main "url 수집"                              # 창을 띄워 직접 둘러본다
python -m src.main "수집된 트래픽에서 개인정보 유출 있는지 확인해줘"
python -m src.main "최근 jwt-token 패턴 매칭 결과 보여줘"
```

인자 없이 실행하면 대화형(REPL) 모드로 진입한다.

### 입력

- 사용자의 자연어 문자열 1개

### 출력 (두 단계)

1. **즉시 출력 (도구 실행 중)**: `detect_matches` 실행 중 매칭 발생 시 다음 형태로 즉시 콘솔 출력
   ```
   [MATCH] pattern=origin_body|location=body|matched_value="origin"|url=https://www.naver.com/|context=..."utf-8"> <meta name="Referrer" content="origin"> <meta http-equiv="X-UA-Compat...|detail={'page_url': 'https://www.naver.com/', 'status': 200}
   ```
   필드는 `|`로 구분한다. `url`은 매칭된 값이 아니라 **값이 발견된 리소스 URL**이고,
   실제로 패턴에 걸린 값은 `matched_value`다 (`detail.page_url`은 방문한 페이지).
   `matched_value`는 원본 그대로 싣고, `context`와 `detail`은 각각 200자까지 싣는다
   ([verification.md](verification.md) 6-2, 6-5)

   `context`는 매칭 자리 앞뒤 40자(`_matcher.CONTEXT_CHARS`)로, `matched_value`만으로는
   그 값이 어떤 문장 안에 있었는지 알 수 없어서 넣는다 — 위 예에서 `"origin"`이 유출이
   아니라 HTML 메타 태그의 값이라는 것이 문맥으로 드러난다. `detail`에 함께 저장하되
   출력에서는 꺼내어 별도 필드로 낸다. `detail` 안에 두면 `page_url`이 길 때 200자
   제한에 잘려 사라지기 때문이다 ([verification.md](verification.md) 3-7, 6-6)
2. **추적 출력 (디버깅용, 기본 꺼짐)**: `SCAN_TRACE=1`이면 `visit`이 넘긴 수집 덩어리를
   매칭 여부와 함께 표준에러로 출력한다. 매칭 0건일 때 **수집이 안 된 것**인지
   **패턴이 안 맞은 것**인지 구분하기 위한 것이다. 수집 원본이 그대로 찍히므로 기본은 꺼져 있다
   ```
   [DATA] location=body len=15234 matched=0 url=https://www.naver.com/main.js
          detail={'page_url': 'https://www.naver.com/', 'status': 200}
          "use strict";(self.webpackChunk_N_E=...
   [VISIT] https://www.naver.com/ - 수집 덩어리 633건, 매칭 0건
   ```
3. **최종 응답 (에이전트)**: 도구 실행이 끝난 뒤 LLM이 결과를 요약한 자연어 텍스트를 표준출력에 출력
   ```
   수집된 2082건을 검사한 결과, jwt-token 패턴이 2건(헤더 1건, 콘솔 1건) 발견되었습니다.
   상세 내역은 scan_id=7로 조회할 수 있습니다.
   ```

서버 프로세스 없이 한 번 실행되고 응답 후 종료되는 단발성 CLI 프로세스다.

## 9. `evaluation/` — 평가

### `test_queries.csv`

| 컬럼 | 설명 |
|---|---|
| `id` | 테스트 케이스 번호 |
| `question` | `python -m src.main`에 넘길 자연어 요청 |
| `expected_tool` | 이 요청이 호출해야 하는 도구 (`detect_matches` / `query_matches`) |
| `expected_pattern` | 응답에 포함되길 기대하는 패턴 이름 (없으면 빈 값) |
| `notes` | 판정 기준 비고 |

예시 행:
```
1,"수집된 트래픽에서 개인정보 유출 있는지 확인해줘",detect_matches,jwt-token,"매칭 발생 시 [MATCH] 로그와 최종 요약에 모두 나와야 함"
2,"최근 jwt-token 매칭 결과 보여줘",query_matches,jwt-token,"재스캔 없이 query_matches만 호출해야 함"
```

### `report.md`

`test_queries.csv`를 실제로 실행한 결과를 [verification.md](verification.md)의 기능별 기준(수집/탐지/매칭기록/저장/조회/알림)에 대응시켜 Pass/Fail로 기록한다. 형식은 verification.md와 동일한 표 스타일을 재사용한다.

## 10. 검증 기준과의 매핑

| verification.md 항목 | 설계 대응 |
|---|---|
| 1-x 수집 | `src/_browser.py`(`record_session`), `collect` 테이블, `tools.collect_traffic()` |
| 2-x 탐지 | `src/_matcher.py`, `data/patterns.json`(`patterns`, `filters.methods`) |
| 3-x 매칭 기록 | `matches` 테이블 컬럼 구성 |
| 4-x 저장 | `src/_storage.py`, `scans`/`matches` 스키마 |
| 5-x 조회 | `src/retriever.py`(`find_matches`), `tools.query_matches()` |
| 6-x 알림 | `src/_notify.py` |
| 7-x 패턴 도출 | `src/_induce.py`, `retriever.find_distinct_values`/`find_context_texts`, `tools.suggest_patterns()` |
| 8-x 트래픽 수집 | `_browser.record_session()`, `_storage.save_collected()`, `collect` 테이블, `tools.collect_traffic()` |

## 11. 에러 처리 정책

- 수집 중 개별 요청을 읽지 못하면(리다이렉트로 사라진 응답 등) 그 덩어리만 건너뛴다
- `collect`가 비어 있으면 탐지를 시작하지 않고 `ValueError`로 사유를 알린다
- 종료 시 `scans.status`: 1건 이상 검사 → `completed`, 하나도 못 하면 → `failed`
- 도중에 예외가 나도 `finally`에서 `scans` 행을 마무리해 `running`으로 남기지 않는다

## 12. `.env` 항목 (`.env.example`)

```
# 이 파일을 .env로 복사해서 값을 채운다. .env는 커밋하지 않는다.

# Bedrock
# 계정/리전에서 실제 사용 가능한 ID는 아래 명령으로 확인한다:
#   aws bedrock list-inference-profiles --region <리전>
# 교차 리전 추론 프로파일은 "us." / "eu." / "apac." 접두사가 붙는다.
# 예: us.anthropic.claude-sonnet-4-5-20250929-v1:0
BEDROCK_MODEL_ID=
AWS_REGION=us-east-1

# AWS 자격증명은 .env가 아닌 AWS 기본 자격증명 체인
# (~/.aws/credentials, 환경변수, IAM 역할 등) 사용을 권장한다.
```

- 리전은 반드시 `AWS_REGION`이다. `AWS_DEFAULT_REGION`만 설정하면 `_required_env`가 실패한다

## 미정 (다음 단계에서 결정)

- ~~`requirements.txt` 의존성 버전 고정 방식~~ → 직접 의존성만 `==`로 정확히 고정하고
  전이 의존성은 pip 해석에 맡긴다 (Python 3.14 / Windows 기준 설치 검증 완료)
- `BEDROCK_MODEL_ID` 기본값 — 계정/리전마다 사용 가능한 모델이 달라
  `.env.example`에는 빈 값과 조회 명령(`aws bedrock list-inference-profiles`)만 두었다
