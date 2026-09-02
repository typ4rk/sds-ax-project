# 세부 설계

[service.md](service.md)의 기능 정의와 [claude.md](claude.md)의 프로젝트 규칙
(Python + LangChain/LangGraph + Bedrock + `create_agent`, ReAct/LangGraph 실습 목적)을
기준으로 한 설계. HTTP 서버·RAG(임베딩 검색)는 사용하지 않는다 — CLI로 한 번 실행하고
종료하는 온디맨드 도구이며, `retriever.py`는 저장된 매칭을 SQLite에서 조건으로 걸러오는
단순 조회 헬퍼일 뿐이다.

## 1. 디렉토리 구조

`claude.md`가 고정한 구조(`src/main.py`, `src/agent.py`, `src/tools.py`, `src/retriever.py`, `data/`, `evaluation/`)는
이름·위치를 바꾸지 않는다. "파일 하나에 한 가지 역할만 둔다" 규칙을 지키기 위해,
브라우저 제어/매칭/저장/알림처럼 `tools.py`·`retriever.py`가 내부적으로 쓰는 로직은
`src/` 밑에 언더스코어 접두사 헬퍼 모듈로 분리한다 (제출 규약 대상이 아닌 내부 구현).

```
my-pjt/
├── claude.md
├── service.md
├── verification.md
├── design.md
├── requirements.txt
├── .env.example
├── src/
│   ├── main.py                  # CLI 진입점: 자연어 요청 1개를 받아 에이전트 실행
│   ├── agent.py                 # 메인 에이전트 그래프 (LangGraph ReAct 루프, create_agent 활용)
│   ├── tools.py                 # 도메인 도구: run_scan(스캔 실행), query_matches(저장된 매칭 조회)
│   ├── retriever.py             # SQLite 조회 헬퍼 (query_matches가 내부적으로 사용, RAG/임베딩 아님)
│   ├── _browser.py              # (내부) Playwright 세션 생성/종료, chromePath 처리
│   ├── _matcher.py              # (내부) 정규식 패턴 매칭
│   ├── _storage.py              # (내부) SQLite 연결/저장
│   └── _notify.py               # (내부) 매칭 즉시 콘솔 출력
├── data/                        # 사용한 문서와 데이터
│   ├── urls.txt                 # 점검 대상 URL 목록 (한 줄에 하나)
│   ├── patterns.json            # 정규식 패턴 + 실행 설정
│   └── scan.db                  # SQLite 저장소 (gitignore 대상)
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
    "network": { "headers": true, "body": true, "cookies": true },
    "console": true
  },
  "delayMs": 500,
  "browser": { "chromePath": null }
}
```

검증 규칙:
- `patterns[].name` 중복 불가, `regex`는 로드 시 `re.compile(...)`로 컴파일 검증 (실패 시 이름과 함께 에러)
- `browser.chromePath`가 `null`이면 Playwright 관리 Chromium 사용, 문자열이면 그 경로를 `executable_path`로 사용

## 4. SQLite 스키마 (`src/_storage.py`가 관리)

```sql
CREATE TABLE IF NOT EXISTS scans (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source        TEXT NOT NULL,   -- 'data/urls.txt'
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
  location      TEXT NOT NULL,   -- header | body | cookie | console
  url           TEXT NOT NULL,
  detail_json   TEXT,
  matched_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_matches_scan_id      ON matches(scan_id);
CREATE INDEX IF NOT EXISTS idx_matches_pattern_name ON matches(pattern_name);
CREATE INDEX IF NOT EXISTS idx_matches_url          ON matches(url);
CREATE INDEX IF NOT EXISTS idx_matches_matched_at   ON matches(matched_at);
```

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

- 이 파일은 순수 조회 로직만 담당 (상태 변경 없음)
- `tools.query_matches()`가 이 함수를 감싸 에이전트에 도구로 노출한다

## 6. `src/tools.py` — 도메인 도구

```python
def run_scan() -> dict:
    """data/urls.txt에 저장된 URL을 순서대로 방문하며 등록된 정규식 패턴을 탐지한다.

    내부적으로 다음을 고정 순서로 실행한다:
    1) data/patterns.json 로드 및 검증
    2) data/urls.txt의 각 URL을 순서대로 방문 (실패한 URL은 건너뛰고 계속)
    3) 방문마다 네트워크/콘솔 데이터를 수집하고 정규식으로 매칭
    4) 매칭 발생 즉시 콘솔에 출력
    5) scans/matches를 data/scan.db에 저장

    반환값은 에이전트가 요약에 쓸 수 있는 구조화된 결과(dict)이며,
    scan_id, urls_total, urls_visited, status, 매칭 건수 요약을 포함한다.
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

- `SYSTEM_PROMPT`는 모듈 상수로 두며, 위 요약 지침에 더해 **점검한 URL 수·매칭 건수·패턴별/위치별 분포·건너뛴 URL을 요약에 포함**하고 **매칭된 값 자체는 요약에 그대로 옮기지 않을 것**을 지시한다. 콘솔의 `[MATCH]` 줄은 값을 그대로 출력하지만([verification.md](verification.md) 6-6), LLM 요약은 건수·분포만 다루게 해 값이 두 번 노출되지 않게 한다
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
   [MATCH] pattern=test-any-url location=header url=https://ssl.pstatic.net/tveta/libs/glad/res/r.html matched_value=https://nid.naver.com detail={'page_url': 'https://nid.naver.com/nidlogin.login?mode=form', 'direction': 'request', 'method': 'GET'}
   ```
   `url`은 매칭된 값이 아니라 **값이 발견된 리소스 URL**이고, 실제로 패턴에 걸린 값은
   `matched_value`다 (`detail.page_url`은 방문한 페이지). `matched_value`는 원본 그대로,
   `detail`은 200자까지만 싣는다 ([verification.md](verification.md) 6-2, 6-6)
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
| 2-x 탐지 | `src/_matcher.py`, `data/patterns.json` |
| 3-x 매칭 기록 | `matches` 테이블 컬럼 구성 |
| 4-x 저장 | `src/_storage.py`, `scans`/`matches` 스키마 |
| 5-x 조회 | `src/retriever.py`(`find_matches`), `tools.query_matches()` |
| 6-x 알림 | `src/_notify.py` |

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
