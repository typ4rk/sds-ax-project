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
│   ├── tools.py                 # 도메인 도구 4개: run_scan / query_matches / suggest_patterns / collect_traffic
│   ├── retriever.py             # SQLite 조회 헬퍼 (query_matches가 내부적으로 사용, RAG/임베딩 아님)
│   ├── _browser.py              # (내부) Playwright 세션, 페이지 방문 수집, 트래픽 기록
│   ├── _matcher.py              # (내부) 정규식 패턴 매칭 (정규식 → 값)
│   ├── _induce.py               # (내부) 매칭 값에서 정규식 후보 귀납 (값 → 정규식)
│   ├── _storage.py              # (내부) SQLite 연결/저장
│   └── _notify.py               # (내부) 매칭 즉시 출력, 추적 출력, 수집 종료 대기
├── data/                        # 사용한 문서와 데이터
│   ├── urls.txt                 # 점검 대상 URL 목록 (한 줄에 하나)
│   ├── patterns.json            # 정규식 패턴 + 실행 설정
│   └── scan.db                  # SQLite 저장소 (scans/matches/collect, gitignore 대상)
└── evaluation/
    ├── test_queries.csv         # 평가용 자연어 질의 목록
    └── report.md                # 평가 리포트
```

## 2. `data/urls.txt` — 점검 대상

```
# 점검 대상 URL 목록 (한 줄에 하나)
# 빈 줄과 '#'로 시작하는 줄은 무시한다.

https://www.naver.com/
https://nid.naver.com/nidlogin.login?mode=form&url=https://www.naver.com/
```

- 한 줄에 URL 하나. 빈 줄/`#`로 시작하는 줄은 무시
- `tools.run_scan()`이 이 파일을 순서대로 읽어 방문(trace)한다 (도메인 크롤링 없음)
- 개별 URL 방문 실패 시 해당 URL만 건너뛰고 다음 URL 계속 진행

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
  "delayMs": 500,
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
- `delayMs`는 0 이상의 숫자여야 한다
- `browser.chromePath`가 `null`이면 Playwright 관리 Chromium 사용, 문자열이면 그 경로를 `executable_path`로 사용

## 4. SQLite 스키마 (`src/_storage.py`가 관리)

```sql
CREATE TABLE IF NOT EXISTS scans (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source        TEXT NOT NULL,   -- 'data\urls.txt' | 'data/scan.db#collect'
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  urls_total    INTEGER NOT NULL,
  urls_visited  INTEGER NOT NULL DEFAULT 0,
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
  method        TEXT NOT NULL,
  headers_json  TEXT,            -- 요청 헤더 dict를 JSON 문자열로
  body          TEXT,            -- 요청 페이로드. 본문 없는 요청(GET 등)은 NULL
  time          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_matches_scan_id      ON matches(scan_id);
CREATE INDEX IF NOT EXISTS idx_matches_pattern_name ON matches(pattern_name);
CREATE INDEX IF NOT EXISTS idx_matches_url          ON matches(url);
CREATE INDEX IF NOT EXISTS idx_matches_matched_at   ON matches(matched_at);

CREATE INDEX IF NOT EXISTS idx_collect_url          ON collect(url);
CREATE INDEX IF NOT EXISTS idx_collect_time         ON collect(time);
```

`collect`는 `collect_traffic`이 모아 둔 **정규식을 거치지 않은 원본 요청**이다.
`matches`가 "패턴에 걸린 것"이라면 `collect`는 "오간 것 전부"이므로, 쿠키·
`Authorization` 헤더·POST 본문의 자격증명이 그대로 담긴다 — `matches`보다 민감하다.

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
| `find_collected(limit)` | `collect` 테이블의 원본 요청. `urls.txt` 없이 탐지할 때의 입력 |

`find_collected`는 `headers_json` 컬럼을 dict로 파싱해 **`headers` 키로 바꿔** 넘긴다.
호출하는 쪽은 `headers_json`이 아니라 `headers`를 봐야 한다 (컬럼명과 반환 키가 다르다).

- 이 파일은 순수 조회 로직만 담당 (상태 변경 없음)

## 6. `src/tools.py` — 도메인 도구

```python
def run_scan() -> dict:
    """등록된 정규식 패턴을 탐지한다. 대상은 data/urls.txt 유무로 갈린다.

    - urls.txt가 있으면: 그 URL을 순서대로 브라우저로 방문하며 탐지한다(기존 동작).
    - urls.txt가 없으면: collect_traffic이 scan.db의 collect 테이블에 모아 둔
      요청 트래픽을 대상으로 탐지한다. 브라우저를 띄우지 않으므로 네트워크가 필요 없고,
      로그인해야 보이던 페이지의 트래픽도 수집 당시 상태 그대로 검사된다.

    두 경로 모두 patterns.json 로드·검증 → 필터 → 매칭 → 즉시 출력 → scan.db 저장
    순서를 따르며, scans 행의 source로 어느 대상을 썼는지 남긴다.

    반환값은 scan_id, source, urls_total, urls_visited, status, 매칭 건수 요약,
    method_filter를 포함한다.
    """


def collect_traffic(start_url: str | None = None) -> dict:
    """브라우저를 띄워 사용자가 직접 둘러보는 동안 오간 요청 트래픽을 수집해 저장한다.

    내부적으로 다음을 고정 순서로 실행한다:
    1) 창을 띄우고(start_url이 있으면 그 페이지로) 브라우저가 보낸 요청을 모두 관찰
    2) 사용자가 터미널에서 Enter를 누를 때까지 대기
    3) 요청마다 url/method/헤더/본문을 data/scan.db의 collect 테이블에 즉시 저장

    urls.txt를 손으로 채우는 대신 실제 브라우징을 기록해 점검 대상을 만드는 도구다.
    urls.txt를 변경하지 않는다.
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
) -> dict:
    """저장된 매칭 값의 문자 구조를 분석해 더 정확한 정규식 후보를 제안한다.

    임베딩을 쓰지 않는다 — 값을 문자 클래스 시그니처로 정규화해 군집화하고, 군집의
    공통 접두/접미를 앵커로 고정한 뒤 가변부만 일반화해 후보를 조립한다. 그런 다음
    정규식이 적용된 적 없는 부수 텍스트(url, detail)에 돌려 추가 탐지와 회귀를 센다.

    매칭이 0건인 엄격한 패턴에는 완화 사다리를 돌려 어느 축(수량자/문자클래스/구분자/
    리터럴/스킴)이 병목인지 함께 보고한다.

    data/patterns.json을 변경하지 않는다 — 제안만 돌려주고 채택은 사람이 판단한다.
    """
```

`suggest_patterns`의 고정 순서:

1. `retriever.find_distinct_values()` — 중복 없는 매칭 값과 빈도 (양성 표본)
2. `retriever.find_context_texts()` — 정규식이 적용된 적 없는 부수 텍스트 (검증 코퍼스)
3. `_induce.cluster_by_shape()` → `_induce.induce_regex()` — 군집화 후 strict/open/bounded 3변형 귀납
4. `_induce.evaluate_candidate()` — coverage / gained / lost / 합성 음성 차단율 계산
5. 채택 게이트 통과분만 정렬해 반환

**채택 게이트**: 기존 패턴이 잡던 값을 놓치지 않을 것(`lost` 없음), 컴파일될 것,
중첩 수량자가 없을 것(ReDoS). 정렬은 `gained` 내림차순 → 음성 차단율 내림차순 → 길이 오름차순.

`tightness`는 **같은 귀납 계열 안에서만** 비교 가능하다(strict < bounded < open). 무한 반복을
상수로 근사하므로 구조가 다른 정규식끼리 비교하면 오해를 부른다 — 채택 판단은 `coverage`와
음성 차단율로 한다.

### `run_scan`의 두 경로

```
urls.txt 있음 ──> _scan_by_visiting()  브라우저로 방문        source = data\urls.txt
urls.txt 없음 ──> _scan_collected()    collect 테이블 재검사   source = data/scan.db#collect
                        │
                  둘 다 _record_chunk() 공유
                  (필터 → 매칭 → 즉시 출력 → 저장)
```

- 두 경로가 `_record_chunk()`를 공유하므로 **필터 적용과 저장 방식이 어긋날 수 없다.**
  `filters.methods`도 양쪽에 동일하게 걸린다 (collect 경로는 `detail.method`를 채운다)
- collect 경로의 위치 이름도 기존 것을 재사용한다 — 헤더는 `header`, 본문은 `request_body`.
  `detail`에는 필터용 `method`와 원본 추적용 `collect_id`가 들어간다
- 헤더 텍스트 형식(`이름: 값` 줄 목록)은 `_browser.headers_text()` 한 곳에만 정의한다.
  브라우저 수집과 collect 재검사가 형식이 갈리면 `(?mi)^origin:`처럼 줄 시작에 의존하는
  정규식이 한쪽에서만 동작한다
- `urls.txt`도 없고 `collect`도 비어 있으면 `ValueError`로 사유와 다음 할 일을 알린다

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
    from src.tools import query_matches, run_scan

    model = ChatBedrockConverse(
        model=_required_env("BEDROCK_MODEL_ID"),
        region_name=_required_env("AWS_REGION"),
    )

    return create_agent(
        model=model,
        tools=[run_scan, query_matches],
        system_prompt=SYSTEM_PROMPT,
    )
```

- `SYSTEM_PROMPT`는 모듈 상수로 두며, **점검한 URL 수·매칭 건수·패턴별/위치별 분포·건너뛴 URL을 요약에 포함**할 것을 지시한다. 값 자체는 `[MATCH]` 줄과 DB에 그대로 남으므로([verification.md](verification.md) 6-6) 요약에서 따로 가리지 않는다
- 패턴 개선 요청에는 `suggest_patterns`를 호출하되, **도구가 돌려준 `candidates` 밖의 정규식을 새로 지어내지 말 것**을 명시한다. LLM은 후보를 고르고·이름 붙이고·위험도를 설명하는 편집자 역할이며, 정규식의 저자가 아니다 (검증 불가능한 환각이 탐지 규칙이 되는 것을 막는다)
- `_required_env(name)`로 필수 환경변수를 읽어, 값이 없으면 무엇이 빠졌는지 알리는 `RuntimeError`를 던진다 (`main.py`가 이를 잡아 `[ERROR]`로 출력)
- ReAct 루프: LLM이 요청을 보고 `run_scan`/`query_matches` 중 무엇을, 몇 번 호출할지 스스로 판단 (`create_agent`가 이 루프를 LangGraph 그래프로 컴파일)
- 도구 내부(수집→탐지→저장, 조회)의 순서는 고정이며 LLM이 그 세부 단계를 정하지 않음

## 8. `src/main.py` — 실행 진입점

### 준비 (최초 1회)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (bash: source .venv/Scripts/activate)
pip install -r requirements.txt
playwright install chromium      # 브라우저 바이너리는 pip이 받지 않는다 — 없으면 run_scan이 실패
copy .env.example .env           # 복사 후 BEDROCK_MODEL_ID / AWS_REGION 을 채운다
```

### 실행 방법

```bash
python -m src.main "<자연어 요청>"
```

예시:
```bash
python -m src.main "urls.txt에 있는 사이트들 점검해서 토큰 유출 패턴 있는지 확인해줘"
python -m src.main "최근 jwt-token 패턴 매칭 결과 보여줘"
```

인자 없이 실행하면 대화형(REPL) 모드로 진입한다.

### 입력

- 사용자의 자연어 문자열 1개

### 출력 (두 단계)

1. **즉시 출력 (도구 실행 중)**: `run_scan` 실행 중 매칭 발생 시 다음 형태로 즉시 콘솔 출력
   ```
   [MATCH] pattern=origin_body|location=body|matched_value="origin"|url=https://www.naver.com/|context=..."utf-8"> <meta name="Referrer" content="origin"> <meta http-equiv="X-UA-Compat...|detail={'page_url': 'https://www.naver.com/', 'status': 200}
   ```
   필드는 `|`로 구분한다. `url`은 매칭된 값이 아니라 **값이 발견된 리소스 URL**이고,
   실제로 패턴에 걸린 값은 `matched_value`다 (`detail.page_url`은 방문한 페이지).
   `matched_value`는 원본 그대로 싣고, `context`와 `detail`은 각각 200자까지 싣는다
   ([verification.md](verification.md) 6-2, 6-6)

   `context`는 매칭 자리 앞뒤 40자(`_matcher.CONTEXT_CHARS`)로, `matched_value`만으로는
   그 값이 어떤 문장 안에 있었는지 알 수 없어서 넣는다 — 위 예에서 `"origin"`이 유출이
   아니라 HTML 메타 태그의 값이라는 것이 문맥으로 드러난다. `detail`에 함께 저장하되
   출력에서는 꺼내어 별도 필드로 낸다. `detail` 안에 두면 `page_url`이 길 때 200자
   제한에 잘려 사라지기 때문이다 ([verification.md](verification.md) 3-7, 6-7)
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
   urls.txt의 3개 URL을 점검한 결과, jwt-token 패턴이 2건(헤더 1건, 콘솔 1건) 발견되었습니다.
   상세 내역은 scan_id=7로 조회할 수 있습니다.
   ```

서버 프로세스 없이 한 번 실행되고 응답 후 종료되는 단발성 CLI 프로세스다.

## 9. `evaluation/` — 평가

### `test_queries.csv`

| 컬럼 | 설명 |
|---|---|
| `id` | 테스트 케이스 번호 |
| `question` | `python -m src.main`에 넘길 자연어 요청 |
| `expected_tool` | 이 요청이 호출해야 하는 도구 (`run_scan` / `query_matches`) |
| `expected_pattern` | 응답에 포함되길 기대하는 패턴 이름 (없으면 빈 값) |
| `notes` | 판정 기준 비고 |

예시 행:
```
1,"urls.txt 사이트들 점검해서 토큰 유출 있는지 확인해줘",run_scan,jwt-token,"매칭 발생 시 [MATCH] 로그와 최종 요약에 모두 나와야 함"
2,"최근 jwt-token 매칭 결과 보여줘",query_matches,jwt-token,"재스캔 없이 query_matches만 호출해야 함"
```

### `report.md`

`test_queries.csv`를 실제로 실행한 결과를 [verification.md](verification.md)의 기능별 기준(수집/탐지/매칭기록/저장/조회/알림)에 대응시켜 Pass/Fail로 기록한다. 형식은 verification.md와 동일한 표 스타일을 재사용한다.

## 10. 검증 기준과의 매핑

| verification.md 항목 | 설계 대응 |
|---|---|
| 1-x 수집 | `src/_browser.py`, `data/urls.txt`, `tools.run_scan()` |
| 2-x 탐지 | `src/_matcher.py`, `data/patterns.json`(`patterns`, `filters.methods`) |
| 3-x 매칭 기록 | `matches` 테이블 컬럼 구성 |
| 4-x 저장 | `src/_storage.py`, `scans`/`matches` 스키마 |
| 5-x 조회 | `src/retriever.py`(`find_matches`), `tools.query_matches()` |
| 6-x 알림 | `src/_notify.py` |
| 7-x 패턴 도출 | `src/_induce.py`, `retriever.find_distinct_values`/`find_context_texts`, `tools.suggest_patterns()` |
| 8-x 트래픽 수집 | `_browser.record_session()`, `_storage.save_collected()`, `collect` 테이블, `tools.collect_traffic()` |

## 11. 에러 처리 정책

- URL 방문 실패 시 해당 URL만 건너뛰고 계속 진행, `urls_visited`에는 미포함
- 콘솔에 `[SKIP] <url> - <에러 사유>` 출력
- 종료 시 `scans.status`: 1개 이상 방문 성공 → `completed`, 전부 실패 → `failed`

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
