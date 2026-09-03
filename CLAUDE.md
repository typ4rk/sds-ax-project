# 프로젝트 규칙

## 기술 스택
- Python, LangChain, LangGraph
- 모델: Amazon Bedrock (`ChatBedrockConverse`), 모델 ID/리전은 `.env`로 관리
- Agent 생성: `langchain.agents.create_agent`
- 브라우저 제어: Playwright (Python)
- 저장소: 이 레포지 (`C:\source\project\my-pjt`)에 재사용 가능한 Python 프로젝트로 구축

## 폴더 구조 (제출 규약. 바꾸지 않는다)

```
my-pjt/
├── requirements.txt
├── .env.example
├── src/
│   ├── main.py            # 실행 진입점: 자연어 요청을 받아 에이전트 호출
│   ├── agent.py            # 메인 에이전트 그래프 (LangGraph ReAct 루프)
│   ├── tools.py             # 도메인 도구: collect_traffic(트래픽 수집), run_scan(탐지),
│   │                        #             query_matches(조회), suggest_patterns(패턴 제안)
│   └── retriever.py         # 단순 조회 헬퍼 (임베딩/RAG 아님 — SQLite 필터 조회)
├── data/                   # 사용한 문서와 데이터 (patterns.json, scan.db)
└── evaluation/
    ├── test_queries.csv     # 평가용 질의 목록
    └── report.md            # 평가 리포트
```

세부 설명(내부 헬퍼 모듈 구성 포함): [design.md](design.md) 1절 참고

## 주고받는 형식 (제출 규약)

- 실행: `python -m src.main "<자연어 요청>"` (별도 서버 없이 CLI로 한 번 실행하고 종료)
- 입력: 사용자의 자연어 문자열 1개
- 출력: 에이전트의 최종 응답(자연어 요약)을 표준출력으로 출력. 스캔 중 매칭 발생 시 `[MATCH] ...`가 그 즉시 먼저 출력됨

세부 설명/예시: [design.md](design.md) 8절 참고


## 코드 규칙
- 파일 하나에 한 가지 역할만 둔다
- 함수와 도구에는 한국어 docstring 을 쓴다
- 비밀 값은 .env 에서 읽고 코드에 적지 않는다

## 하지 말 것
- 요청하지 않은 파일을 새로 만들지 않는다
- 기존 파일을 통째로 다시 쓰지 않는다. 바뀐 부분만 고친다