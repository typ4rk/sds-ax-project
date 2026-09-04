# 평가 리포트

`evaluation/test_queries.csv`를 `python -m src.main "<question>"`으로 실제 실행한 결과를 기록한다.

> **상태: 부분 검증.** 도구 함수를 직접 호출하는 경로는 [verification.md](../verification.md)
> 71건 중 41건을 확인했다. 반면 **에이전트(LLM) 경로는 전부 미실행**이며, 아래 1절 질의별
> 결과는 채울 자리만 잡아둔 것이다. `.env`의 `BEDROCK_MODEL_ID`·`AWS_REGION`은 채워져 있고
> Bedrock 호출까지 도달하지만, 현재 Bedrock 일일 토큰 쿼터
> (`ThrottlingException: Too many tokens per day`)에 걸려 응답을 받지 못한다.
>
> 실행 방법:
> ```bash
> python -m src.main "수집된 트래픽에서 개인정보 유출 있는지 확인해줘"
> ```

## 1. 질의별 결과

| id | question | expected_tool | 실제 호출 도구 | 판정 | 비고 |
|---|---|---|---|---|---|
| 1 | 수집된 트래픽에서 개인정보 유출 있는지 확인해줘 | detect_matches | - | 미실행 | |
| 2 | 최근 jwt-token 매칭 결과 보여줘 | query_matches | - | 미실행 | |
| 3 | 지금 바로 다시 검사해줘 | detect_matches | - | 미실행 | |
| 4 | naver.com 에서 나온 매칭만 골라서 보여줘 | query_matches | - | 미실행 | |
| 5 | scan_id 1 결과 요약해줘 | query_matches | - | 미실행 | |
| 6 | custom-secret 패턴이 걸린 적 있어? | query_matches | - | 미실행 | |
| 7 | 오늘 발견된 매칭 있으면 알려줘 | query_matches | - | 미실행 | |
| 8 | 저장된 결과 말고 새로 확인해줘 | detect_matches | - | 미실행 | |
| 9 | 헤더에서 발견된 것만 있는지 확인해줘 | query_matches | - | 미실행 | |
| 10 | 점검하고 결과까지 정리해서 알려줘 | detect_matches | - | 미실행 | |

**도구 선택 정확도:** - / 10

## 2. 기능별 검증

[verification.md](../verification.md)의 케이스 71건을 기능별로 집계한다.
개별 케이스의 판정 기준은 그 파일을 따른다.

| 기능 | 설계 대응 | 케이스 | Pass | Fail | 미실행 |
|---|---|---|---|---|---|
| 1-x 수집 | `_browser.record_session()`, `tools.collect_traffic()` | 13 | 9 | 0 | 4 |
| 2-x 탐지 | `src/_matcher.py`, `data/patterns.json` | 12 | 7 | 0 | 5 |
| 3-x 매칭 기록 | `matches` 테이블 컬럼 구성 | 7 | 3 | 0 | 4 |
| 4-x 저장 | `src/_storage.py` | 8 | 2 | 0 | 6 |
| 5-x 조회 | `src/retriever.py`, `tools.query_matches()` | 14 | 6 | 0 | 8 |
| 6-x 알림 | `src/_notify.py` | 7 | 4 | 0 | 3 |
| 7-x 패턴 도출 | `src/_induce.py`, `tools.suggest_patterns()` | 10 | 10 | 0 | 0 |
| **합계** | | **71** | **41** | **0** | **30** |

현재 통과율 **41/71 (58%)** — 출시 기준(90%) 미달. Fail은 아직 없고 전부 미실행이다.
확인된 41건의 목록은 [verification.md](../verification.md) 「현재까지 확인된 항목」 참고.

## 3. 성공 기준 대비

[service.md](../service.md) 「성공 기준」 8개 항목 기준.

| # | 기준 | 판정 | 비고 |
|---|---|---|---|
| 1 | 단발 실행 | 미실행 | |
| 2 | 도구 선택 정확성 | 미실행 | |
| 3 | 탐지 정확도 (거짓 음성/양성 없음) | 미실행 | |
| 4 | 내결함성 (일부 URL 실패해도 계속) | 미실행 | |
| 5 | 데이터 무결성 | 미실행 | |
| 6 | 즉시성 | 미실행 | |
| 7 | 재현성 | 미실행 | |
| 8 | 전체 통과율 90% 이상 | 미실행 | |
