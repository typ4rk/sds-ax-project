# 브라우저 트래픽 분석 Agent — 도구 안내

## 실행

```bash
python -m src.main "<자연어 요청>"     # 1회 실행
python -m src.main                    # 인자 없으면 대화형
```

준비가 안 됐으면 [design.md](design.md) 8절의 "준비 (최초 1회)"를 먼저 따른다
(`pip install -r requirements.txt` → `playwright install chromium` → `.env` 채우기).

## 도구 4개 한눈에

| 도구 | 한 줄 요약 | 브라우저 | DB |
|---|---|---|---|
| `run_scan` | `collect`에 모아 둔 트래픽에서 등록된 정규식을 탐지한다 | 안 씀 | 읽기+쓰기 |
| `query_matches` | 저장된 매칭 기록을 조건에 맞게 조회한다 | 안 씀 | 읽기 |
| `suggest_patterns` | 더 정확한 정규식 후보를 제안한다 (설정은 바꾸지 않는다) | 안 씀 | 읽기 |
| `collect_traffic` | 직접 둘러보는 동안 오간 요청 트래픽을 모아 저장한다 | **띄움** | 쓰기 |

---

## `run_scan()`

> `collect` 테이블에 모아 둔 트래픽에서 등록된 정규식 패턴을 탐지한다.

**파라미터 없음.** 브라우저를 띄우지 않고 저장된 데이터만 검사하므로, 패턴을 고쳐
몇 번이든 다시 돌릴 수 있다. `collect`가 비어 있으면 `ValueError`로 사유를 알린다.

| 설정 | 효과 |
|---|---|
| `patterns[]` | 탐지할 정규식. 이름 중복·컴파일 실패는 시작 전에 거부 |
| `filters.methods` | `["POST"]`처럼 주면 그 method 요청만 검사. **비우거나 지우면 전부 검사** |

`filters.methods`를 켜면 `method`가 없는 항목(응답 헤더·응답 바디·쿠키·콘솔)이
**함께 제외된다.** "나가는 데이터만 검사"할 때 쓰는 설정이다. 필터는 탐지 단계에
걸리므로, 바꿔서 다시 검사해도 데이터를 다시 모을 필요가 없다.

`targets`는 **수집** 단계 설정이라 `collect_traffic`에만 영향을 준다.

**반환**: `scan_id`, `source`, `chunks_total`, `chunks_scanned`, `status`,
`matches_total`, `matches_by_pattern`, `matches_by_location`, `method_filter`, `skipped`

**이 도구를 부르는 요청**

```
"수집된 트래픽에서 토큰 유출 있는지 확인해줘"
"지금 바로 다시 검사해줘"
"저장된 결과 말고 새로 확인해줘"
```

---

## `query_matches(...)`

> 저장된 매칭 기록을 조건에 맞게 조회한다.

| 파라미터 | 기본 | 의미 |
|---|---|---|
| `pattern_name` | `None` | 그 패턴의 매칭만 |
| `url_substring` | `None` | URL에 이 문자열이 포함된 매칭만 |
| `date_from` / `date_to` | `None` | 기간. `2026-09-03`처럼 날짜만 줘도 그날 전체가 포함된다 |
| `scan_id` | `None` | 특정 스캔 회차의 매칭만 |
| `limit` | `100` | 최신순 최대 건수 |

조건은 AND로 결합되고, 하나도 안 주면 최근 `limit`건을 돌려준다.

**반환** (행마다): `id`, `scan_id`, `pattern_name`, `matched_value`, `location`,
`url`, `matched_at`, `detail`

`url`은 매칭된 값이 아니라 **값이 발견된 리소스 URL**이다. 실제로 걸린 값은
`matched_value`, 방문한 페이지는 `detail.page_url`, 그 값이 있던 문장은 `detail.context`다.

**이 도구를 부르는 요청**

```
"최근 jwt-token 매칭 결과 보여줘"          → pattern_name
"naver.com 에서 나온 매칭만 골라서 보여줘"   → url_substring
"오늘 발견된 매칭 있으면 알려줘"            → date_from
"scan_id 1 결과 요약해줘"                 → scan_id
```

`location` 필터는 도구 인자에 없다. "헤더에서 발견된 것만"처럼 물으면 조회 후
응답에서 걸러 설명한다.

---

## `suggest_patterns(...)`

> 정규식 후보를 제안한다. 분석 대상은 `source`로 고른다.

**`data/patterns.json`을 변경하지 않는다** — 제안만 돌려주고 채택은 사람이 판단한다.

| 파라미터 | 기본 | 의미 |
|---|---|---|
| `source` | `"matches"` | `"matches"` 또는 `"collect"`. 그 외 값은 `ValueError` |
| `min_cluster` | `3` | 서로 다른 값이 이보다 적은 군집·키는 건너뛴다(과적합 방지) |
| `limit` | `1000` | 읽을 행 수. `source="collect"`면 **본문 있는 행만** 센다 |
| `pattern_name`, `scan_id` | `None` | `source="matches"`에서만 쓰인다 |

### `source="matches"` — 쓰던 정규식을 다듬는다

이미 그 패턴에 **걸린 값들**을 분석한다. 두 방향으로 일한다.

**넓게 잡는 패턴은 좁힌다.** 관측된 형태만 허용하는 후보를 만들고, 기존에 잡던 값을
하나도 놓치지 않는 것만 통과시킨다.

```
현재 : https://[a-z.]+naver\.com
후보 : https://(?:[a-z]+\.)+naver\.com(?![\w.-])
       → https://notnaver.com 같은 오탐을 배제하면서 기존 매칭은 유지
```

**하나도 못 잡는 패턴은 원인을 짚는다.** 귀납할 재료가 없으므로 반대로 정규식을
축별(수량자/문자클래스/구분자/리터럴/스킴)로 완화해 어디가 병목인지 찾는다.

```
sk_live_[A-Za-z0-9]{24,} → 0건
  [literal] sk_(?:live|test|prod|dev)_... → +1건   ← 'live' 고정이 원인
```

**반환**: `source`, `patterns[]`(패턴별 `current_regex`, `distinct_values`,
`candidates`, `relaxations`, `only_this_pattern_catches`, `note`), `corpus_size`

`corpus_size`는 **검증에 쓴 부수 텍스트 수**이며 `collect` 테이블과 무관하다.

### `source="collect"` — 아직 안 잡힌 값에서 새 패턴을 찾는다

`collect` 테이블의 **요청 본문**을 분석한다. 본문을 통째로 귀납하면 의미 있는 정규식이
나오지 않으므로, JSON 본문의 **같은 키끼리 값을 모아** 키별로 귀납한다.

```
bodies_analyzed 14 / json_keys_found 49 / candidates 20

json_key      regex                  support
adCntsSeq     1[0-9]{8,}                 34
expsTrtrCd    00[0-9]{4}                 13
bizCd         04[0-9]{2}01                4
```

기준이 될 기존 정규식이 없어 **회귀 판정을 못 한다** — 채택 게이트가 컴파일 가능·
ReDoS 없음·커버리지만 본다.

**반환**: `source`, `bodies_analyzed`, `json_keys_found`, `keys_too_few_values`,
`candidates[]`(`json_key`, `regex`, `variant`, `support`, `coverage`, `tightness`, `samples`)

**이 도구를 부르는 요청**

```
"test-any-url 패턴이 너무 넓게 잡히는데 더 좁은 정규식 없어?"   → source=matches
"custom-secret 이 왜 하나도 안 잡히는지 알려줘"               → source=matches (완화 사다리)
"collect 테이블 body가 null 이 아닌 데이터에 대해 패턴 추출해줘"  → source=collect
"수집된 트래픽 본문에서 정규식 후보 찾아줘"                     → source=collect
```

---

## `collect_traffic(start_url=None)`

> 브라우저를 띄워 사용자가 직접 둘러보는 동안 오간 요청 트래픽을 수집해 저장한다.

| 파라미터 | 기본 | 의미 |
|---|---|---|
| `start_url` | `None` | 처음 열 페이지. 없으면 빈 탭으로 시작한다 |

점검 대상 URL 목록 파일 대신 실제 브라우징을 기록해 검사 대상을 만든다.

동작 순서:

1. 창이 열린다 (`start_url`이 있으면 그 페이지로)
2. 원하는 페이지를 둘러본다. 새 탭·팝업에서 오간 것도 잡힌다
3. **터미널에서 Enter**를 누르면 종료. 창을 먼저 닫아도 종료로 본다
4. 관측 덩어리마다 위치·텍스트·URL·부가정보가 `collect` 테이블에 즉시 저장된다

수집 위치는 `patterns.json`의 `targets`가 정한다.

| `targets` | 수집 위치 |
|---|---|
| `network.headers` | 요청·응답 헤더 → `header` |
| `network.body` | 응답 바디 → `body` |
| `network.requestBody` | 요청 페이로드 → `request_body` |
| `network.cookies` | 쿠키 → `cookie` |
| `console` | 콘솔 로그·JS 에러 → `console` |

**반환**: `chunks_collected`, `saved_to`, `collect_by_location`, `note`

**이 도구를 부르는 요청**

```
"url 수집"
"직접 둘러보면서 트래픽 모아줘"
```

이후 `run_scan`을 부르면 모아 둔 트래픽을 대상으로 탐지한다. 사람 개입이 필요 없다.

---

## 주의할 점

**`collect` 테이블은 `matches`보다 민감하다.** 정규식을 거치지 않은 원본 요청이라
쿠키·`Authorization` 헤더·POST 본문의 자격증명이 그대로 담긴다. `data/scan.db`는
`.gitignore` 대상이지만 파일 자체는 로컬에 남는다.

**로그인 세션은 저장하지 않는다.** 구현했다가 제거했다 — `storage_state()`가 컨텍스트의
모든 쿠키를 내보내 점검 대상과 무관한 메일·금융 세션까지 평문 파일 하나에 모이기 때문이다.
그래서 로그인해야 보이는 페이지는 `collect_traffic` 중에만 관찰되고 `run_scan` 재현 시에는
비로그인 상태로 접근한다.

**`[MATCH]` 줄은 매칭된 값을 그대로 출력한다** ([verification.md](verification.md) 6-6).
표준출력으로 나가므로 파이프·리다이렉트 시 값이 파일에 남는다.
