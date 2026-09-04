# run_eval 실행 결과 (예시)

## eval_result.json (stdout 출력문)
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
[14] collect 테이블 content 컬럼이 null 이 아닌 데이터에 대해 패턴 추출해줘
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
| 14 | collect 테이블 content 컬럼이 null 이 아닌 데이터에 대해 패턴 추출해줘 | suggest_patterns | suggest_patterns | PASS | 도구 1회, 13,367토큰 |
| 15 | 수집된 트래픽 본문에서 정규식 후보 찾아줘 | suggest_patterns | suggest_patterns | PASS | 도구 1회, 13,459토큰 |

결과: 15/15 통과
  detect_matches     4/4
  query_matches      6/6
  suggest_patterns   5/5
기록: C:\source\sds-ax-project\evaluation\eval_result.json

## eval_trace.jsonl

{"case_id": "1", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.802, "ts": "2026-09-04 12:38:10", "input_tokens": 5484, "output_tokens": 90}
{"case_id": "1", "seq": 1, "event": "tool", "name": "detect_matches", "latency_s": 0.049, "ts": "2026-09-04 12:38:10", "result_chars": 218}
{"case_id": "1", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 3.23, "ts": "2026-09-04 12:38:13", "input_tokens": 5665, "output_tokens": 291}
{"case_id": "2", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.513, "ts": "2026-09-04 12:38:14", "input_tokens": 5474, "output_tokens": 110}
{"case_id": "2", "seq": 1, "event": "tool", "name": "query_matches", "latency_s": 0.002, "ts": "2026-09-04 12:38:14", "result_chars": 2}
{"case_id": "2", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 3.606, "ts": "2026-09-04 12:38:18", "input_tokens": 5596, "output_tokens": 372}
{"case_id": "3", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.265, "ts": "2026-09-04 12:38:19", "input_tokens": 5470, "output_tokens": 64}
{"case_id": "3", "seq": 1, "event": "tool", "name": "detect_matches", "latency_s": 0.052, "ts": "2026-09-04 12:38:19", "result_chars": 218}
{"case_id": "3", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 2.741, "ts": "2026-09-04 12:38:22", "input_tokens": 5625, "output_tokens": 225}
{"case_id": "4", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.339, "ts": "2026-09-04 12:38:23", "input_tokens": 5479, "output_tokens": 88}
{"case_id": "4", "seq": 1, "event": "tool", "name": "query_matches", "latency_s": 0.002, "ts": "2026-09-04 12:38:23", "result_chars": 1626}
{"case_id": "4", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 3.375, "ts": "2026-09-04 12:38:27", "input_tokens": 6263, "output_tokens": 322}
{"case_id": "5", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.382, "ts": "2026-09-04 12:38:28", "input_tokens": 5469, "output_tokens": 98}
{"case_id": "5", "seq": 1, "event": "tool", "name": "query_matches", "latency_s": 0.002, "ts": "2026-09-04 12:38:28", "result_chars": 1333}
{"case_id": "5", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 3.074, "ts": "2026-09-04 12:38:31", "input_tokens": 6148, "output_tokens": 319}
{"case_id": "6", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.593, "ts": "2026-09-04 12:38:33", "input_tokens": 5473, "output_tokens": 94}
{"case_id": "6", "seq": 1, "event": "tool", "name": "query_matches", "latency_s": 0.002, "ts": "2026-09-04 12:38:33", "result_chars": 2}
{"case_id": "6", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 2.792, "ts": "2026-09-04 12:38:36", "input_tokens": 5579, "output_tokens": 264}
{"case_id": "7", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.442, "ts": "2026-09-04 12:38:37", "input_tokens": 5476, "output_tokens": 108}
{"case_id": "7", "seq": 1, "event": "tool", "name": "query_matches", "latency_s": 0.002, "ts": "2026-09-04 12:38:37", "result_chars": 2}
{"case_id": "7", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 1.43, "ts": "2026-09-04 12:38:38", "input_tokens": 5596, "output_tokens": 97}
{"case_id": "8", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.595, "ts": "2026-09-04 12:38:40", "input_tokens": 5474, "output_tokens": 104}
{"case_id": "8", "seq": 1, "event": "tool", "name": "detect_matches", "latency_s": 0.027, "ts": "2026-09-04 12:38:40", "result_chars": 218}
{"case_id": "8", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 2.429, "ts": "2026-09-04 12:38:43", "input_tokens": 5669, "output_tokens": 219}
{"case_id": "9", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.189, "ts": "2026-09-04 12:38:44", "input_tokens": 5478, "output_tokens": 65}
{"case_id": "9", "seq": 1, "event": "tool", "name": "query_matches", "latency_s": 0.005, "ts": "2026-09-04 12:38:44", "result_chars": 42587}
{"case_id": "9", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 4.532, "ts": "2026-09-04 12:38:48", "input_tokens": 23377, "output_tokens": 375}
{"case_id": "10", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.338, "ts": "2026-09-04 12:38:50", "input_tokens": 5475, "output_tokens": 69}
{"case_id": "10", "seq": 1, "event": "tool", "name": "detect_matches", "latency_s": 0.033, "ts": "2026-09-04 12:38:50", "result_chars": 218}
{"case_id": "10", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 3.722, "ts": "2026-09-04 12:38:53", "input_tokens": 5635, "output_tokens": 383}
{"case_id": "11", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.773, "ts": "2026-09-04 12:38:55", "input_tokens": 5490, "output_tokens": 151}
{"case_id": "11", "seq": 1, "event": "tool", "name": "suggest_patterns", "latency_s": 0.003, "ts": "2026-09-04 12:38:55", "result_chars": 472}
{"case_id": "11", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 4.993, "ts": "2026-09-04 12:39:00", "input_tokens": 5925, "output_tokens": 500}
{"case_id": "12", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.632, "ts": "2026-09-04 12:39:02", "input_tokens": 5489, "output_tokens": 101}
{"case_id": "12", "seq": 1, "event": "tool", "name": "suggest_patterns", "latency_s": 0.013, "ts": "2026-09-04 12:39:02", "result_chars": 1918}
{"case_id": "12", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 6.672, "ts": "2026-09-04 12:39:08", "input_tokens": 6669, "output_tokens": 758}
{"case_id": "13", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.453, "ts": "2026-09-04 12:39:10", "input_tokens": 5480, "output_tokens": 118}
{"case_id": "13", "seq": 1, "event": "tool", "name": "query_matches", "latency_s": 0.002, "ts": "2026-09-04 12:39:10", "result_chars": 2}
{"case_id": "13", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 4.216, "ts": "2026-09-04 12:39:14", "input_tokens": 5610, "output_tokens": 440}
{"case_id": "14", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.799, "ts": "2026-09-04 12:39:16", "input_tokens": 5489, "output_tokens": 150}
{"case_id": "14", "seq": 1, "event": "tool_error", "name": "suggest_patterns", "latency_s": 0.001, "ts": "2026-09-04 12:39:16", "error": "collect 테이블에서 조회할 수 있는 텍스트 컬럼이 아닙니다: 'body' (가능: content, detail_json)"}
{"case_id": "15", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 1.44, "ts": "2026-09-04 12:39:17", "input_tokens": 5482, "output_tokens": 109}
{"case_id": "15", "seq": 1, "event": "tool", "name": "suggest_patterns", "latency_s": 0.01, "ts": "2026-09-04 12:39:17", "result_chars": 3405}
{"case_id": "15", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 8.457, "ts": "2026-09-04 12:39:26", "input_tokens": 7098, "output_tokens": 1035}
{"case_id": "16", "seq": 0, "event": "llm", "name": "chat_model", "latency_s": 2.176, "ts": "2026-09-04 12:39:28", "input_tokens": 5491, "output_tokens": 227}
{"case_id": "16", "seq": 1, "event": "tool", "name": "suggest_patterns", "latency_s": 0.009, "ts": "2026-09-04 12:39:28", "result_chars": 5241}
{"case_id": "16", "seq": 2, "event": "llm", "name": "chat_model", "latency_s": 7.21, "ts": "2026-09-04 12:39:35", "input_tokens": 7987, "output_tokens": 736}
