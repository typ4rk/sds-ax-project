# 평가 리포트

`evaluation/test_queries.csv`를 `python evaluation/run_eval.py`로 실제 실행한 결과를 기록한다.
문항별 원본 기록은 `evaluation/eval_result.json`, 호출 단위 기록은 `evaluation/eval_trace.jsonl`에 남는다
(둘 다 실행할 때마다 바뀌므로 커밋하지 않는다).

> **상태: 에이전트 경로 실행 완료.** 16문항을 모두 돌려 **13/16 통과**했다.
> 이전에 막혀 있던 Bedrock 일일 토큰 쿼터는 해소되었다. 총 204,197토큰을 썼다
> (문항당 평균 12,762).
>
> 도구 함수를 직접 호출하는 경로는 [verification.md](../verification.md) 73건 중 43건을 확인했다
> (2절). 나머지 30건은 여전히 미실행이다.
>
> 실행 방법:
> ```bash
> python evaluation/run_eval.py                # 전체
> python evaluation/run_eval.py --ids 1,2,3    # 일부만
> python evaluation/run_eval.py --dry-run      # 에이전트 호출 없이 점검
> ```

## 1. 질의별 결과

판정 기준은 **기대한 도구를 실제로 불렀는가** 하나다. 답변 문장의 품질은 사람이 본다.

| id | question | expected_tool | 실제 호출 도구 | 판정 | 비고 |
|---|---|---|---|---|---|
| 1 | 수집된 트래픽에서 개인정보 유출 있는지 확인해줘 | detect_matches | detect_matches | Pass | 도구 1회, 11,530토큰 / jwt-token 언급 없음 |
| 2 | 최근 jwt-token 매칭 결과 보여줘 | query_matches | query_matches | Pass | 도구 1회, 11,552토큰 / jwt-token 언급함 |
| 3 | 지금 바로 다시 검사해줘 | detect_matches | detect_matches | Pass | 도구 1회, 11,384토큰 |
| 4 | naver.com 에서 나온 매칭만 골라서 보여줘 | query_matches | query_matches | Pass | 도구 1회, 12,152토큰 |
| 5 | scan_id 1 결과 요약해줘 | query_matches | query_matches | Pass | 도구 1회, 12,034토큰 |
| 6 | custom-secret 패턴이 걸린 적 있어? | query_matches | query_matches | Pass | 도구 1회, 11,410토큰 / custom-secret 언급함 |
| 7 | 오늘 발견된 매칭 있으면 알려줘 | query_matches | query_matches | Pass | 도구 1회, 11,277토큰 |
| 8 | 저장된 결과 말고 새로 확인해줘 | detect_matches | detect_matches | Pass | 도구 1회, 11,466토큰 |
| 9 | 헤더에서 발견된 것만 있는지 확인해줘 | query_matches | query_matches | Pass | 도구 1회, 29,295토큰 |
| 10 | 점검하고 결과까지 정리해서 알려줘 | detect_matches | detect_matches | Pass | 도구 1회, 11,562토큰 |
| 11 | origin-body 패턴이 너무 넓게 잡히는데 더 좁은 정규식 없어? | suggest_patterns | suggest_patterns | Pass | 도구 1회, 12,066토큰 / origin-body 언급함 |
| 12 | 지금 패턴이 놓치고 있는 게 있는지 보고 개선안 알려줘 | suggest_patterns | suggest_patterns | Pass | 도구 1회, 13,017토큰 |
| 13 | custom-secret 이 왜 하나도 안 잡히는지 알려줘 | suggest_patterns | query_matches | Fail | 도구 1회, 11,648토큰 / custom-secret 언급함 |
| 14 | collect 테이블 content 컬럼이 null 이 아닌 데이터에 대해 패턴 추출해줘 | suggest_patterns | - | Error | ValueError: collect 테이블에서 조회할 수 있는 텍스트 컬럼이 아닙니다: 'body' (가능: content, detail_json) |
| 15 | 수집된 트래픽 본문에서 정규식 후보 찾아줘 | suggest_patterns | suggest_patterns | Pass | 도구 1회, 13,724토큰 |
| 16 | collect 테이블에 마스킹 없이 저장된 민감 데이터가 있는지 확인해줘 | detect_matches | suggest_patterns | Fail | 도구 1회, 14,441토큰 |

**도구 선택 정확도:** 13 / 16

### 실패 3건

**13번 — 조회로 끝내고 분석 도구를 부르지 않았다.**
`query_matches`로 매칭을 찾다가 0건이 나오자, `suggest_patterns`의 완화 사다리로 넘어가지 않고
사용자에게 되물었다("collect 테이블에 데이터가 있나요?"). 이 문항이 요구하는 것은
`relaxations`의 병목 축을 근거로 한 설명이다. 시스템 프롬프트가 "왜 안 잡히는지" 유형을
`suggest_patterns`로 보내도록 더 분명히 적어야 한다.

**14번 — 도구 예외가 실행을 끝냈다 (Error).**
질문은 `content` 컬럼을 지목했는데 모델이 `column="body"`를 넘겼고, `tools.py`가
`ValueError: ... 'body' (가능: content, detail_json)`를 던졌다. 이 예외는
`agent.invoke()` 밖으로 나가 문항 자체가 중단됐다.

메시지에 이미 유효한 값(`content`, `detail_json`)이 적혀 있으므로, 예외 대신 그 문자열을
**반환**했다면 모델이 인자를 고쳐 다시 부를 수 있었다. `todo.md` 1번(도구 예외를 안내
문자열로)이 겨냥한 상황이 실제로 발생한 사례다.

**16번 — 질문이 두 도구 사이에서 모호하다.**
"collect 테이블에 마스킹 없이 저장된 민감 데이터가 있는지"에 `suggest_patterns(source=collect)`를
불렀다. 기대는 `detect_matches`였다. 다만 모델의 선택도 근거가 있다 — 그 도구도 `collect`를
분석하고, 실제 답변은 "비즈니스 식별자가 대부분이고 민감 정보는 발견되지 않았다"로 타당했다.
문항 문구를 "등록된 패턴으로 다시 검사해"처럼 좁히거나, 기대 도구를 둘 다 허용하도록
판정을 고치는 편이 맞다.

### 비용 관찰

9번(`헤더에서 발견된 것만 있는지 확인해줘`)이 **29,295토큰**으로 다른 문항의 2.5배다.
`eval_trace.jsonl`이 원인을 보여준다 — `query_matches`가 큰 결과를 물어오면서 다음 LLM
호출의 입력이 뛴다. `limit` 기본값(100)을 줄이거나 요약에 필요한 만큼만 조회하도록
도구 설명을 손볼 자리다.

## 2. 기능별 검증

[verification.md](../verification.md)의 케이스 73건을 기능별로 집계한다.
개별 케이스의 판정 기준은 그 파일을 따른다.

| 기능 | 설계 대응 | 케이스 | Pass | Fail | 미실행 |
|---|---|---|---|---|---|
| 1-x 수집 | `_browser.record_session()`, `tools.collect_traffic()` | 13 | 9 | 0 | 4 |
| 2-x 탐지 | `src/_matcher.py`, `data/patterns.json` | 12 | 7 | 0 | 5 |
| 3-x 매칭 기록 | `matches` 테이블 컬럼 구성 | 7 | 3 | 0 | 4 |
| 4-x 저장 | `src/_storage.py` | 8 | 2 | 0 | 6 |
| 5-x 조회 | `src/retriever.py`, `tools.query_matches()` | 14 | 6 | 0 | 8 |
| 6-x 알림 | `src/_notify.py` | 6 | 3 | 0 | 3 |
| 7-x 패턴 도출 | `src/_induce.py`, `tools.suggest_patterns()` | 13 | 13 | 0 | 0 |
| **합계** | | **73** | **43** | **0** | **30** |

현재 통과율 **43/73 (59%)** — 출시 기준(90%) 미달. Fail은 아직 없고 전부 미실행이다.
확인된 43건의 목록은 [verification.md](../verification.md) 「현재까지 확인된 항목」 참고.

## 3. 성공 기준 대비

[service.md](../service.md) 「성공 기준」 8개 항목 기준.
대응 케이스는 [verification.md](../verification.md) 「성공 기준 대응」 표를 따른다.

| # | 기준 | 대응 | 판정 | 비고 |
|---|---|---|---|---|
| 1 | 단발 실행 | 별도 확인 | 부분 확인 | 에이전트 경로 16회가 모두 응답까지 완결. 다만 run_eval은 한 프로세스에서 invoke를 반복하므로 `python -m src.main` 1회 실행 종료는 따로 확인해야 한다 |
| 2 | 도구 선택 정확성 | test_queries.csv | **미달** | 전체 13/16. detect/query 구분만 보면 10/11로 문제 없고, 실패는 전부 `suggest_patterns` 계열(13·14·16)이다 |
| 3 | 탐지 정확도 | 2-1, 2-2, 2-9, 2-10, 7-4, 7-5 | **Pass** | 6건 모두 확인됨 |
| 4 | 내결함성 | 1-9, 2-12, 4-3, 4-4 | 부분 확인 | 3/4 확인 (4-4 미실행) |
| 5 | 데이터 무결성 | 3-1 ~ 3-7, 5-8 | 부분 확인 | 3/8 확인 (3-1, 3-3, 3-7). 매칭 값 원본 보존(3-1)은 확인됨 |
| 6 | 즉시성 | 6-1, 6-3 | 부분 확인 | 6-1 확인, 6-3(출력 순서) 미실행 |
| 7 | 재현성 | 4-7 | **미확인** | 대응 케이스 1건이 미실행이다 |
| 8 | 전체 통과율 90% | 73건 전체 | **미달** | 43/73 (59%) |

### 다음에 볼 것

- **2번**을 올리려면 13·14·16번 각각의 원인이 다르다 — 프롬프트(13), 도구 예외 처리(14),
  문항 문구(16). 14번은 코드 변경이 필요하고 나머지 둘은 문서·문항 수정이다.
- **7번(재현성)**은 케이스가 4-7 하나뿐이라 실행 비용이 낮다. 먼저 채우면 성공 기준 하나가
  바로 판정 가능해진다.
- **8번**은 미실행 30건이 남아 있어, 새 기능을 더하기보다 기존 케이스를 돌리는 편이
  통과율을 빨리 올린다.
