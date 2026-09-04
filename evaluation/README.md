# run_eval 실행 결과

(.venv) PS C:\source\sds-ax-project> py -m evaluation.run_eval
[1] 수집된 트래픽에서 개인정보 유출 있는지 확인해줘
[2] 최근 jwt-token 매칭 결과 보여줘
[3] 지금 바로 다시 검사해줘
[4] naver.com 에서 나온 매칭만 골라서 보여줘
[5] scan_id 1 결과 요약해줘
[6] custom-secret 패턴이 걸린 적 있어?
[7] 오늘 발견된 매칭 있으면 알려줘
[8] 저장된 결과 말고 새로 확인해줘
[9] 헤더에서 발견된 것만 있는지 확인해줘
[10] 점검하고 결과까지 정리해서 알려줘
[11] origin-body 패턴이 너무 넓게 잡히는데 더 좁은 정규식 없어?
[12] 지금 패턴이 놓치고 있는 게 있는지 보고 개선안 알려줘
[13] custom-secret 이 왜 하나도 안 잡히는지 알려줘
[14] collect 테이블 body가 null 이 아닌 데이터에 대해 패턴 추출해줘
[15] 수집된 트래픽 본문에서 정규식 후보 찾아줘
| id | question | expected_tool | 실제 호출 도구 | 판정 | 비고 |
|---|---|---|---|---|---|
| 1 | 수집된 트래픽에서 개인정보 유출 있는지 확인해줘 | detect_matches | detect_matches | PASS | 도구 1회, 11,587토큰 / jwt-token 언급 없음 |
| 2 | 최근 jwt-token 매칭 결과 보여줘 | query_matches | query_matches | PASS | 도구 1회, 11,456토큰 / jwt-token 언급함 |
| 3 | 지금 바로 다시 검사해줘 | detect_matches | detect_matches | PASS | 도구 1회, 11,404토큰 |
| 4 | naver.com 에서 나온 매칭만 골라서 보여줘 | query_matches | query_matches | PASS | 도구 1회, 12,234토큰 |
| 5 | scan_id 1 결과 요약해줘 | query_matches | query_matches | PASS | 도구 1회, 12,024토큰 |
| 6 | custom-secret 패턴이 걸린 적 있어? | query_matches | query_matches | PASS | 도구 1회, 11,415토큰 / custom-secret 언급함 |
| 7 | 오늘 발견된 매칭 있으면 알려줘 | query_matches | query_matches | PASS | 도구 1회, 11,387토큰 |
| 8 | 저장된 결과 말고 새로 확인해줘 | detect_matches | detect_matches | PASS | 도구 1회, 11,479토큰 |
| 9 | 헤더에서 발견된 것만 있는지 확인해줘 | query_matches | query_matches | PASS | 도구 1회, 29,367토큰 |
| 10 | 점검하고 결과까지 정리해서 알려줘 | detect_matches | detect_matches | PASS | 도구 1회, 11,554토큰 |
| 11 | origin-body 패턴이 너무 넓게 잡히는데 더 좁은 정규식 없어? | suggest_patterns | suggest_patterns | PASS | 도구 1회, 11,970토큰 / origin-body 언급함 |
| 12 | 지금 패턴이 놓치고 있는 게 있는지 보고 개선안 알려줘 | suggest_patterns | suggest_patterns | PASS | 도구 1회, 14,295토큰 |
| 13 | custom-secret 이 왜 하나도 안 잡히는지 알려줘 | suggest_patterns | query_matches, suggest_patterns | PASS | 도구 2회, 14,282토큰 / custom-secret 언급함 |
| 14 | collect 테이블 body가 null 이 아닌 데이터에 대해 패턴 추출해줘 | suggest_patterns | suggest_patterns | PASS | 도구 1회, 13,367토큰 |
| 15 | 수집된 트래픽 본문에서 정규식 후보 찾아줘 | suggest_patterns | suggest_patterns | PASS | 도구 1회, 13,459토큰 |

결과: 15/15 통과
  detect_matches     4/4
  query_matches      6/6
  suggest_patterns   5/5
기록: C:\source\sds-ax-project\evaluation\eval_result.json